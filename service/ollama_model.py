"""Local Ollama adapter used by the Docker Compose deployment.

Ollama owns the Llama weights and inference process in a sibling container.
Nimbus talks to its native streaming chat endpoint so the app remains small,
the model weights persist independently of app rebuilds, and Ollama's measured
prompt/output token counts can be carried into the existing benchmark report.

The adapter intentionally exposes the same contract as ``model.py`` and
``cloud_model.py``. It does not pull models during a request or at app startup;
the Compose ``ollama-pull-*`` services do that once into the persistent Ollama
volume before Nimbus starts serving traffic.
"""
import asyncio
import json
import os
from typing import Any, AsyncIterator

import httpx

import incident


class ProviderError(RuntimeError):
    """The local Ollama server could not complete a model request."""


class RetryableProviderError(ProviderError):
    """The local Ollama server may succeed if the request is retried."""


_http: httpx.AsyncClient | None = None


def _base_url() -> str:
    return os.environ.get("NIMBUS_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")


def _model_id(tier: str) -> str:
    if tier not in {"small", "large"}:
        raise ProviderError(f"Unknown model tier: {tier}")
    specific = os.environ.get(f"NIMBUS_OLLAMA_MODEL_{tier.upper()}")
    if specific:
        return specific
    return os.environ.get("NIMBUS_OLLAMA_MODEL", "llama3.1:8b")


def _timeout() -> float:
    try:
        value = float(os.environ.get("NIMBUS_OLLAMA_TIMEOUT_SECONDS", "360"))
    except ValueError as exc:
        raise ProviderError("NIMBUS_OLLAMA_TIMEOUT_SECONDS must be numeric") from exc
    if value <= 0:
        raise ProviderError("NIMBUS_OLLAMA_TIMEOUT_SECONDS must be greater than zero")
    return value


def _model_names(payload: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue
        for key in ("name", "model"):
            name = item.get(key)
            if isinstance(name, str):
                names.add(name)
    return names


def _has_model(installed: set[str], requested: str) -> bool:
    if requested in installed:
        return True
    # Ollama treats an omitted tag as :latest. Accept that spelling when a
    # caller uses a short model name such as "llama3.1".
    return ":" not in requested and f"{requested}:latest" in installed


def warm() -> None:
    """Validate Ollama and all configured tiers before accepting traffic."""
    requested = {_model_id("small"), _model_id("large")}
    try:
        response = httpx.get(f"{_base_url()}/api/tags", timeout=_timeout())
        if response.status_code >= 400:
            detail = response.text[:500]
            raise ProviderError(
                f"Ollama returned HTTP {response.status_code} from /api/tags: {detail}")
        payload = response.json()
    except ProviderError:
        raise
    except (httpx.RequestError, ValueError) as exc:
        raise ProviderError(
            f"Ollama is not reachable at {_base_url()}. Start the local stack with "
            "`make docker-up`." ) from exc

    installed = _model_names(payload)
    missing = sorted(name for name in requested if not _has_model(installed, name))
    if missing:
        joined = ", ".join(missing)
        raise ProviderError(
            f"Ollama is running but model(s) are not pulled: {joined}. "
            "Run `make docker-up` so the pull services can download them, or "
            "run `ollama pull <model>` yourself.")


def runtime_info() -> dict:
    """Return non-secret details for /metrics and benchmark records."""
    return {
        "provider": "ollama",
        "base_url": _base_url(),
        "model_small": _model_id("small"),
        "model_large": _model_id("large"),
    }


def _http_client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        timeout = _timeout()
        _http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 15.0)))
    return _http


def _update_usage(stats: dict, payload: dict[str, Any]) -> None:
    if "prompt_eval_count" in payload:
        stats["tokens_in"] = int(payload.get("prompt_eval_count") or 0)
    if "eval_count" in payload:
        stats["tokens_out"] = int(payload.get("eval_count") or 0)
    if "prompt_eval_count" in payload or "eval_count" in payload:
        stats["usage_source"] = "provider"


async def _stream_once(model_id: str, prompt: str, max_tokens: int,
                       stats: dict) -> AsyncIterator[str]:
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True,
        "keep_alive": os.environ.get("NIMBUS_OLLAMA_KEEP_ALIVE", "30m"),
        "options": {"temperature": 0, "num_predict": max_tokens},
    }
    emitted = False
    try:
        async with _http_client().stream(
                "POST", f"{_base_url()}/api/chat", json=payload) as response:
            if response.status_code in {408, 425, 429} or response.status_code >= 500:
                detail = (await response.aread()).decode(errors="replace")[:500]
                raise RetryableProviderError(
                    f"Ollama returned HTTP {response.status_code}: {detail}")
            if response.status_code >= 400:
                detail = (await response.aread()).decode(errors="replace")[:500]
                raise ProviderError(f"Ollama returned HTTP {response.status_code}: {detail}")

            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ProviderError("Ollama returned invalid JSON while streaming") from exc
                if not isinstance(event, dict):
                    continue
                _update_usage(stats, event)
                message = event.get("message") or {}
                content = message.get("content") if isinstance(message, dict) else None
                if isinstance(content, str) and content:
                    emitted = True
                    yield content
                if event.get("done"):
                    break
    except httpx.RequestError as exc:
        raise RetryableProviderError("Ollama network request failed") from exc

    if not emitted:
        raise ProviderError("Ollama returned no text")


async def close() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


async def generate(tier: str, prompt: str, max_tokens: int, stats: dict,
                   prefix_text: str | None = None):
    """Stream a locally generated answer using the selected Ollama model.

    ``prefix_text`` is accepted for adapter compatibility. Ollama manages its
    own loaded-model and prompt state, so Nimbus does not attempt to copy a
    Transformers KV cache into this HTTP request.
    """
    model_id = _model_id(tier)
    stats.update({"provider": "ollama", "model": model_id,
                  "usage_source": "unreported", "tokens_in": 0,
                  "tokens_out": 0, "tokens_cached": 0})
    # Same contract as the cloud adapter: retries are reported, not hidden.
    stats["upstream_retries"] = 0
    stats["provider_status"] = None
    try:
        retries = int(os.environ.get("NIMBUS_OLLAMA_RETRIES", "1"))
    except ValueError as exc:
        raise ProviderError("NIMBUS_OLLAMA_RETRIES must be an integer") from exc
    if not 0 <= retries <= 5:
        raise ProviderError("NIMBUS_OLLAMA_RETRIES must be between 0 and 5")

    for attempt in range(retries + 1):
        stats.update({"usage_source": "unreported", "tokens_in": 0,
                      "tokens_out": 0})
        yielded = False
        try:
            simulated = incident.provider_fault(prompt, attempt)
            if simulated is not None:
                raise RetryableProviderError(
                    f"Ollama returned HTTP {simulated}")
            async for text in _stream_once(model_id, prompt, max_tokens, stats):
                yielded = True
                yield text
            return
        except RetryableProviderError as exc:
            stats["provider_status"] = getattr(exc, "status_code", None)
            if yielded or attempt >= retries:
                stats["upstream_retries"] = attempt
                raise
            stats["upstream_retries"] = attempt + 1
            await asyncio.sleep(0.25 * (2 ** attempt))
