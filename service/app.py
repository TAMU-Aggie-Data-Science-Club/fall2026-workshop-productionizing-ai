"""Nimbus -- the cafe ordering assistant you deploy, benchmark and scale.

Request path, and where the time goes:

    arrival -> [shed?] -> [queue] -> [cache] -> [retrieve] -> [generate] -> done
               |__________________|            |_________________________|
                     QUEUE WAIT                        COMPUTE

The whole activity turns on being able to see those two numbers separately.
An overloaded queue and a slow model look identical from the outside and have
opposite fixes.
"""
import asyncio
import importlib
import json
import os
import pathlib
import secrets
import sys
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).parent))

import config          # noqa: E402
import incident        # noqa: E402
import levers          # noqa: E402
import retrieval       # noqa: E402
from timing import Timer  # noqa: E402

if config.MODEL_BACKEND == "google":
    import cloud_model as model  # noqa: E402
elif config.MODEL_BACKEND == "ollama":
    import ollama_model as model  # noqa: E402
else:
    import torch  # noqa: E402
    import model  # noqa: E402

    # One core per in-flight request in local mode. Cloud mode is network-bound
    # and does not import PyTorch for LLM inference.
    torch.set_num_threads(1)

_state: dict = {"semaphore": None, "waiting": 0, "served": 0, "shed": 0, "failed": 0}

# What a team has committed to, in the order they committed to it. Held in
# memory on purpose for now: it belongs to one team's one service, and the
# durable copy is a later phase.
_declarations: list[dict] = []

# Round 2 refuses a lever change until a diagnosis is on record. Enforcing this
# in the service rather than by a facilitator walking the room is the point:
# otherwise a team can flip switches until something goes green and write the
# reasoning afterwards, which is the exact habit the activity exists to break.
def _require_hypothesis() -> bool:
    return os.environ.get("NIMBUS_REQUIRE_HYPOTHESIS", "").lower() in {"1", "true", "yes"}

_CONFIG_KEYS = ("MODEL_BACKEND", "RESPONSE_CACHE", "PREFIX_CACHE", "SEMANTIC_CACHE",
                "SEMANTIC_CACHE_THRESHOLD", "MAX_TOKENS",
                "SYSTEM_PROMPT", "RETRIEVE_K", "ROUTE_EASY", "MODEL_TIER",
                "MAX_CONCURRENT", "REPLICAS", "SHED_ABOVE_QUEUE")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate/load all runtime dependencies BEFORE serving traffic, never inside
    # a request handler. In Cloud Run this validates ADC; Python-local mode
    # loads the two local model tiers; Docker-local mode validates Ollama and
    # the pulled model names.
    model.warm()
    _state["semaphore"] = asyncio.Semaphore(config.MAX_CONCURRENT * config.REPLICAS)
    print(f"Nimbus ready | {retrieval.size()} note chunks | tier={config.MODEL_TIER} "
          f"concurrency={config.MAX_CONCURRENT}x{config.REPLICAS} "
          f"max_tokens={config.MAX_TOKENS}")
    yield
    if hasattr(model, "close"):
        await model.close()


app = FastAPI(title="Nimbus", version="1.0", lifespan=lifespan)


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    max_tokens: int | None = Field(default=None, ge=1, le=1024)


@app.get("/", include_in_schema=False)
async def participant_ui() -> FileResponse:
    return FileResponse(pathlib.Path(__file__).resolve().parent / "web" / "index.html")


@app.get("/brief")
async def brief() -> dict:
    """The incident as a user would report it, plus the targets to hit.

    Public on purpose: this is the symptom, and participants are meant to have
    it. The CAUSE is not here and is not anywhere the service can reach -- the
    catalog that holds it lives with the facilitators, and this text arrives as
    a deploy-time string with the answer already stripped out.
    """
    scenario_path = pathlib.Path(__file__).resolve().parents[1] / "scenario.json"
    try:
        constraints = json.loads(scenario_path.read_text())["constraints"]
    except Exception:  # noqa: BLE001
        constraints = {}
    return {
        "title": os.environ.get("NIMBUS_INCIDENT_TITLE", "Nimbus is degraded"),
        "reported": os.environ.get(
            "NIMBUS_INCIDENT_BRIEF",
            "Students say the assistant is not behaving the way it should."),
        "user_impact": os.environ.get("NIMBUS_INCIDENT_IMPACT", ""),
        "targets": {
            "p95_latency_s": constraints.get("slo_p95_latency_s"),
            "usd_per_month": constraints.get("budget_usd_per_month"),
            "quality_pct": constraints.get("quality_bar_eval_pct"),
        },
        # The traffic this service is receiving. NOT a secret -- "finals week
        # traffic is 5x normal" is part of the incident a user would report --
        # and it has to come from here, because each incident was calibrated
        # under a specific load. A client that invents its own concurrency
        # measures a different system: sending 8-way traffic at a service
        # calibrated for 2 manufactures a queue that is not the incident.
        "traffic": {
            "requests": int(os.environ.get("NIMBUS_TRAFFIC_REQUESTS", "16")),
            "rate": float(os.environ.get("NIMBUS_TRAFFIC_RATE", "4.0")),
            "concurrency": int(os.environ.get("NIMBUS_TRAFFIC_CONCURRENCY", "8")),
        },
        "task": ("Attribute the latency before you change anything. The report "
                 "names the largest contributor; it will not tell you what to do "
                 "about it."),
    }


