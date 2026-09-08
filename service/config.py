"""
╔══════════════════════════════════════════════════════════════════════════╗
║  THIS IS THE ONLY FILE YOU EDIT.                                         ║
║                                                                          ║
║  Change ONE setting, re-measure, and write down what moved. Changing two  ║
║  at once tells you that something helped, but not which thing.           ║
╚══════════════════════════════════════════════════════════════════════════╝

Every setting Nimbus exposes, with an honest note on what it actually does.
The list is not ordered by usefulness and it is not a checklist: which of
these is worth touching depends entirely on what your measurements say is
slow, and most of them will do nothing for your incident.

Find out what is slow first. The benchmark report breaks the time down for
you; the settings below cannot tell you which one you need.
"""

import os


# ─── RUNTIME BACKEND ──────────────────────────────────────────────────────
# Local mode keeps the original offline workshop path. The Docker Compose path
# sets this to "ollama" and uses a locally running Llama model. Cloud Run sets
# this to "google" and uses service/cloud_model.py; the model weights are
# never served by the Cloud Run container.
MODEL_BACKEND = os.environ.get("NIMBUS_MODEL_BACKEND", "local")
if MODEL_BACKEND not in {"local", "ollama", "google"}:
    raise ValueError("NIMBUS_MODEL_BACKEND must be 'local', 'ollama', or 'google'")


# ─── CACHING ─────────────────────────────────────────────────────────────
# Three different things that all get called "caching". They fail in
# different ways and they help with different problems.

RESPONSE_CACHE = False
# Exact-match cache keyed on the fully assembled prompt. During finals week a
# lot of customers ask the same question in the same words. A hit skips retrieval
# AND generation entirely, so it costs nothing at all.
#
# Note this is a RESPONSE cache -- it stores finished answers. That is a
# different thing from prompt caching below, and it is worth knowing which one
# people mean when they say "we added caching".

PREFIX_CACHE = False
# Prompt/prefix caching, the real thing. Every request re-reads the same system
# prompt block before it gets to your question. This computes the attention
# cache for that block ONCE and reuses it, so the model skips re-reading it.
#
# Unlike the response cache this does not skip generation -- you still pay for
# every output token. It discounts the repeated INPUT only. That is exactly how
# prompt caching works at every commercial provider, and why it matters that
# the static part of a prompt comes first and the varying part comes last.

SEMANTIC_CACHE = False
# Same idea, but matches questions that MEAN the same thing rather than ones
# spelled the same way. Reuses the embedding model retrieval already loaded,
# so it costs one extra vector comparison.
# Careful: a stale hit on a personalised or time-sensitive question is worse
# than a slow correct answer.

SEMANTIC_CACHE_THRESHOLD = 0.92
# Cosine similarity above which two questions count as "the same".
# Lower = more hits, more risk of answering the wrong question.


# ─── HOW MUCH WORK EACH REQUEST DOES ─────────────────────────────────────

MAX_TOKENS = 32
# Hard cap on generated tokens. Latency is roughly linear in this number,
# and output tokens cost several times what input tokens cost.
# Ask yourself: how long does a good answer to a study question
# actually need to be?

SYSTEM_PROMPT = "LONG"
# "LONG"    — the 1,200-token instruction block Nimbus shipped with
# "TRIMMED" — the 180-token version that says the same thing
# "VERBOSE" — asks for a fuller teaching answer; useful when testing decode
# Every request pays to re-read this. Nobody has ever audited it.

RETRIEVE_K = 4
# How many menu-note chunks get stuffed into the prompt. More context is
# not free: it lands in the prefill on every single request.


# ─── WHICH MODEL ANSWERS ─────────────────────────────────────────────────

ROUTE_EASY = False
# Send easy questions (short, factual, definitional) to the small model and
# keep the large one for the hard ones. No training required — it is a
# heuristic. Most traffic is easier than the model you sized for.

MODEL_TIER = "large"
# "large" | "small"
#
# ⚠  Setting this to "small" sends EVERY request to the small model. It will
#    make your latency and cost numbers look fantastic.
#    Before you ship it, look at what the eval card says about quality.


# ─── CAPACITY ────────────────────────────────────────────────────────────

MAX_CONCURRENT = 2
# How many requests are allowed to compute at once. Everything else waits in
# the queue — that wait is what `queue wait p95` measures.
#
# Raising this is NOT automatically a win. This box has a fixed number of
# cores; letting more requests in at once does not create more compute, it
# just moves the waiting from the queue into the model. Try it and look at
# what happens to p95 vs queue wait.

REPLICAS = 1
# Pretend replicas. Divides queue pressure, multiplies your bill.
# The only lever on this page that costs real money.


# ─── WHAT TO DO WHEN YOU CANNOT SERVE EVERYONE ───────────────────────────

SHED_ABOVE_QUEUE = None
# Set to an integer to reject requests with 429 + Retry-After once the queue
# is deeper than this. Failing fast and honestly beats timing out slowly —
# but every shed request is a customer who did not get an answer.


