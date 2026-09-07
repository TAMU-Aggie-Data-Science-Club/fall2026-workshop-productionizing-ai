"""The two model tiers Nimbus can serve from.

Both are loaded ONCE, at import, and reused for every request. Loading a model
inside a request handler is the most common LLM deployment mistake there is --
and here it would also make every latency number you measure meaningless.
"""
import asyncio
import copy
import hashlib
import os
import threading

import torch
from transformers import (AutoModelForCausalLM, AutoTokenizer, DynamicCache,
                          TextIteratorStreamer)

# Two tiers so that "route the easy questions to the cheaper model" is a real
# lever with a real effect, not a simulation. Both are small enough to run on
# CPU; the large one is roughly 2.5x the work of the small one.
TIERS = {
    "small": "HuggingFaceTB/SmolLM2-135M-Instruct",
    "large": "HuggingFaceTB/SmolLM2-360M-Instruct",
}

_loaded: dict[str, tuple] = {}
LOCAL_ONLY = os.environ.get("NIMBUS_ALLOW_MODEL_DOWNLOAD") != "1"


class WeightsMissing(RuntimeError):
    """Raised instead of a huggingface traceback when the cache is empty."""


def load(tier: str):
    """Load a tier on first use and keep it. Called at startup, not per request."""
    if tier not in _loaded:
        name = TIERS[tier]
        try:
            return _load_tier(tier, name)
        except Exception as exc:  # noqa: BLE001
            raise WeightsMissing(
                f"\n\n  Model weights for '{name}' are not downloaded yet.\n"
                f"  Run this once, then start the server again:\n\n"
                f"      .venv/bin/python .devcontainer/prefetch.py\n\n"
                f"  (original error: {type(exc).__name__})\n") from exc
    return _loaded[tier]


def _load_tier(tier: str, name: str):
    if tier not in _loaded:
        tokenizer = AutoTokenizer.from_pretrained(name, local_files_only=LOCAL_ONLY)
        model = AutoModelForCausalLM.from_pretrained(
            name, dtype=torch.float32, local_files_only=LOCAL_ONLY)
        model.eval()
        _loaded[tier] = (tokenizer, model)
    return _loaded[tier]


def warm() -> None:
    """Load every tier up front so the first real request does not pay for it."""
    for tier in TIERS:
        load(tier)


# ── Real prefix caching ───────────────────────────────────────────────────
# Not a discount invented in the cost model: we actually compute the attention
# KV cache for the static system-prompt block once, then reuse it so that every
# subsequent request skips re-reading those tokens. Measured on this stack:
# 2.43s -> 1.24s for one request, with byte-identical output.
#
# This is ALSO why build_prompt puts the static block FIRST and the varying
# question LAST. A prefix cache only helps up to the first byte that changes.
_prefix_seeds: dict[tuple[str, str], tuple[DynamicCache, int]] = {}


def prefix_seed(tier: str, prefix_text: str) -> tuple[DynamicCache, int]:
    """KV cache for a static prompt prefix, computed once per (tier, prefix)."""
    key = (tier, hashlib.sha256(prefix_text.encode()).hexdigest())
    if key not in _prefix_seeds:
        tokenizer, mdl = load(tier)
        ids = tokenizer(prefix_text, return_tensors="pt")
        cache = DynamicCache()
        with torch.no_grad():
            mdl(**ids, past_key_values=cache, use_cache=True)
        _prefix_seeds[key] = (cache, int(ids["input_ids"].shape[1]))
    return _prefix_seeds[key]


def count_tokens(tier: str, text: str) -> int:
    tokenizer, _ = load(tier)
    return len(tokenizer(text)["input_ids"])


def _run_generate(model, kwargs, result: dict) -> None:
    with torch.no_grad():
        result["output_ids"] = model.generate(**kwargs)


async def generate(tier: str, prompt: str, max_tokens: int, stats: dict,
                   prefix_text: str | None = None):
    """Stream generated text one chunk at a time.

    Streaming is not a nicety here: without a first-chunk timestamp there is no
    TTFT to measure, and TTFT is half of what the benchmark is for.

    Records token counts into `stats` so the caller can price the request.
    `prefix_text`, when given, is served from the reusable KV cache: those tokens
    are still input tokens, but they are not recomputed and they bill at the
    cached rate.
    """
    tokenizer, model = load(tier)
    inputs = tokenizer(prompt, return_tensors="pt")
    stats["tokens_in"] = int(inputs["input_ids"].shape[1])
    stats["tokens_out"] = 0
    stats["tokens_cached"] = 0

    past = None
    if prefix_text and prompt.startswith(prefix_text):
        seed, prefix_len = prefix_seed(tier, prefix_text)
        # Generation mutates the cache, so every request needs its own copy.
        past = copy.deepcopy(seed)
        stats["tokens_cached"] = prefix_len

    streamer = TextIteratorStreamer(tokenizer, skip_prompt=True, skip_special_tokens=True)
    kwargs = dict(
        **inputs,
        max_new_tokens=max_tokens,
        do_sample=False,
        pad_token_id=tokenizer.eos_token_id,
        streamer=streamer,
    )
    if past is not None:
        kwargs["past_key_values"] = past

    result = {}
    thread = threading.Thread(target=_run_generate, args=(model, kwargs, result), daemon=True)
    thread.start()

    loop = asyncio.get_running_loop()
    iterator = iter(streamer)
    while True:
        # next() blocks, so it has to leave the event loop or it stalls every
        # other in-flight request -- which would fake the queueing we want to
        # measure honestly.
        chunk = await loop.run_in_executor(None, next, iterator, None)
        if chunk is None:
            break
        if chunk:
            yield chunk

    # TextIteratorStreamer signals completion just before generate() returns.
    # Join the worker so its captured output is available before the caller
    # emits the final accounting event.
    await loop.run_in_executor(None, thread.join)
    output_ids = result.get("output_ids")
    if hasattr(output_ids, "sequences"):
        output_ids = output_ids.sequences
    if output_ids is not None:
        stats["tokens_out"] = max(
            0, int(output_ids.shape[-1]) - int(inputs["input_ids"].shape[-1]))