@app.get("/health")
async def health() -> dict:
    return {"ok": True, "service": "nimbus", "status": "ready",
            "backend": config.MODEL_BACKEND, "note_chunks": retrieval.size(),
            "capacity": config.MAX_CONCURRENT * config.REPLICAS,
            "served": _state["served"],
            "shed": _state["shed"], "failed": _state["failed"],
            "waiting": _state["waiting"]}


def _admin_allowed(token: str | None) -> bool:
    expected = os.environ.get("NIMBUS_ADMIN_TOKEN")
    # Preserve the original local workflow. Cloud mode must be configured with
    # a secret, otherwise administrative endpoints are unavailable.
    if not expected:
        return config.MODEL_BACKEND != "google"
    return token is not None and secrets.compare_digest(token, expected)


@app.get("/metrics")
async def metrics(x_nimbus_admin_token: str | None = Header(default=None)) -> dict:
    if not _admin_allowed(x_nimbus_admin_token):
        return JSONResponse({"error": "admin authentication required"}, status_code=401)
    return {
        "served": _state["served"], "shed": _state["shed"],
        "failed": _state["failed"],
        "waiting": _state["waiting"],
        "config": {k: getattr(config, k) for k in _CONFIG_KEYS},
        "runtime": (model.runtime_info() if hasattr(model, "runtime_info") else
                    {"provider": "local"}),
        "deployment": {"service": os.environ.get("K_SERVICE", "local"),
                       "revision": os.environ.get("K_REVISION", "local")},
        "cache": levers.cache_stats(),
    }


@app.post("/verify-models")
async def verify_models(x_nimbus_admin_token: str | None = Header(default=None)):
    """Verify fixed model tiers without changing participant controls or caches.

    Use the normal admission pool and adapter; this consumes provider requests.
    It deliberately does not fabricate a hypothesis to get past the lever gate.
    """
    if not _admin_allowed(x_nimbus_admin_token):
        return JSONResponse({"error": "team token required"}, status_code=401)
    if _state["semaphore"] is None:
        return JSONResponse({"error": "service is still starting"}, status_code=503)
    results = {}
    async with _state["semaphore"]:
        prompt = "Explain briefly what a flat white is. It is a double ristretto with steamed milk, served in an 8 oz cup."
        for tier in ("large", "small"):
            stats = {}
            try:
                pieces = [part async for part in model.generate(
                    tier, prompt, max(256, config.MAX_TOKENS), stats, None)]
                text = "".join(pieces).strip()
                results[tier] = {"ok": bool(text), "text": text,
                                 "model": stats.get("model", ""),
                                 "usage_source": stats.get("usage_source", "unknown")}
            except Exception:
                results[tier] = {"ok": False, "error": "model verification failed"}
    return {"ok": all(r["ok"] for r in results.values()), "tiers": results}


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj)}\n\n"


def _trace(request_id: str, stage: str, state: str, label: str,
           detail: str | None = None, duration_ms: float | None = None,
           **metadata) -> str:
    """Make a safe operational event for the participant activity view.

    This describes observable system work without exposing the assembled
    prompt or private model reasoning.
    """
    event = {"request_id": request_id, "stage": stage, "state": state,
             "label": label}
    if detail is not None:
        event["detail"] = detail
    if duration_ms is not None:
        event["duration_ms"] = round(duration_ms, 1)
    if metadata:
        event["meta"] = metadata
    return _sse({"trace": event})


class LeverChange(BaseModel):
    # Free-form on purpose: config.coerce_lever owns the allow-list and the
    # bounds, so there is exactly one place that decides what is legal.
    model_config = {"extra": "allow"}


