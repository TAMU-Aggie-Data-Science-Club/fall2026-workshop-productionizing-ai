"""Fault injection for the incident investigations.

An incident degrades ONE part of the request path, in the way a real dependency
degrades, and nothing else. Participants get the symptom and the instruments;
they work out the cause. So this module is deliberately split from the answer:

    THIS FILE holds only the MECHANISM -- how a stage delay or a provider fault
    is applied. Reading it tells you that a retrieval delay is possible. It does
    not tell you whether yours is one.

    facilitators/incidents.py holds the CATALOG -- which incident sets which
    knob to what. That directory is already marked "not for participants".

The knobs arrive as environment variables at deploy time, so a participant with
the whole repository checked out still cannot read their own answer out of it.
Nothing here may be echoed into /metrics, /health, a trace event, a log line or
an error message: one leak turns an investigation into a lookup.

Reproducibility
---------------
Delays are seeded from the request text rather than drawn from a running
sequence. Under concurrency a shared generator hands out its values in whatever
order requests happen to arrive, so the same benchmark would produce different
per-request delays every run and a team could never reproduce its own
measurement. Keying on the question means the same question always draws the
same delay, which is what makes a before/after comparison mean anything.
"""
import asyncio
import hashlib
import math
import os
import random

_SEED = os.environ.get("NIMBUS_INCIDENT_SEED", "nimbus")

# "stage:distribution:p50_ms:p95_ms", comma-separated for several stages.
#   retrieve:lognormal:400:1800   a dependency whose tail is much worse than
#                                 its median -- the shape a real hosted service
#                                 degrades in, and the reason percentiles exist
#   retrieve:fixed:250            a constant delay; avoid, see below
_DELAY_SPEC = os.environ.get("NIMBUS_INCIDENT_STAGE_DELAY", "")

# "rate:status" -- e.g. "0.17:429". Applied per attempt, so the adapter's
# existing retry loop usually recovers and occasionally does not, which is
# exactly what a rate-limiting provider looks like from the inside.
_FAULT_SPEC = os.environ.get("NIMBUS_INCIDENT_PROVIDER_FAULT", "")


class IncidentConfigError(ValueError):
    """A malformed injection spec. Fail at startup, never mid-session."""


def _parse_delays(spec: str) -> dict[str, tuple[float, float]]:
    """Return {stage: (mu, sigma)} for a lognormal in log-milliseconds."""
    out: dict[str, tuple[float, float]] = {}
    for clause in (c.strip() for c in spec.split(",") if c.strip()):
        parts = clause.split(":")
        if len(parts) < 3:
            raise IncidentConfigError(
                f"stage delay {clause!r} must be stage:distribution:p50[:p95]")
        stage, distribution = parts[0], parts[1].lower()
        try:
            p50 = float(parts[2])
            p95 = float(parts[3]) if len(parts) > 3 else p50
        except ValueError as exc:
            raise IncidentConfigError(
                f"stage delay {clause!r} has non-numeric milliseconds") from exc
        if p50 <= 0 or p95 < p50:
            raise IncidentConfigError(
                f"stage delay {clause!r} needs 0 < p50 <= p95")
        if distribution == "fixed":
            p95 = p50
        elif distribution != "lognormal":
            raise IncidentConfigError(
                f"unknown distribution {distribution!r}; use lognormal or fixed")
        # median = exp(mu); p95 = exp(mu + 1.645 sigma)
        mu = math.log(p50)
        sigma = 0.0 if p95 <= p50 else (math.log(p95) - mu) / 1.645
        out[stage] = (mu, sigma)
    return out


def _parse_fault(spec: str) -> tuple[float, int]:
    if not spec.strip():
        return 0.0, 0
    parts = spec.split(":")
    try:
        rate = float(parts[0])
        status = int(parts[1]) if len(parts) > 1 else 429
    except ValueError as exc:
        raise IncidentConfigError(
            f"provider fault {spec!r} must be rate[:status]") from exc
    if not 0.0 <= rate <= 1.0:
        raise IncidentConfigError("provider fault rate must be between 0 and 1")
    return rate, status


_DELAYS = _parse_delays(_DELAY_SPEC)
_FAULT_RATE, _FAULT_STATUS = _parse_fault(_FAULT_SPEC)


def _rng(key: str) -> random.Random:
    digest = hashlib.sha256(f"{_SEED}:{key}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def active() -> bool:
    """Whether anything is being injected. Never says WHAT -- callers use this
    only to decide whether to take a fast path, never to build a message."""
    return bool(_DELAYS) or _FAULT_RATE > 0


async def delay(stage: str, key: str) -> float:
    """Sleep this stage's injected degradation. Returns the milliseconds slept.

    Must be awaited INSIDE the caller's timing context, so the injected time
    lands in the stage it belongs to. Injected time that lands outside the
    ledger is time the participant cannot attribute, which defeats the point.
    """
    params = _DELAYS.get(stage)
    if params is None:
        return 0.0
    mu, sigma = params
    ms = math.exp(mu if sigma == 0 else _rng(f"{stage}:{key}").gauss(mu, sigma))
    # A degraded dependency is slow, not infinitely slow. The cap keeps one
    # unlucky draw from blowing a 20-minute session's time budget.
    ms = min(ms, 30_000.0)
    await asyncio.sleep(ms / 1000)
    return ms


def provider_fault(key: str, attempt: int) -> int | None:
    """An HTTP status to simulate for this attempt, or None to proceed.

    Independent per attempt: with a 17% rate and two retries a request fails
    outright about once in 200, so the run shows a fat p99 and a small non-zero
    error count rather than a uniformly broken service.
    """
    if _FAULT_RATE <= 0:
        return None
    if _rng(f"provider:{key}:{attempt}").random() < _FAULT_RATE:
        return _FAULT_STATUS
    return None