# ─── RUNTIME OVERRIDES ────────────────────────────────────────────────────
# The source-level values above remain the workshop's single control panel.
# Cloud Run cannot edit a checked-out file at runtime, so deployment variables
# may override the same settings without changing the local activity. This is
# intentionally applied last and is visible through /metrics.
def _env_bool(name: str, current: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return current
    if value.lower() not in {"0", "1", "false", "true", "no", "yes"}:
        raise ValueError(f"{name} must be true/false or 1/0")
    return value.lower() in {"1", "true", "yes"}


def _env_int(name: str, current: int | None) -> int | None:
    value = os.environ.get(name)
    return current if value is None else int(value)


RESPONSE_CACHE = _env_bool("NIMBUS_RESPONSE_CACHE", RESPONSE_CACHE)
PREFIX_CACHE = _env_bool("NIMBUS_PREFIX_CACHE", PREFIX_CACHE)
SEMANTIC_CACHE = _env_bool("NIMBUS_SEMANTIC_CACHE", SEMANTIC_CACHE)
if os.environ.get("NIMBUS_SEMANTIC_CACHE_THRESHOLD") is not None:
    SEMANTIC_CACHE_THRESHOLD = float(os.environ["NIMBUS_SEMANTIC_CACHE_THRESHOLD"])
MAX_TOKENS = _env_int("NIMBUS_MAX_TOKENS", MAX_TOKENS)
if os.environ.get("NIMBUS_SYSTEM_PROMPT") is not None:
    SYSTEM_PROMPT = os.environ["NIMBUS_SYSTEM_PROMPT"].upper()
RETRIEVE_K = _env_int("NIMBUS_RETRIEVE_K", RETRIEVE_K)
ROUTE_EASY = _env_bool("NIMBUS_ROUTE_EASY", ROUTE_EASY)
if os.environ.get("NIMBUS_MODEL_TIER") is not None:
    MODEL_TIER = os.environ["NIMBUS_MODEL_TIER"].lower()
MAX_CONCURRENT = _env_int("NIMBUS_MAX_CONCURRENT", MAX_CONCURRENT)
SHED_ABOVE_QUEUE = _env_int("NIMBUS_SHED_ABOVE_QUEUE", SHED_ABOVE_QUEUE)

# ─── THE LEVER SCHEMA ─────────────────────────────────────────────────────
# One definition of every setting a participant may change, and the bounds it
# must satisfy. Startup validation and the runtime /levers endpoint both read
# it, so a value applied to a running service gets exactly the checks a value
# read from the file gets. Two copies of these bounds is how a service ends up
# accepting at runtime what it would have rejected at boot.
#
# Deliberately absent: MODEL_BACKEND, REPLICAS and anything about the incident.
# The backend is a deployment fact, REPLICAS is a local simulation with no
# meaning on Cloud Run, and the incident is the thing being diagnosed.
LEVERS: dict[str, dict] = {
    "RESPONSE_CACHE":           {"type": "bool"},
    "PREFIX_CACHE":             {"type": "bool"},
    "SEMANTIC_CACHE":           {"type": "bool"},
    "SEMANTIC_CACHE_THRESHOLD": {"type": "float", "min": 0.0, "max": 1.0},
    "MAX_TOKENS":               {"type": "int", "min": 1, "max": 1024},
    "SYSTEM_PROMPT":            {"type": "choice", "choices": ("LONG", "TRIMMED", "VERBOSE")},
    "RETRIEVE_K":               {"type": "int", "min": 0, "max": 20},
    "ROUTE_EASY":               {"type": "bool"},
    "MODEL_TIER":               {"type": "choice", "choices": ("small", "large")},
    "MAX_CONCURRENT":           {"type": "int", "min": 1, "max": 64},
    "SHED_ABOVE_QUEUE":         {"type": "int", "min": 0, "nullable": True},
}

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def coerce_lever(name: str, value):
    """Validate and convert one lever value. Raises ValueError with a sentence
    a participant can act on, never a stack trace -- these arrive from a form
    under time pressure."""
    spec = LEVERS.get(name)
    if spec is None:
        raise ValueError(f"{name} is not a setting you can change. "
                         f"Available: {', '.join(sorted(LEVERS))}")
    kind = spec["type"]

    if value is None or (isinstance(value, str) and value.strip() == ""):
        if spec.get("nullable"):
            return None
        raise ValueError(f"{name} cannot be empty")

    if kind == "bool":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in _TRUE:
            return True
        if text in _FALSE:
            return False
        raise ValueError(f"{name} must be true or false, not {value!r}")

    if kind == "choice":
        text = str(value).strip()
        for choice in spec["choices"]:
            if text.lower() == choice.lower():
                return choice
        raise ValueError(f"{name} must be one of "
                         f"{' or '.join(spec['choices'])}, not {value!r}")

    if kind in {"int", "float"}:
        try:
            number = int(value) if kind == "int" else float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be a number, not {value!r}") from None
        low, high = spec.get("min"), spec.get("max")
        if low is not None and number < low:
            raise ValueError(f"{name} must be at least {low}, not {number}")
        if high is not None and number > high:
            raise ValueError(f"{name} must be at most {high}, not {number}")
        return number

    raise ValueError(f"{name} has an unknown type {kind!r}")


# Validate what the file and the environment produced, using the same rules a
# runtime change will be held to.
for _name in LEVERS:
    globals()[_name] = coerce_lever(_name, globals()[_name])
del _name