class Hypothesis(BaseModel):
    dominant_slice: str = Field(min_length=1, max_length=64)
    model_implicated: bool
    proof_metric: str = Field(min_length=1, max_length=200)
    predicted_lever: str | None = Field(default=None, max_length=64)
    predicted_direction: str | None = Field(default=None, max_length=200)


@app.post("/hypothesis")
async def record_hypothesis(body: Hypothesis,
                            x_nimbus_admin_token: str | None = Header(default=None)) -> dict:
    """Record what this team thinks is wrong, before they change anything.

    Deliberately NOT graded here. Confirming a diagnosis at the moment it is
    offered ends the investigation before it has been tested; the team finds
    out by changing one thing and watching whether the number moves the way
    they said it would.
    """
    if not _admin_allowed(x_nimbus_admin_token):
        return JSONResponse({"error": "team token required"}, status_code=401)
    entry = {"kind": "hypothesis", "at": time.time(), **body.model_dump()}
    _declarations.append(entry)
    return {"recorded": True, "hypotheses": sum(
        1 for d in _declarations if d["kind"] == "hypothesis")}


@app.get("/declarations")
async def declarations(x_nimbus_admin_token: str | None = Header(default=None)):
    if not _admin_allowed(x_nimbus_admin_token):
        return JSONResponse({"error": "team token required"}, status_code=401)
    return {"declarations": _declarations,
            "hypothesis_required": _require_hypothesis()}


@app.post("/levers")
async def set_levers(body: LeverChange,
                     x_nimbus_admin_token: str | None = Header(default=None)):
    """Change one setting on the RUNNING service.

    /reload re-reads the container's config.py, which a participant cannot
    edit, so on Cloud Run it can never apply their change. Redeploying can --
    at three and a half minutes a time, which is the activity over. This takes
    the value from the request instead, and applies it in about a second.

    Changes live in this process only. That is correct for the workshop, where
    each team owns one service pinned to a single instance; it would need a
    shared store the moment a service is allowed to scale out.
    """
    if not _admin_allowed(x_nimbus_admin_token):
        return JSONResponse({"error": "team token required"}, status_code=401)

    requested = body.model_dump()
    if not requested:
        return JSONResponse(
            {"error": "no settings supplied",
             "available": sorted(config.LEVERS)}, status_code=400)

    if _require_hypothesis() and not any(
            d["kind"] == "hypothesis" for d in _declarations):
        return JSONResponse(
            {"error": "diagnose first",
             "detail": "Record what you think is wrong, and which number says "
                       "so, before changing a setting.",
             "how": "POST /hypothesis"},
            status_code=409)

    # Validate EVERY value before applying ANY of them, so a rejected change
    # cannot leave the service half-changed and the run unattributable.
    coerced, errors = {}, {}
    for name, value in requested.items():
        try:
            coerced[name] = config.coerce_lever(name, value)
        except ValueError as exc:
            errors[name] = str(exc)
    if errors:
        return JSONResponse({"error": "invalid settings", "detail": errors,
                             "applied": False}, status_code=400)

    before = {name: getattr(config, name) for name in coerced}
    for name, value in coerced.items():
        setattr(config, name, value)

    # A lever change is measured against a cold cache, not against answers
    # accumulated under the previous settings.
    levers.reset_caches()
    _state["semaphore"] = asyncio.Semaphore(config.MAX_CONCURRENT * config.REPLICAS)
    _state["served"] = _state["shed"] = _state["failed"] = 0
    _declarations.append({"kind": "change", "at": time.time(),
                          "before": before, "after": coerced})

    return {"applied": True, "changed": coerced, "previous": before,
            "config": {k: getattr(config, k) for k in _CONFIG_KEYS}}


@app.post("/reload")
async def reload_config(x_nimbus_admin_token: str | None = Header(default=None)) -> dict:
    """Re-read config.py without restarting.

    In local mode, loading both model tiers takes ~13s. Cloud mode validates
    credentials at startup and keeps the managed model warm outside this
    process, so reload remains a configuration/cache operation.
    importlib.reload updates the existing module object in place, so levers.py --
    which holds a reference to it and reads config.X at call time -- sees the new
    values without being reloaded itself.

    Caches are cleared deliberately: a lever change should be measured against a
    cold cache, not against answers accumulated under the previous settings.
    """
    if not _admin_allowed(x_nimbus_admin_token):
        return JSONResponse({"error": "admin authentication required"}, status_code=401)
    try:
        importlib.reload(config)
    except Exception as exc:  # noqa: BLE001
        # Participants edit this file by hand under time pressure. A stray comma
        # should produce a sentence they can act on, not a stack trace -- and the
        # server must keep serving with the last good config.
        return JSONResponse(
            {"reloaded": False,
             "error": f"{type(exc).__name__}: {exc}",
             "hint": "config.py has a syntax error. Fix it and run `make reload` "
                     "again. The server is still running the previous config."},
            status_code=400)

    levers.reset_caches()
    _state["semaphore"] = asyncio.Semaphore(config.MAX_CONCURRENT * config.REPLICAS)
    _state["served"] = _state["shed"] = _state["failed"] = 0
    return {"reloaded": True,
            "config": {k: getattr(config, k) for k in _CONFIG_KEYS}}


