"""Turn raw per-request timings into the thing the room actually reads.

Two design decisions carry this file.

The VERDICT. A benchmark that only prints numbers is a measurement tool; one
that says PASS or FAIL against a stated SLO and a stated budget is a game with
a win condition, and people play it.

The LEDGER. Latency is additive, so the report shows the addends and they sum.
Reporting one undifferentiated "compute" number makes an overloaded queue, a
slow retrieval dependency and a slow model look identical from the outside --
and those have opposite fixes. This file names the dominant contributor and
stops there: it must never name the lever that fixes it, because that is the
participant's job and the whole point of the exercise.
"""
import json
import os
import pathlib
from run_context import compatible

# The components of one request's wall clock, in the order they occur.
# Rows sum back to end-to-end latency; a component that never sums is a missing
# instrument, not rounding.
LEDGER = (("client_network", "client + network"),
          ("queue",          "app queue wait"),
          ("cache",          "cache lookup"),
          ("retrieve",       "retrieve"),
          ("assemble",       "assemble"),
          ("generate",       "generate"),
          ("other",          "other (app)"))

LEDGER_LABELS = dict(LEDGER)


def pct(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(int(round(q / 100 * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[idx]


def _rank_row(rows: list[dict], q: float) -> dict | None:
    """The single request sitting at the q-th percentile of end-to-end latency."""
    if not rows:
        return None
    ordered = sorted(rows, key=lambda r: r.get("latency_s", 0.0))
    idx = min(int(round(q / 100 * (len(ordered) - 1))), len(ordered) - 1)
    return ordered[idx]


def _ledger_for(row: dict) -> dict[str, float]:
    """Split ONE request's wall clock into components that sum back to it.

    Decomposing a single request rather than combining per-stage percentiles is
    deliberate: percentiles of the parts do not add up to the percentile of the
    whole, so a column of per-stage p95s cannot be read as a budget. This one
    can. The distributional view is reported alongside it.
    """
    stages = row.get("stages_ms") or {}
    queue = float(row.get("queue_wait_ms", 0.0) or 0.0)
    compute = float(row.get("compute_ms", 0.0) or 0.0)
    measured = sum(float(v or 0.0) for v in stages.values())
    total_ms = float(row.get("latency_s", 0.0) or 0.0) * 1000

    out = {key: float(stages.get(key, 0.0) or 0.0) for key, _ in LEDGER}
    out["queue"] = queue
    # Admitted time no stage timer claimed: request parsing, SSE framing, and
    # the trace events themselves.
    out["other"] = max(0.0, compute - measured)
    # Time outside the server's own accounting: connection setup, transit and
    # client-side parsing. On Cloud Run this also contains the platform's own
    # request queue and any cold start; separating those needs Cloud Monitoring.
    out["client_network"] = max(0.0, total_ms - queue - compute)
    return out


def _bar(value: float, scale: float, width: int = 24) -> str:
    if scale <= 0 or value <= 0:
        return "\u258f"
    filled = int(round(value / scale * width))
    return "\u2588" * filled if filled else "\u258f"


def _residual(total_ms: float, latency_ms: float) -> str:
    """How far the ledger misses the wall clock. Should be ~0; if not, say so."""
    if latency_ms <= 0:
        return "n/a"
    return f"{(total_ms - latency_ms) / latency_ms * 100:+.1f}%"


def _baseline(scenario: dict, key: str, provider=None):
    """A calibrated 'normal' value, or None if this hardware was never measured."""
    baseline = scenario.get("baselines", {})
    if baseline.get("_backend") and baseline["_backend"] != provider:
        return None
    return (baseline.get("default", {}) or {}).get(key)


def _versus(value: float, base, unit: str = "", tol: float = 0.15) -> str:
    """Render a measurement against its calibrated baseline, honestly."""
    if base in (None, 0):
        return "not calibrated"
    delta = (value - base) / base
    if abs(delta) <= tol:
        return f"baseline {base:,.0f}{unit} \u00b7 normal"
    return f"baseline {base:,.0f}{unit} \u00b7 {delta*100:+.0f}%"


def _price_for(row: dict, payload: dict, scenario: dict) -> dict | None:
    """Find a token price for the backend that actually served the request."""
    provider = row.get("provider") or payload.get("server_runtime", {}).get("provider", "local")
    model = row.get("model") or ""
    provider_prices = scenario.get("provider_prices", {})
    if model and f"{provider}:{model}" in provider_prices:
        return provider_prices[f"{provider}:{model}"]
    if provider == "ollama":
        # Ollama is a local open-weight runtime. The benchmark reports direct
        # model spend as zero; it intentionally does not estimate electricity
        # or the user's existing hardware.
        return {"input": 0.0, "output": 0.0, "cached_input": 0.0}
    if provider == "local":
        tier = row.get("tier")
        return scenario.get("prices", {}).get(tier)
    return None


def summarise(payload: dict, scenario: dict) -> dict:
    rows = payload["results"]
    ok = [r for r in rows if r.get("ok")]
    shed = [r for r in rows if r.get("shed")]
    failed = [r for r in rows if not r.get("ok") and not r.get("shed")]
    duration = payload["duration_s"]

    prices = scenario["prices"]
    token_cost = 0.0
    cached_tokens = 0
    unknown_usage_requests = 0
    for r in ok:
        price = _price_for(r, payload, scenario)
        provider = r.get("provider") or payload.get("server_runtime", {}).get("provider", "local")
        usage_source = r.get("usage_source", "local" if provider == "local" else "unknown")
        has_usage = usage_source not in {"unreported", "unknown", None}
        is_cache_hit = r.get("cache", "miss") != "miss"
        if is_cache_hit:
            # A cache hit performs no model call and therefore costs no model
            # tokens, even if the configured model has no price entry here.
            continue
        if price is None or not has_usage:
            unknown_usage_requests += 1
            continue
        # Prefix-cached tokens are still input tokens -- they are simply billed
        # at the discounted rate, exactly as a provider would charge them.
        cached = min(r.get("tokens_cached", 0), r["tokens_in"])
        fresh = r["tokens_in"] - cached
        cached_tokens += cached
        token_cost += (fresh / 1e6) * price["input"]
        token_cost += (cached / 1e6) * price.get("cached_input", price["input"])
        token_cost += (r["tokens_out"] / 1e6) * price["output"]

    n = max(len(ok), 1)
    usage_complete = unknown_usage_requests == 0
    per_request = token_cost / n if usage_complete else None
    monthly_requests = scenario["traffic"]["requests_per_day"] * 30

    provider = payload.get("server_runtime", {}).get("provider")
    if not provider:
        providers = {r.get("provider") for r in ok if r.get("provider")}
        provider = "google" if "google" in providers else next(iter(providers), "local")
    if provider == "google":
        # Cloud Run cost depends on CPU/memory allocation and active time, so a
        # flat "replica" price would be misleading. Let the operator provide a
        # budget estimate when they know the service shape; otherwise report it
        # as separate/unknown rather than silently calling token cost total cost.
        # Prefer the auditable figure in scenario.json; the environment variable
        # stays as a per-run override. Without either, the cost verdict reports
        # UNKNOWN rather than quietly treating unmeasured infrastructure as free.
        estimate = os.environ.get("NIMBUS_CLOUD_RUN_MONTHLY_ESTIMATE_USD")
        if estimate is None:
            scenario_estimate = prices.get("cloudrun_usd_per_month")
            infra = float(scenario_estimate) if scenario_estimate is not None else None
        else:
            infra = float(estimate)
        replicas = None
    elif provider == "ollama":
        replicas = None
        infra = 0.0
    else:
        # Capacity is the only lever with a bill in the local exercise.
        replicas = payload.get("server_config", {}).get("REPLICAS", 1) or 1
        infra = replicas * prices.get("replica_usd_per_month", 0)
    hits = sum(1 for r in ok if r.get("cache", "miss") != "miss")

    # The ledger: one representative slow request, decomposed so it sums.
    p95_row = _rank_row(ok, 95)
    ledger = _ledger_for(p95_row) if p95_row else {k: 0.0 for k, _ in LEDGER}
    ledger_latency_ms = (float(p95_row.get("latency_s", 0.0) or 0.0) * 1000
                         if p95_row else 0.0)

    # The distributional view: each stage's own p95 across every request. This
    # does NOT sum, on purpose -- when the two columns disagree, different
    # requests are slow for different reasons, and that is a finding.
    stage_names = {name for r in ok for name in (r.get("stages_ms") or {})}
    stage_p95 = {name: pct([float((r.get("stages_ms") or {}).get(name, 0.0) or 0.0)
                            for r in ok], 95)
                 for name in stage_names}
    stage_p95["queue"] = pct([r.get("queue_wait_ms", 0.0) or 0.0 for r in ok], 95)

    # Token averages must exclude cache hits. A hit makes no model call and
    # reports zero tokens, so averaging it in reports "input tokens 150" for a
    # service whose prompts are all 242 -- the metric drops because requests
    # stopped happening, not because they got smaller. That would hide a prompt
    # regression behind a healthy cache hit rate, which is the exact shape of
    # failure this panel exists to make visible.
    # `or ok` handles an all-cache run; the max() handles a run with no
    # successful requests at all, which must never raise -- the report has to
    # survive a completely broken deployment in order to say it was broken.
    generated = [r for r in ok if r.get("cache", "miss") == "miss"] or ok
    n_generated = max(len(generated), 1)

    slo = scenario.get("constraints", {}).get("slo_p95_latency_s")
    retry_statuses = sorted({r.get("provider_status") for r in ok
                             if r.get("provider_status")})

    monthly_token_cost = token_cost / n * monthly_requests if usage_complete else None
    monthly_total = (monthly_token_cost + infra
                     if monthly_token_cost is not None and infra is not None else None)

    return {
        "run": payload["run"],
        "label": payload.get("label", ""),
        "provider": provider,
        "ok": len(ok), "shed": len(shed), "failed": len(failed),
        "duration_s": duration,
        "rps": len(ok) / duration if duration else 0.0,
        "tps": sum(r["tokens_out"] for r in ok) / duration if duration else 0.0,
        "p50": pct([r["latency_s"] for r in ok], 50),
        "p90": pct([r["latency_s"] for r in ok], 90),
        "p95": pct([r["latency_s"] for r in ok], 95),
        "p99": pct([r["latency_s"] for r in ok], 99),
        "ttft_p95": pct([r["ttft_s"] for r in ok], 95),
        "queue_p95": pct([r["queue_wait_ms"] for r in ok], 95) / 1000,
        "compute_p95": pct([r["compute_ms"] for r in ok], 95) / 1000,
        "cache_hit_rate": hits / n,
        "ledger": ledger,
        "ledger_latency_ms": ledger_latency_ms,
        "stage_p95": stage_p95,
        "upstream_retries": sum(int(r.get("upstream_retries", 0) or 0) for r in ok),
        "retry_statuses": retry_statuses,
        "tokens_in_mean": sum(r.get("tokens_in", 0) for r in generated) / n_generated,
        "tokens_out_mean": sum(r.get("tokens_out", 0) for r in generated) / n_generated,
        "generated_requests": len(generated),
        "over_slo": (sum(1 for r in ok if r.get("latency_s", 0.0) > slo)
                     if slo else 0),
        "prefix_cached_tokens": cached_tokens,
        "input_tokens": sum(r["tokens_in"] for r in ok),
        "usage_complete": usage_complete,
        "unknown_usage_requests": unknown_usage_requests,
        "usd_token_cost_per_1k": token_cost / n * 1000,
        "usd_per_1k": per_request * 1000 if per_request is not None else None,
        "replicas": replicas,
        "usd_tokens_per_month": monthly_token_cost,
        "usd_infra_per_month": infra,
        "usd_per_month": monthly_total,
    }


def recovery(payload, scenario):
    s = summarise(payload, scenario)
    c = scenario["constraints"]
    total = len(payload["results"])
    availability = s["ok"] / total if total else 0.0
    minimum = c.get("minimum_success_rate", 1.0)
    quality = payload.get("quality")
    quality_ok = bool(quality and quality.get("signature") == payload.get("config_signature")
                      and payload.get("config_signature")
                      and quality.get("score_pct", 0) >= c.get("quality_bar_eval_pct", 80))
    latency_ok = s["ok"] > 0 and s["p95"] <= c["slo_p95_latency_s"]
    cost_ok = s["usd_per_month"] is not None and s["usd_per_month"] <= c["budget_usd_per_month"]
    stable = payload.get("configuration_stable", False)
    return {"recovered": bool(stable and latency_ok and cost_ok and availability >= minimum and quality_ok),
            "latency_ok": latency_ok, "cost_ok": cost_ok,
            "availability": availability, "availability_ok": availability >= minimum,
            "quality_ok": quality_ok, "configuration_stable": stable}


def render(payload: dict, scenario: dict, results_dir: pathlib.Path) -> str:
    s = summarise(payload, scenario)
    c = scenario["constraints"]
    slo, budget = c["slo_p95_latency_s"], c["budget_usd_per_month"]

    # A run with no successful requests is a failed deployment, not a pass.
    # Percentiles over an empty list are 0.0, and 0.0 <= any SLO -- so without
    # this guard a completely broken service reports "2/2 constraints met".
    healthy = s["ok"] > 0
    lat_ok = healthy and s["p95"] <= slo
    cost_ok = healthy and s["usd_per_month"] is not None and s["usd_per_month"] <= budget
    met = int(lat_ok) + int(cost_ok)

    # Repeated runs of an identical config on this workload vary by ~12%. A
    # result inside that band is not a result -- it is noise that happens to
    # have landed on one side of the line. Say so rather than pretending.
    NOISE = 0.15
    lat_marginal = healthy and abs(s["p95"] - slo) / slo < NOISE
    cost_marginal = (healthy and s["usd_per_month"] is not None and
                     abs(s["usd_per_month"] - budget) / budget < NOISE)

    prev = None
    prev_path = results_dir / f"run-{payload['run'] - 1}.json"
    if prev_path.exists():
        previous_payload = json.loads(prev_path.read_text())
        candidate = summarise(previous_payload, scenario)
        # A run with no successful requests has percentiles of 0.0 and a cost of
        # nothing, so quoting it as "the previous result" presents a completely
        # broken deployment as the number to beat. Same trap the verdict guard
        # below exists for -- it just also has to apply to the comparison.
        prev = candidate if candidate["ok"] > 0 and compatible(payload, previous_payload) else None

    def mark(ok: bool, marginal: bool = False) -> str:
        if marginal:
            return "MARGINAL"
        return "PASS" if ok else "FAIL"

    w = 68
    L = []
    label = f"  {s['label']}" if s["label"] else ""
    L.append("")
    L.append(f"NIMBUS BENCHMARK - run {s['run']}{label}")
    L.append("=" * w)
    L.append(f"requests     {s['ok']} ok · {s['shed']} shed · {s['failed']} failed"
             f"{'':>6}duration  {s['duration_s']:.1f} s")
    L.append(f"throughput   {s['rps']:.1f} req/s · {s['tps']:.0f} output tok/s")
    L.append("")
    L.append(f"latency      median   {s['p50']:6.2f} s")
    L.append(f"             p95      {s['p95']:6.2f} s   SLO {slo:.2f} s   "
             f"{mark(lat_ok, lat_marginal)}")
    L.append(f"             slowest  {s['p99']:6.2f} s")
    L.append(f"TTFT         p95      {s['ttft_p95']:6.2f} s")
    if s["ok"] < 50:
        rank = s["ok"] - int(round(0.95 * (s["ok"] - 1)))
        L.append(f"             note: with {s['ok']} requests, \"p95\" is the "
                 f"{rank}{'nd' if rank == 2 else 'st' if rank == 1 else 'th'}-slowest")
        L.append(f"             request, not a true percentile. Repeat runs vary ~12%.")
    if s["over_slo"]:
        L.append(f"             {s['over_slo']} of {s['ok']} request(s) exceeded "
                 f"the {slo:.1f}s target")
    L.append("")

    # ── where the time went: the additive ledger ─────────────────────────
    # Left column decomposes the p95 request and SUMS to it, so it reads as a
    # budget. Right column is each stage's own p95 across all requests, which
    # is what a dashboard shows and deliberately does not sum.
    ledger = s["ledger"]
    peak = max(list(ledger.values()) or [0.0])
    W = 17
    L.append("             ── where the time went ─────────────────────────────")
    L.append(f"  {'':<{W}}{'p95 req':>10}  {'p95 each':>8}")
    for key, label in LEDGER:
        value = ledger.get(key, 0.0)
        each = s["stage_p95"].get(key)
        each_txt = f"{each / 1000:7.2f}s" if each is not None else f"{'-':>8}"
        L.append(f"  {label:<{W}}{value / 1000:8.2f} s  {each_txt}  "
                 f"{_bar(value, peak)}")
    total = sum(ledger.values())
    L.append(f"  {'':<{W}}{'--------':>10}")
    L.append(f"  {'sum of rows':<{W}}{total / 1000:8.2f} s   end-to-end "
             f"{s['ledger_latency_ms'] / 1000:.2f} s · residual "
             f"{_residual(total, s['ledger_latency_ms'])}")
    L.append("")

    # ── how the model behaved ────────────────────────────────────────────
    # Deliberately no per-token RATE here. Under load every rate inflates with
    # contention, so an overloaded queue and a genuinely slow model produce the
    # same reading -- the one confusion this whole panel exists to prevent.
    # Output token COUNT is load-independent and separates them cleanly; it
    # lives in "work per request" below.
    L.append("             ── how the model behaved ───────────────────────────")
    statuses = ", ".join(str(x) for x in s["retry_statuses"]) or "none"
    L.append(f"  {'provider retries':<{W}}{s['upstream_retries']:8d}           "
             f"upstream status: {statuses}")
    L.append(f"  {'provider':<{W}}{s['provider']:>8}")
    L.append("")

    # ── work per request ─────────────────────────────────────────────────
    L.append("             ── work per request ────────────────────────────────")
    L.append(f"  {'input tokens':<{W}}{s['tokens_in_mean']:8,.0f} avg      "
             f"{_versus(s['tokens_in_mean'], _baseline(scenario, 'tokens_in', s['provider']))}")
    L.append(f"  {'output tokens':<{W}}{s['tokens_out_mean']:8,.0f} avg      "
             f"{_versus(s['tokens_out_mean'], _baseline(scenario, 'tokens_out', s['provider']))}")
    L.append(f"  {'cache hit rate':<{W}}{s['cache_hit_rate']*100:7.0f}%")
    if s["input_tokens"]:
        share = s["prefix_cached_tokens"] / s["input_tokens"] * 100
        L.append(f"  {'prefix-cached':<{W}}{share:7.0f}%          "
                 f"{s['prefix_cached_tokens']:,} of {s['input_tokens']:,} input tokens")
    L.append("")
    if s["usage_complete"]:
        L.append(f"cost         ${s['usd_per_1k']:.3f} / 1k requests")
        if s["provider"] == "ollama":
            infra_label = "$0 local model hosting (hardware/electricity excluded)"
        elif s["replicas"] is not None:
            infra_label = (f"${s['usd_infra_per_month']:,.0f} infra "
                           f"({s['replicas']} replica"
                           f"{'s' if s['replicas'] != 1 else ''})")
        elif s["usd_infra_per_month"] is not None:
            infra_label = f"${s['usd_infra_per_month']:,.0f} Cloud Run estimate"
        else:
            infra_label = "Cloud Run infra not supplied"
        token_label = f"${s['usd_tokens_per_month']:,.0f} tokens"
        total_label = (f"${s['usd_per_month']:,.0f} / month"
                       if s["usd_per_month"] is not None else
                       "total / month unknown")
        L.append(f"             {token_label} + {infra_label}")
        L.append(f"             {total_label} @ {scenario['traffic']['requests_per_day']:,}/day"
                 f"   budget ${budget:,}   {mark(cost_ok, cost_marginal) if s['usd_per_month'] is not None else 'UNKNOWN'}")
    else:
        L.append("cost         UNKNOWN — provider usage was not reported for "
                 f"{s['unknown_usage_requests']} request(s)")
        L.append("             set provider usage reporting or do not use this run "
                 "for the budget verdict")
    L.append("")
    L.append("-" * w)
    verdict = f"VERDICT  {met}/2 constraints met"
    if lat_marginal or cost_marginal:
        verdict += "  -- but within measurement noise. Run it again before believing it."
    if prev:
        previous_cost = (f"${prev['usd_per_month']:,.0f}/mo"
                         if prev["usd_per_month"] is not None else "cost unknown")
        verdict += (f"      (run {prev['run']}: p95 {prev['p95']:.2f}s, "
                    f"{previous_cost})")
    L.append(verdict)
    recovery_state = recovery(payload, scenario)
    L.append(f"availability {recovery_state['availability']:.0%} successful · "
             f"{'PASS' if recovery_state['availability_ok'] else 'FAIL'}")
    L.append("quality      " + ("PASS" if recovery_state["quality_ok"] else "NOT VERIFIED / FAIL"))
    L.append("RECOVERY     " + ("PASS" if recovery_state["recovered"] else "NOT PROVEN"))

    if not healthy:
        L.append("hint     every request failed. Is the service running, and on this port?")
        L.append("")
        return "\n".join(L)

    # READ THIS FIRST attributes the latency and stops. It names the dominant
    # contributor and what is sitting at baseline -- ruling things out is half
    # of a diagnosis -- but it must never name the lever that fixes it. The
    # moment this block says "enable caching" or "the model is not your
    # problem", the exercise is over and the room has learned nothing.
    L.extend(_read_this_first(s, scenario))
    L.append("")
    return "\n".join(L)


def _read_this_first(s: dict, scenario: dict) -> list[str]:
    """Attribution, never remediation."""
    ledger = s["ledger"]
    total = sum(ledger.values())
    if total <= 0:
        return []

    ranked = sorted(ledger.items(), key=lambda kv: kv[1], reverse=True)
    out = ["READ THIS FIRST"]
    top_key, top_value = ranked[0]
    out.append(f"  Largest contributor to the p95 request: "
               f"{LEDGER_LABELS[top_key].upper()} ({top_value / total * 100:.0f}%).")

    runners = [f"{LEDGER_LABELS[k]} {v / total * 100:.0f}%"
               for k, v in ranked[1:3] if v / total >= 0.01]
    if runners:
        out.append("  Then: " + ", ".join(runners) + ".")
    quiet = [LEDGER_LABELS[k] for k, v in ranked if v / total < 0.01]
    if quiet:
        out.append(f"  Below 1% of the budget: {', '.join(quiet)}.")

    # Signals sitting at their calibrated normal. Saying what is NOT anomalous
    # is what lets a team rule out a suspect instead of guessing at one.
    steady = []
    for value, key in ((s["tokens_in_mean"], "tokens_in"),
                       (s["tokens_out_mean"], "tokens_out")):
        base = _baseline(scenario, key, s["provider"])
        if base and abs(value - base) / base <= 0.15:
            steady.append(key.replace("_", " "))
    if steady:
        out.append(f"  At baseline: {', '.join(steady)}.")
    if s["upstream_retries"]:
        out.append(f"  The provider was retried {s['upstream_retries']} time(s); "
                   f"that time is inside generate.")
    return out


# ═════════════════════════════════════════════════════════════════════════
#  STEP RENDERING
#
#  The five step commands (benchmark / infra / monitor / optimize / guard)
#  draw the same measurements the report above already computes. Nothing here
#  measures anything new -- it reshapes what `summarise` returned so that a
#  first-year can read it without doing arithmetic in their head.
#
#  The rule from the top of this file still holds: these may ATTRIBUTE and
#  they may show a distance from a target, but they must never name the lever
#  that closes it.
# ═════════════════════════════════════════════════════════════════════════

# Ledger keys in the words a student would use. The technical name is taught
# alongside the friendly one in the report above; this is the reading aid, not
# a replacement vocabulary.
FRIENDLY = {
    "client_network": "network",
    "queue":          "wait for a slot",
    "cache":          "check the cache",
    "retrieve":       "find the notes",
    "assemble":       "build the prompt",
    "generate":       "write the answer",
    "other":          "other app work",
}


def _place(width: int, items: list[tuple[int, str]]) -> str:
    """Lay labels out on one line at given positions; drop any that collide.

    Dropping beats overlapping: two labels printed on top of each other read as
    corruption, and a missing label is recoverable from the row above it.
    """
    line = [" "] * width
    for pos, text in sorted(items):
        start = max(0, min(pos, width - len(text)))
        window = range(max(0, start - 1), min(width, start + len(text) + 1))
        if all(line[i] == " " for i in window):
            for offset, char in enumerate(text):
                if start + offset < width:
                    line[start + offset] = char
    return "".join(line).rstrip()


def gap_bar(name: str, value, target, unit: str = "s", width: int = 44,
            money: bool = False) -> list[str]:
    """One metric drawn as a distance from its target.

    A verdict line says PASS or FAIL. It does not say how far, or which way you
    just moved -- which is the only question a team in the middle of optimising
    actually has. The bar answers it without arithmetic.
    """
    def fmt(x: float) -> str:
        return f"${x:,.0f}" if money else f"{x:.2f} {unit}"

    if value is None or target is None or target <= 0:
        return [f"  {name:<15}not measured"]

    scale = max(value, target) * 1.25
    span = width - 1
    tp = max(0, min(span, int(round(target / scale * span))))
    vp = max(0, min(span, int(round(value / scale * span))))

    track = ["─"] * width
    track[tp] = "┼"
    track[vp] = "▲"          # value last: if they collide, "you are here" wins

    over = value - target
    if over > 0:
        delta = f"▲ {fmt(over)} OVER"
        state = "FAIL"
    else:
        delta = f"▼ {fmt(abs(over))} under"
        state = "PASS"

    return [
        f"  {name:<15}{fmt(value):>10}   target {fmt(target):<10} {delta}  {state}",
        "  ├" + "".join(track) + "┤",
        "   " + _place(width, [(tp, "target"), (vp, fmt(value))]),
    ]


def stage_histogram(ledger: dict, width: int = 20) -> list[str]:
    """Where one representative slow request spent its time, drawn.

    The ledger already sums to the request, so a share is meaningful. Drawing it
    is what turns "retrieve 1.21" into "retrieve is most of it" without asking a
    first-year to divide two numbers under time pressure.
    """
    total = sum(ledger.values())
    if total <= 0:
        return ["    no timing recorded for this run"]
    peak = max(ledger.values()) or 1.0
    out = []
    for key, value in sorted(ledger.items(), key=lambda kv: kv[1], reverse=True):
        share = value / total * 100
        if share < 0.5:
            continue
        bar = "█" * max(1, int(round(value / peak * width)))
        out.append(f"    {FRIENDLY.get(key, key):<18}{value / 1000:6.2f} s  "
                   f"{bar:<{width}} {share:3.0f}%")
    quiet = [FRIENDLY.get(k, k) for k, v in ledger.items() if v / total * 100 < 0.5]
    if quiet:
        out.append(f"    {'':<18}{'':>6}    below 1%: {', '.join(quiet)}")
    return out


def _tier_price(tier: str, payload: dict, scenario: dict):
    """The real per-token price of one tier on the backend that actually ran.

    Mirrors _price_for, but keyed on a tier rather than on a request, because
    the projection asks what a tier WOULD cost -- there are no requests from it
    to read a model name off.
    """
    runtime = payload.get("server_runtime", {}) or {}
    provider = runtime.get("provider", "local")
    if provider == "ollama":
        return {"input": 0.0, "output": 0.0, "cached_input": 0.0}
    if provider == "local":
        return scenario.get("prices", {}).get(tier)
    model = runtime.get(f"model_{tier}")
    if not model:
        return None
    return scenario.get("provider_prices", {}).get(f"{provider}:{model}")


def tier_projection(payload: dict, scenario: dict) -> list[str]:
    """What each model tier would cost on THIS run's measured token counts.

    Arithmetic on a run that already happened, so it sends no traffic and costs
    nothing. Cost is projected; QUALITY IS DELIBERATELY ABSENT. Cost and latency
    are computable from a run, answer quality is not -- and that asymmetry is
    the entire lesson of the step. A team that reads a cheap row here and ships
    it without evaluating has made exactly the mistake the exercise is about.
    """
    s = summarise(payload, scenario)
    if not s["usage_complete"] or s["generated_requests"] == 0:
        return ["    provider usage was not reported for every request, so this",
                "    projection would be wrong. Re-run the benchmark."]

    runtime = payload.get("server_runtime", {}) or {}
    current = payload.get("server_config", {}).get("MODEL_TIER", "large")
    monthly_requests = scenario["traffic"]["requests_per_day"] * 30
    infra = s["usd_infra_per_month"] or 0.0
    tokens_in, tokens_out = s["tokens_in_mean"], s["tokens_out_mean"]

    out = [f"    {'tier':<8}{'model':<26}{'$/month':>10}   {'vs now':>10}"]
    rows, baseline_total = [], None
    for tier in ("large", "small"):
        price = _tier_price(tier, payload, scenario)
        model = runtime.get(f"model_{tier}", tier)
        if price is None:
            rows.append((tier, model, None))
            continue
        per_request = (tokens_in / 1e6) * price["input"] + (tokens_out / 1e6) * price["output"]
        total = per_request * monthly_requests + infra
        if tier == current:
            baseline_total = total
        rows.append((tier, model, total))

    for tier, model, total in rows:
        marker = "  <- now" if tier == current else ""
        if total is None:
            out.append(f"    {tier:<8}{model:<26}{'no price':>10}{marker}")
            continue
        if baseline_total is None or tier == current:
            delta = "—"
        else:
            delta = f"{total - baseline_total:+,.0f}"
        out.append(f"    {tier:<8}{model:<26}{total:>9,.0f}   {delta:>10}{marker}")

    out.append("")
    out.append("    Cost is arithmetic. ANSWER QUALITY IS NOT IN THIS TABLE,")
    out.append("    because a run cannot tell you it. Only `nimbus guard` can.")
    return out


def cost_split(payload: dict, scenario: dict, width: int = 24) -> list[str]:
    """The monthly bill separated into tokens and hosting.

    Participants never deploy anything, so "what does it cost to keep a server
    on" is invisible to them by default. It is 18% of this bill and it is owed
    whether or not a single customer asks a question.
    """
    s = summarise(payload, scenario)
    tokens, infra, total = (s["usd_tokens_per_month"], s["usd_infra_per_month"],
                            s["usd_per_month"])
    if total is None or not total:
        return ["    cost unknown for this run"]
    out = []
    for label, value in (("tokens to the model provider", tokens),
                         ("keeping the server on", infra)):
        if value is None:
            out.append(f"    {label:<32}{'unknown':>9}")
            continue
        share = value / total * 100
        bar = "█" * max(1, int(round(value / total * width)))
        out.append(f"    {label:<32}{value:>8,.0f}   {share:3.0f}%")
        out.append(f"    {'':<32}{bar}")
    out.append(f"    {'':<32}{'-'*8}")
    out.append(f"    {'total per month':<32}{total:>8,.0f}")
    return out
