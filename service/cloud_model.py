"""Google managed-model adapter used by the Cloud Run deployment.

The FastAPI application deliberately keeps the same ``warm``/``generate``
contract as the local model implementation.  That lets the workshop keep a
local fallback while Cloud Run sends inference to a managed Google endpoint.

Authentication uses Application Default Credentials, which means a Cloud Run
runtime service account is used in production.  No service-account key or API
key belongs in the container or repository.
"""
import asyncio
import json
import os
from typing import Any, AsyncIterator

import httpx

import incident


class ProviderError(RuntimeError):
    """An upstream model request failed before a response could complete.

    Carries the upstream HTTP status when there was one. The report needs it:
    "the provider returned 429 four times" and "the provider was slow" are
    different incidents with different fixes, and they are indistinguishable
    from a latency number alone.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class RetryableProviderError(ProviderError):
    """The upstream response may succeed if retried with backoff."""


_credentials = None
_project = None
_http: httpx.AsyncClient | None = None
_refresh_lock: asyncio.Lock | None = None


def _api_style() -> str:
    return os.environ.get("NIMBUS_GOOGLE_API_STYLE", "mistral").lower()


# Two real tiers, so "route the easy questions to the cheaper model" is a lever
# with a measurable effect rather than a simulation.
_DEFAULT_MODELS = {
    "gemini": {"small": "gemini-2.5-flash-lite", "large": "gemini-2.5-flash"},
    "mistral": {"small": "mistral-small-2503", "large": "mistral-small-2503"},
    "openai": {"small": "mistral-small-2503", "large": "mistral-small-2503"},
}


def _model_id(tier: str) -> str:
    common = os.environ.get("NIMBUS_GOOGLE_MODEL_ID")
    if common:
        return common
    fallback = _DEFAULT_MODELS.get(_api_style(), _DEFAULT_MODELS["mistral"])
    key = "NIMBUS_GOOGLE_MODEL_SMALL" if tier == "small" else "NIMBUS_GOOGLE_MODEL_LARGE"
    return os.environ.get(key, fallback["small" if tier == "small" else "large"])


# What each model will accept as a thinking budget. Measured against the live
# API, not read off a docs page:
#
#   gemini-2.5-pro         rejects 0; smallest accepted budget is 128
#   gemini-2.5-flash-lite  accepts 0, then nothing until 512
#   gemini-2.5-flash       accepts 0 and 128
#
# One global budget cannot satisfy all three, and the failure is a hard 400 at
# request time. The decode incident sets 128 for Pro, which is out of range for
# flash-lite -- so a team taking either the tempting shortcut (MODEL_TIER=small)
# or the correct path (ROUTE_EASY=true) would have had every routed request fail
# instead of showing them a trade-off.
#
# Longest prefix wins, so flash-lite is matched before flash.
_THINKING_LIMITS = {
    "gemini-2.5-pro":        {"min": 128, "allows_zero": False},
    "gemini-2.5-flash-lite": {"min": 512, "allows_zero": True},
    "gemini-2.5-flash":      {"min": 0,   "allows_zero": True},
}


def _limits_for(model_id: str | None) -> dict | None:
    if not model_id:
        return None
    for prefix in sorted(_THINKING_LIMITS, key=len, reverse=True):
        if model_id.startswith(prefix):
            return _THINKING_LIMITS[prefix]
    return None


def _resolve_budget(requested: int, model_id: str | None) -> int | None:
    """Fit a requested budget to what this model actually accepts.

    Below-minimum values clamp DOWN to zero where zero is legal, rather than up
    to the model's floor. That keeps the cheap tier cheap: raising flash-lite to
    512 thinking tokens would make the small model slow and expensive too, and
    the trap that teaches "route instead of downgrading" depends on it staying
    fast.
    """
    limits = _limits_for(model_id)
    if limits is None:
        return requested
    if requested == 0:
        return 0 if limits["allows_zero"] else None
    if requested >= limits["min"]:
        return requested
    return 0 if limits["allows_zero"] else limits["min"]


def _thinking_budget(model_id: str | None = None) -> int | None:
    """Gemini 2.5 models think before answering, and thinking spends the SAME
    output-token budget the answer needs.

    At the workshop's default cap this is not a tuning detail -- it is total
    failure: max_output_tokens=32 returned finishReason=MAX_TOKENS with ZERO
    text parts and thoughtsTokenCount=29. Every answer empty, while latency and
    cost both read as healthy. Setting the budget to 0 restores normal output.

    Returns None to omit the field entirely. Gemini 2.5 Pro cannot disable
    thinking and rejects a zero budget, so a zero value is treated as omitted
    when the selected model is Pro. Other Gemini 2.5 tiers retain the existing
    zero-budget behavior.
    """
    raw = os.environ.get("NIMBUS_GEMINI_THINKING_BUDGET", "0")
    if raw.strip().lower() in {"", "none", "default"}:
        return None
    try:
        requested = max(0, int(raw))
    except ValueError as exc:
        raise ProviderError(
            "NIMBUS_GEMINI_THINKING_BUDGET must be an integer or 'none'") from exc
    return _resolve_budget(requested, model_id)


def _wire_model_id(model_id: str) -> str:
    """Return the identifier expected by the selected Google endpoint."""
    if _api_style() == "openai":
        return os.environ.get("NIMBUS_GOOGLE_OPENAI_MODEL_ID", model_id)
    return model_id


def _load_credentials() -> None:
    global _credentials, _project
    if _credentials is not None:
        return

    try:
        import google.auth
        from google.auth.transport.requests import Request

        _credentials, discovered_project = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"])
        _project = os.environ.get("GOOGLE_CLOUD_PROJECT") or discovered_project
        if not _project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is not set and ADC returned no project")
        _credentials.refresh(Request())
    except Exception as exc:  # noqa: BLE001
        raise ProviderError(
            "Google credentials are unavailable. Configure Cloud Run ADC or run "
            "`gcloud auth application-default login` locally.") from exc


async def _access_token() -> str:
    global _refresh_lock
    if _credentials is None:
        await asyncio.to_thread(_load_credentials)

    if _refresh_lock is None:
        _refresh_lock = asyncio.Lock()
    if not _credentials.valid or _credentials.expired:
        async with _refresh_lock:
            if not _credentials.valid or _credentials.expired:
                from google.auth.transport.requests import Request
                await asyncio.to_thread(_credentials.refresh, Request())
    if not _credentials.token:
        raise ProviderError("Google credentials did not return an access token")
    return _credentials.token


def _endpoint(model_id: str) -> str:
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    project = _project or os.environ.get("GOOGLE_CLOUD_PROJECT")
    # The "global" location is served by the unprefixed host; every regional
    # location is served by its own.
    host = ("aiplatform.googleapis.com" if location == "global"
            else f"{location}-aiplatform.googleapis.com")
    if not project:
        raise ProviderError("GOOGLE_CLOUD_PROJECT is not set")
    style = _api_style()
    if style == "gemini":
        # alt=sse is required, or streamGenerateContent returns a single JSON
        # array instead of a token stream -- and TTFT stops being measurable.
        return (f"https://{host}/v1/projects/{project}/locations/{location}/"
                f"publishers/google/models/{model_id}:streamGenerateContent?alt=sse")
    if style == "mistral":
        return (f"https://{host}/v1/projects/{project}/locations/{location}/"
                f"publishers/mistralai/models/{model_id}:streamRawPredict")
    return (f"https://{host}/v1/projects/{project}/locations/{location}/"
            "endpoints/openapi/chat/completions")


def _request_body(model_id: str, prompt: str, max_tokens: int) -> dict:
    """Wire format for the selected dialect. Temperature 0 everywhere so a
    re-run measures the configuration change and not sampling noise."""
    if _api_style() == "gemini":
        generation: dict = {"maxOutputTokens": max_tokens, "temperature": 0}
        budget = _thinking_budget(model_id)
        if budget is not None:
            generation["thinkingConfig"] = {"thinkingBudget": budget}
        return {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                "generationConfig": generation}
    return {
        "model": _wire_model_id(model_id),
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
        "stream": True,
    }


def runtime_info() -> dict:
    """Return non-secret provider details for /metrics and benchmark records."""
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    info = {
        "provider": "google",
        "api_style": _api_style(),
        "location": location,
        "model_small": _wire_model_id(_model_id("small")),
        "model_large": _wire_model_id(_model_id("large")),
    }
    if _api_style() == "gemini":
        info["thinking_budget"] = _thinking_budget(_model_id("large"))
    return info


def _http_client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        timeout = float(os.environ.get("NIMBUS_PROVIDER_TIMEOUT_SECONDS", "300"))
        _http = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0))
    return _http


def _usage(stats: dict, payload: dict) -> None:
    if _api_style() == "gemini":
        _gemini_usage(stats, payload)
        return
    usage = payload.get("usage") or {}
    if not usage:
        return

    stats["tokens_in"] = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0)
    stats["tokens_out"] = int(
        usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0)
    details = usage.get("prompt_tokens_details") or usage.get("input_tokens_details") or {}
    stats["tokens_cached"] = int(
        usage.get("cached_tokens", details.get("cached_tokens", 0)) or 0)
    stats["usage_source"] = "provider"


def _gemini_usage(stats: dict, payload: dict) -> None:
    """Read Gemini's usageMetadata.

    Every streamed chunk carries a usageMetadata object, but only the final one
    carries the counts -- the earlier ones hold just {"trafficType": ...}. That
    dict is truthy, so treating "usage is present" as "usage is known" would
    overwrite real token counts with zeros on the next chunk and report the run
    as free. Key off an actual count instead.
    """
    usage = payload.get("usageMetadata") or {}
    if "promptTokenCount" not in usage:
        return
    thoughts = int(usage.get("thoughtsTokenCount", 0) or 0)
    stats["tokens_in"] = int(usage.get("promptTokenCount", 0) or 0)
    # Thinking tokens are billed at the output rate, so they belong in
    # tokens_out. Kept separately as well, because "the answer was short but the
    # bill was not" is otherwise inexplicable from the report.
    stats["tokens_out"] = int(usage.get("candidatesTokenCount", 0) or 0) + thoughts
    stats["tokens_thinking"] = thoughts
    stats["tokens_cached"] = int(usage.get("cachedContentTokenCount", 0) or 0)
    stats["usage_source"] = "provider"


def _content_parts(payload: dict[str, Any]) -> list[str]:
    """Extract text from both streaming chunks and complete chat responses."""
    if _api_style() == "gemini":
        return [part["text"]
                for candidate in payload.get("candidates", [])
                for part in (candidate.get("content") or {}).get("parts", [])
                if isinstance(part.get("text"), str)]
    parts: list[str] = []
    for choice in payload.get("choices", []):
        delta = choice.get("delta") or {}
        message = choice.get("message") or {}
        content = delta.get("content")
        if content is None:
            content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
    return parts


def _data_line(line: str) -> str | None:
    """Return an SSE data payload, accepting both ``data:`` spellings."""
    if not line.startswith("data:"):
        return None
    raw = line[5:].lstrip()
    return raw or None


async def _stream_once(model_id: str, prompt: str, max_tokens: int,
                       stats: dict) -> AsyncIterator[str]:
    token = await _access_token()
    payload = _request_body(model_id, prompt, max_tokens)
    emitted = False
    try:
        async with _http_client().stream(
                "POST", _endpoint(model_id),
                headers={"Authorization": f"Bearer {token}",
                         "Accept": "text/event-stream, application/json",
                         "Content-Type": "application/json"},
                json=payload) as response:
            if response.status_code in {408, 425, 429} or response.status_code >= 500:
                detail = (await response.aread()).decode(errors="replace")[:500]
                raise RetryableProviderError(
                    f"Google model returned HTTP {response.status_code}: {detail}",
                    status_code=response.status_code)
            if response.status_code >= 400:
                detail = (await response.aread()).decode(errors="replace")[:500]
                raise ProviderError(
                    f"Google model returned HTTP {response.status_code}: {detail}",
                    status_code=response.status_code)

            content_type = response.headers.get("content-type", "").lower()
            if "event-stream" in content_type or "ndjson" in content_type:
                async for line in response.aiter_lines():
                    raw = _data_line(line)
                    if raw is None:
                        continue
                    if raw == "[DONE]":
                        break
                    try:
                        event = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    _usage(stats, event)
                    for text in _content_parts(event):
                        emitted = True
                        yield text
            else:
                body = await response.aread()
                try:
                    events = [json.loads(body)]
                except json.JSONDecodeError as exc:
                    # Some gateways label newline-delimited provider chunks as
                    # application/json. Accept those as well, but never turn a
                    # malformed response into an empty successful answer.
                    events = []
                    for line in body.decode(errors="replace").splitlines():
                        raw = _data_line(line) or line.strip()
                        if not raw or raw == "[DONE]":
                            continue
                        try:
                            events.append(json.loads(raw))
                        except json.JSONDecodeError:
                            continue
                    if not events:
                        raise ProviderError(
                            "Google model returned an unreadable response") from exc
                for event in events:
                    _usage(stats, event)
                    for text in _content_parts(event):
                        emitted = True
                        yield text
    except httpx.RequestError as exc:
        raise RetryableProviderError("Google model network request failed") from exc

    if not emitted:
        raise ProviderError("Google model returned no text")


def warm() -> None:
    """Validate Google ADC during startup, before Cloud Run accepts traffic."""
    if _api_style() not in {"gemini", "mistral", "openai"}:
        raise ProviderError(
            "NIMBUS_GOOGLE_API_STYLE must be 'gemini', 'mistral' or 'openai'")
    if _api_style() == "gemini":
        _thinking_budget()          # validate the value at startup, not mid-run
    if _api_style() == "openai" and not os.environ.get("NIMBUS_GOOGLE_MODEL_ID"):
        raise ProviderError(
            "NIMBUS_GOOGLE_MODEL_ID is required when using the openai endpoint style")
    try:
        timeout = float(os.environ.get("NIMBUS_PROVIDER_TIMEOUT_SECONDS", "300"))
        retries = int(os.environ.get("NIMBUS_PROVIDER_RETRIES", "2"))
        backoff = float(os.environ.get("NIMBUS_PROVIDER_BACKOFF_SECONDS", "0.5"))
    except ValueError as exc:
        raise ProviderError("Provider timeout, retries, and backoff must be numeric") from exc
    if timeout <= 0 or not 0 <= retries <= 5 or backoff < 0:
        raise ProviderError("Invalid provider timeout, retry count, or backoff")
    _load_credentials()


async def close() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


async def generate(tier: str, prompt: str, max_tokens: int, stats: dict,
                   prefix_text: str | None = None):
    """Stream text from the configured Google managed model.

    ``prefix_text`` is accepted for compatibility with the local backend.  A
    managed provider owns its KV/prompt cache, so the application does not pass
    a local cache object to it.
    """
    model_id = _model_id(tier)
    stats.update({"provider": "google", "model": _wire_model_id(model_id),
                  "usage_source": "unreported", "tokens_in": 0,
                  "tokens_out": 0, "tokens_cached": 0})
    # Counted, not swallowed. A retry nobody records is latency with no
    # explanation in the report, and provider degradation is one of the
    # incidents the activity asks participants to tell apart from a slow model.
    # Set outside the loop so the per-attempt reset below cannot clear it.
    stats["upstream_retries"] = 0
    stats["provider_status"] = None
    retries = max(0, int(os.environ.get("NIMBUS_PROVIDER_RETRIES", "2")))
    backoff = float(os.environ.get("NIMBUS_PROVIDER_BACKOFF_SECONDS", "0.5"))

    for attempt in range(retries + 1):
        stats.update({"usage_source": "unreported", "tokens_in": 0,
                      "tokens_out": 0, "tokens_cached": 0})
        yielded = False
        try:
            # Simulated upstream degradation is raised here rather than faked
            # further down, so it drives the SAME retry-and-backoff path a real
            # 429 does and is counted by the same counter. A fault the retry
            # logic never sees would teach participants to trust a code path
            # that was not actually exercised.
            simulated = incident.provider_fault(prompt, attempt)
            if simulated is not None:
                raise RetryableProviderError(
                    f"Google model returned HTTP {simulated}",
                    status_code=simulated)
            async for text in _stream_once(model_id, prompt, max_tokens, stats):
                yielded = True
                yield text
            return
        except RetryableProviderError as exc:
            stats["provider_status"] = exc.status_code
            if yielded or attempt >= retries:
                stats["upstream_retries"] = attempt
                raise
            stats["upstream_retries"] = attempt + 1
            await asyncio.sleep(backoff * (2 ** attempt))