@app.post("/ask")
async def ask(body: Ask):
    timer = Timer()
    request_id = secrets.token_hex(4)

    # ── Load shedding ────────────────────────────────────────────────────
    # Fail fast and honestly rather than time out slowly. Every shed request
    # is still a customer who did not get an answer.
    if config.SHED_ABOVE_QUEUE is not None and _state["waiting"] > config.SHED_ABOVE_QUEUE:
        _state["shed"] += 1
        return JSONResponse(
            {"error": "overloaded", "retry_after_s": 2},
            status_code=429,
            headers={"Retry-After": "2", "X-Queue-Depth": str(_state["waiting"])},
        )

    # ── Admission control ────────────────────────────────────────────────
    semaphore = _state["semaphore"]
    if semaphore is None:
        return JSONResponse({"error": "service is still starting"}, status_code=503)
    max_tokens = body.max_tokens if body.max_tokens is not None else config.MAX_TOKENS
    question = body.question

    async def stream():
        stats = {"tokens_in": 0, "tokens_out": 0, "usage_source": "local",
                 "upstream_retries": 0, "provider_status": None}
        cache_state, tier = "miss", "-"
        acquired = False
        current_stage = "request"
        try:
            yield _trace(request_id, "request", "complete", "Request received",
                         "POST /ask · validating and admitting work")

            # Keep admission inside the stream so the browser can see a real
            # request waiting for capacity instead of jumping straight to the
            # answer after an invisible server-side pause.
            current_stage = "queue"
            yield _trace(request_id, "queue", "running", "Capacity check",
                         "Waiting for an available inference slot")
            _state["waiting"] += 1
            try:
                await semaphore.acquire()
                acquired = True
            finally:
                _state["waiting"] -= 1
            timer.admitted()
            yield _trace(request_id, "queue", "complete", "Capacity check",
                         "Request admitted to the service",
                         timer.queue_wait_ms)

            # ── Caches ──────────────────────────────────────────────────
            # The semantic cache is checked first because a hit skips
            # retrieval AND generation. The exact cache is keyed on the
            # assembled prompt, so it can only be checked after retrieval.
            current_stage = "cache"
            yield _trace(request_id, "cache", "running", "Check response cache",
                         "Looking for a reusable answer")
            with timer.stage("cache"):
                qvec = levers.question_vector(question)
                answer = levers.semantic_get(question, qvec)
            cache_lookup = "semantic-hit" if answer is not None else "miss"
            if answer is not None:
                cache_state = "semantic-hit"
                prompt = None
                yield _trace(request_id, "cache", "complete", "Check response cache",
                             "Semantic cache hit · retrieval and generation skipped",
                             timer.stages["cache"] * 1000,
                             result=cache_lookup)
                yield _trace(request_id, "retrieve", "skipped", "Retrieve menu notes",
                             "Skipped because the response cache returned an answer")
                yield _trace(request_id, "assemble", "skipped", "Build grounded prompt",
                             "Skipped because the response cache returned an answer")
            else:
                yield _trace(request_id, "cache", "running", "Check prompt cache",
                             "No reusable response yet · checking after retrieval")
                current_stage = "retrieve"
                yield _trace(request_id, "retrieve", "running", "Retrieve menu notes",
                             f"Searching {retrieval.size()} indexed note chunks")
                with timer.stage("retrieve"):
                    # Injected inside the stage timer on purpose: degradation
                    # that lands outside the ledger is time a participant
                    # cannot attribute to anything, which defeats the exercise.
                    # Other stages take a hook the same way if an incident ever
                    # needs one; today only retrieval has a real dependency.
                    await incident.delay("retrieve", question)
                    sources = retrieval.search_details(question, config.RETRIEVE_K)
                    chunks = [source["text"] for source in sources]
                yield _trace(request_id, "retrieve", "complete", "Retrieve menu notes",
                             f"Selected {len(sources)} relevant chunk(s)",
                             timer.stages["retrieve"] * 1000,
                             sources=[{key: source[key] for key in ("source", "title", "excerpt", "score")}
                                     for source in sources])

                current_stage = "assemble"
                yield _trace(request_id, "assemble", "running", "Build grounded prompt",
                             "Combining menu notes with the customer question")
                with timer.stage("assemble"):
                    prompt = levers.build_prompt(question, chunks)
                yield _trace(request_id, "assemble", "complete", "Build grounded prompt",
                             f"Prepared context from {len(chunks)} note chunk(s)",
                             timer.stages["assemble"] * 1000)

                current_stage = "cache"
                with timer.stage("cache"):
                    answer = levers.exact_get(prompt)
                if answer is not None:
                    cache_state = "exact-hit"
                yield _trace(request_id, "cache", "complete", "Check prompt cache",
                             "Exact response cache hit" if answer is not None
                             else "Cache miss · the model will generate a response",
                             timer.stages["cache"] * 1000,
                             result="exact-hit" if answer is not None else "miss")

            if answer is not None:
                yield _trace(request_id, "route", "skipped", "Select model tier",
                             "Skipped because no generation was needed")
                yield _trace(request_id, "generate", "skipped", "Generate response",
                             "Skipped because the response cache returned an answer")
                yield _sse({"delta": answer})
            else:
                current_stage = "route"
                yield _trace(request_id, "route", "running", "Select model tier",
                             "Applying the configured routing policy")
                tier = levers.pick_tier(question)
                yield _trace(request_id, "route", "complete", "Select model tier",
                             f"Routed to the {tier} model tier",
                             tier=tier)
                pieces = []
                current_stage = "generate"
                yield _trace(request_id, "generate", "running", "Generate response",
                             f"Streaming tokens from the {tier} model")
                with timer.stage("generate"):
                    prefix = levers.static_prefix() if config.PREFIX_CACHE else None
                    async for chunk in model.generate(tier, prompt, max_tokens,
                                                      stats, prefix):
                        pieces.append(chunk)
                        yield _sse({"delta": chunk})
                answer = "".join(pieces)
                if not answer.strip():
                    raise RuntimeError("generation returned no answer text")
                levers.exact_put(prompt, answer)
                levers.semantic_put(question, answer, qvec)
                yield _trace(request_id, "generate", "complete", "Generate response",
                             f"Streamed {stats['tokens_out']} output token(s)",
                             timer.stages["generate"] * 1000,
                             tokens_out=stats["tokens_out"], tier=tier)

            current_stage = "complete"
            yield _trace(request_id, "complete", "complete", "Response complete",
                         "Answer delivered to the browser",
                         timer.compute_ms)

            _state["served"] += 1
            yield _sse({"stats": {
                "request_id": request_id,
                "queue_wait_ms": round(timer.queue_wait_ms, 1),
                "compute_ms": round(timer.compute_ms, 1),
                "stages_ms": {k: round(v * 1000, 1) for k, v in timer.stages.items()},
                "tokens_in": stats["tokens_in"],
                "tokens_out": stats["tokens_out"],
                "tokens_cached": stats.get("tokens_cached", 0),
                "usage_source": stats.get("usage_source", "unknown"),
                "provider": stats.get("provider", "local"),
                "model": stats.get("model", ""),
                # Provider retries are part of the latency story, not an
                # implementation detail: a request that succeeded on its third
                # attempt is slow for a reason no stage timer can show.
                "upstream_retries": stats.get("upstream_retries", 0),
                "provider_status": stats.get("provider_status"),
                "cache": cache_state,
                "tier": tier,
            }})
            yield "data: [DONE]\n\n"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            _state["failed"] += 1
            print(f"Nimbus request failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            yield _trace(request_id, current_stage, "failed", "Request failed",
                         "Nimbus could not complete this request. Please try again.")
            # The HTTP status is already 200 once a stream starts. Emit a
            # machine-readable event so browsers and benchmarks do not mistake
            # a truncated stream for a successful answer.
            yield _sse({"error": {
                "code": "request_failed",
                "message": "Nimbus could not complete this request. Please try again.",
            }})
            yield "data: [DONE]\n\n"
        finally:
            # Capture the semaphore this request acquired. /reload may replace
            # the global semaphore while a streamed request is still running.
            if acquired:
                semaphore.release()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache",
                 "X-Accel-Buffering": "no"},
    )
