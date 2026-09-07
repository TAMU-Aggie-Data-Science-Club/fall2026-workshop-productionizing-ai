"""Measure every incident's signature, and refuse to ship a collision.

NOT FOR PARTICIPANTS.

The signature matrix in any design document is a hypothesis. This produces the
shipped one from measurement, the same way the eval card and the answer key are
produced -- because the property the activity depends on is not "these incidents
look different in principle", it is "these incidents measurably looked different
on the hardware the room will use".

The check that matters runs at the end: for every PAIR of incidents, at least
one signal must differ by more than measurement noise. If two incidents move the
same signals by the same amounts, a participant diagnosing one of them is
guessing, and the room correctly concludes that diagnosis does not work. That is
a build failure, not a footnote.

Each incident gets its own server process, because injection is configured by
environment variable and a running process cannot be handed a new environment --
which is also exactly how Cloud Run behaves.

    .venv/bin/python facilitators/calibrate_incidents.py
    .venv/bin/python facilitators/calibrate_incidents.py --only queue,retrieval
"""
import argparse
import asyncio
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "facilitators"))
sys.path.insert(0, str(ROOT / "benchmark"))
sys.path.insert(0, str(ROOT / "service"))

import config                                    # noqa: E402
from incidents import (HEALTHY_ENV, HEALTHY_TRAFFIC, INCIDENTS,  # noqa: E402
                       QUALITY_SEPARATED, for_backend)
import report                                  # noqa: E402
import run as bench                            # noqa: E402

SCENARIO = json.loads((ROOT / "scenario.json").read_text())
OUT = ROOT / "facilitators" / "generated" / "signatures.json"
PANELS = ROOT / "facilitators" / "generated" / "incident_panels"
PAYLOAD_DIR = ROOT / "facilitators" / "generated" / "incident_payloads"
SCENARIO_PATH = ROOT / "scenario.json"
PAYLOADS: dict[str, dict] = {}

# Repeat runs of an identical configuration vary by roughly this much on this
# workload, so two incidents that differ by less than it have not been shown to
# differ at all.
NOISE = 0.15

# Below these absolute values a signal is not carrying information, and a
# relative difference between two of them is arithmetic rather than evidence.
# Without this floor, "retrieve was 0.18% of the budget here and 0.51% there"
# scored as a 65% separation and let a genuinely indistinguishable pair pass.
FLOORS = {
    "queue_share": 0.05, "retrieve_share": 0.05, "generate_share": 0.05,
    "tokens_in": 40.0, "tokens_out": 12.0, "retries": 1.0,
    "tail_p99_over_p95": 0.25, "failure_rate": 0.02,
}

# Signals that are not real below this many successful requests. With 16, "p99"
# IS the slowest request and "p95" the second slowest, so their ratio is one
# unlucky request rather than a property of the service. It let the two
# incidents that are SUPPOSED to be indistinguishable pass the collision check
# on 1.84 vs 1.31 -- burying the very declaration that documents why they are
# alike. The report already refuses to speak confidently about percentiles at
# this sample size; the collision check has to be at least as careful.
DEGENERATE_BELOW = {"tail_p99_over_p95": 50}


def expected_injection(name: str) -> str:
    """Which deployment a valid signature for this incident must come from.

    An incident with no fault injection can only be measured on a service that
    carries none; one with injection can only be measured on a service carrying
    ITS injection. Merging across deployments without this check produced a
    `cheapmodel` signature with a higher retrieve_share (0.81) than the
    retrieval incident itself (0.59) -- it had been measured while the retrieval
    delay was deployed, so it was really "cheapmodel plus somebody else's fault".
    """
    return name if split_env(INCIDENTS[name]["env"])[1] else "none"


def split_env(env: dict) -> tuple[dict, dict]:
    """Separate what a running service can be told from what it must be born with.

    Config settings reach a live service through /levers in about a tenth of a
    second. Fault injection cannot: it is read from the environment at import,
    deliberately, so that a participant holding their own team token cannot set
    or read their own incident. That privacy costs a redeployment per injected
    incident, and it is worth it.
    """
    levers, injection = {}, {}
    for key, value in env.items():
        name = key[len("NIMBUS_"):] if key.startswith("NIMBUS_") else key
        if name in config.LEVERS:
            levers[name] = value
        else:
            injection[key] = value
    return levers, injection


def _post(url: str, path: str, token: str, payload: dict) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{url}{path}", method="POST",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "X-Nimbus-Admin-Token": token})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        body = exc.read() or b"{}"
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"error": body.decode(errors="replace")[:200]}


def apply_levers(url: str, token: str, levers: dict) -> None:
    """Put the running service into a known configuration.

    Always sends the FULL healthy lever set with the incident's values layered
    on top, never just the incident's own keys. A remote service keeps whatever
    the previous measurement left on it, so an incident that omits a lever
    silently inherits the last one's value -- and the result then depends on the
    order the incidents were measured in. `prompt` omitted MAX_CONCURRENT, ran
    after `queue` had set it to 1, and measured 54% queue wait: the wrong
    incident entirely, and only because of what ran before it.
    """
    full = {**split_env(HEALTHY_ENV)[0], **levers}
    status, body = _post(url, "/levers", token, full)
    if status == 409:
        # The diagnose-first gate is armed on this service. Calibration is not a
        # participant and has nothing to diagnose, so it records that plainly
        # rather than pretending to have a hypothesis.
        _post(url, "/hypothesis", token, {
            "dominant_slice": "n/a",
            "model_implicated": False,
            "proof_metric": "automated calibration, not a diagnosis"})
        status, body = _post(url, "/levers", token, levers)
    if status != 200:
        raise RuntimeError(f"could not set levers ({status}): {body}")


def ensure_warm(url: str, rounds: int = 6, batch: int = 4) -> None:
    """Fire discarded traffic until the service stops getting faster.

    A Cloud Run instance that has just been deployed, or has scaled to zero, is
    dramatically slower for its first requests -- and the effect is large enough
    to invent an incident. Measured on this service: three back-to-back runs of
    an IDENTICAL configuration gave p95 3.00s, 12.10s and 7.87s cold, against
    1.95s, 2.03s and 1.95s once warm. The cold numbers made the retrieval
    incident look like a generation problem, which is the precise misreading the
    whole activity exists to prevent.

    The benchmark's own two-request warmup is sized for a process that is
    already running. This is sized for a container that is not.
    """
    # Real requests, not the benchmark's 4-token warmup: a cheap request does
    # not exercise the same paths and can report warm while the first full
    # request still pays. Stop when a batch is no faster than the one before it.
    questions = [bench.PROMPTS[i % len(bench.PROMPTS)]["question"]
                 for i in range(batch)]
    previous = None
    for attempt in range(rounds):
        started = time.perf_counter()
        asyncio.run(bench.drive(url, questions, rate=8.0, concurrency=2))
        elapsed = time.perf_counter() - started
        if previous is not None and elapsed > previous * 0.85:
            return
        previous = elapsed
    print(f"      warmup ran {rounds} rounds and was still speeding up; "
          f"treat this calibration as suspect", flush=True)


def store_payload(name: str, payload: dict) -> None:
    """Keep the raw timings, not just the rendered panel.

    Three incidents can only be measured by redeploying, so without this every
    change to the SLO or the price table would strand their panels asserting a
    verdict against constraints that no longer exist -- or cost three
    deployments to refresh a number that never moved.
    """
    PAYLOADS[name] = payload
    PAYLOAD_DIR.mkdir(exist_ok=True)
    (PAYLOAD_DIR / f"{name}.json").write_text(json.dumps(payload, indent=2))


def measure_remote(name: str, url: str, token: str, levers: dict,
                   traffic: dict, requests_n: int | None) -> dict:
    apply_levers(url, token, levers)
    n = requests_n or traffic["requests"]
    questions = [bench.PROMPTS[i % len(bench.PROMPTS)]["question"] for i in range(n)]
    asyncio.run(bench.warmup(url, SCENARIO["bench_defaults"]["warmup"]))
    results, duration = asyncio.run(
        bench.drive(url, questions, traffic["rate"], traffic["concurrency"]))
    payload = {"run": 0, "label": name, "duration_s": duration, "args": {},
               "server_config": {}, "server_runtime": {"provider": "google"},
               "results": results}
    store_payload(name, payload)
    return report.summarise(payload, SCENARIO)


def _wait_for_health(url: str, timeout_s: float) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{url}/health", timeout=3).read()
            return True
        except Exception:  # noqa: BLE001
            time.sleep(1.0)
    return False


def _serve(env_overrides: dict, port: int):
    env = {**os.environ, **env_overrides, "PORT": str(port)}
    proc = subprocess.Popen(
        [str(ROOT / ".venv" / "bin" / "uvicorn"), "app:app",
         "--app-dir", "service", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return proc


def measure(name: str, env: dict, traffic: dict, port: int,
            requests_n: int | None = None) -> dict:
    """Boot a service under this configuration, benchmark it, summarise."""
    url = f"http://127.0.0.1:{port}"
    proc = _serve(env, port)
    try:
        if not _wait_for_health(url, timeout_s=180):
            err = (proc.stderr.read() or b"").decode(errors="replace")[-600:]
            raise RuntimeError(f"{name}: service never became healthy\n{err}")

        n = requests_n or traffic["requests"]
        questions = [bench.PROMPTS[i % len(bench.PROMPTS)]["question"]
                     for i in range(n)]
        asyncio.run(bench.warmup(url, SCENARIO["bench_defaults"]["warmup"]))
        results, duration = asyncio.run(
            bench.drive(url, questions, traffic["rate"], traffic["concurrency"]))

        payload = {"run": 0, "label": name, "duration_s": duration, "args": {},
                   "server_config": {}, "server_runtime": {"provider": "local"},
                   "results": results}
        # Stored, and rendered LATER. The panel prints each measurement against
        # a calibrated baseline -- and the baseline is produced by this very
        # run, so rendering here would stamp every panel "not calibrated" and
        # strip the comparator the prompt and decode incidents are diagnosed by.
        store_payload(name, payload)
        return report.summarise(payload, SCENARIO)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


def signature(summary: dict) -> dict:
    """The comparable signal vector.

    Shares rather than seconds, so the matrix survives being re-measured on
    slower hardware -- the whole point of generating it rather than writing it
    down.

    Shares are taken over the SERVER-side budget, excluding client+network.
    Measured from a laptop over the public internet, network was 1.48s of a
    1.96s request: it swamped the denominator, pushed every server-side share
    toward zero, and made the capacity incident unrecognisable. What the service
    does and where you stood when you measured it are different facts, and only
    the first one belongs in a signature.

    The participant's panel still shows client+network. There it is a real
    addend and a real lesson -- latency is additive, and the network hop is one
    of the addends.
    """
    ledger = summary["ledger"]
    server_total = sum(v for k, v in ledger.items() if k != "client_network") or 1.0
    total = sum(ledger.values()) or 1.0
    p95 = summary["p95"] or 1e-9
    return {
        "queue_share": ledger["queue"] / server_total,
        "retrieve_share": ledger["retrieve"] / server_total,
        "generate_share": ledger["generate"] / server_total,
        # Reported, never compared: high values mean the measurement was taken
        # far from the service, not that the service is slow.
        "_client_network_share": ledger["client_network"] / total,
        "_ok": float(summary["ok"]),
        "_measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "tokens_in": summary["tokens_in_mean"],
        "tokens_out": summary["tokens_out_mean"],
        "retries": float(summary["upstream_retries"]),
        "tail_p99_over_p95": summary["p99"] / p95,
        "failure_rate": summary["failed"] / max(summary["ok"] + summary["failed"], 1),
    }


def check_expectation(name: str, sig: dict, summary: dict,
                      healthy: dict) -> str | None:
    """Did this incident actually produce the symptom it claims?

    A collision check proves two incidents differ. It does not prove either one
    presents as advertised -- and an incident whose dominant ledger row points
    at the wrong component teaches the opposite of its lesson. This is the check
    that caught the retrieval incident reading as 96% "generate".
    """
    expect = INCIDENTS[name].get("expect") or {}

    if "dominant" in expect:
        shares = {"queue": sig["queue_share"], "retrieve": sig["retrieve_share"],
                  "generate": sig["generate_share"]}
        top = max(shares, key=shares.get)
        if top != expect["dominant"]:
            return (f"expected {expect['dominant']!r} to dominate the ledger, "
                    f"but {top!r} did ({shares[top]*100:.0f}% vs "
                    f"{shares[expect['dominant']]*100:.0f}%)")

    if "signal" in expect and "at_least_x" in expect:
        key = expect["signal"]
        base = healthy[key] or 1e-9
        ratio = sig[key] / base
        if ratio < expect["at_least_x"]:
            return (f"expected {key} at least {expect['at_least_x']}x the healthy "
                    f"baseline, measured {ratio:.1f}x ({sig[key]:.0f} vs {base:.0f})")

    if "signal" in expect and "at_least" in expect:
        key = expect["signal"]
        if sig[key] < expect["at_least"]:
            return f"expected {key} >= {expect['at_least']}, measured {sig[key]:.0f}"

    if expect.get("infra_passes"):
        constraints = SCENARIO["constraints"]
        if summary["p95"] > constraints["slo_p95_latency_s"]:
            return (f"expected every infrastructure signal to PASS (the whole "
                    f"point is that the benchmark cannot see this one), but p95 "
                    f"{summary['p95']:.2f}s exceeds the "
                    f"{constraints['slo_p95_latency_s']}s target")
    return None


def separations(a: dict, b: dict) -> dict:
    """Per-signal relative difference, ignoring differences too small to see.

    A signal only separates two incidents if it moved by a relative amount above
    measurement noise, by an absolute amount a participant could read off the
    panel, and on enough requests for the number to mean anything.
    """
    out = {}
    n_ok = min(a.get("_ok", 0), b.get("_ok", 0))
    for key in a:
        # Underscore-prefixed entries are recorded for context, never compared.
        # Letting client+network into this loop would allow two incidents to
        # "separate" on whoever's wifi took the measurement.
        if key.startswith("_"):
            continue
        if n_ok < DEGENERATE_BELOW.get(key, 0):
            out[key] = 0.0
            continue
        lo, hi = sorted((a[key], b[key]))
        if (hi - lo) < FLOORS.get(key, 0.0):
            out[key] = 0.0
            continue
        scale = max(abs(hi), abs(lo), 1e-6)
        out[key] = (hi - lo) / scale
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", default="", help="comma-separated incident names")
    ap.add_argument("--backend", default=os.environ.get("NIMBUS_MODEL_BACKEND", "local"))
    ap.add_argument("--requests", type=int, default=SCENARIO["bench_defaults"]["requests"])
    # Above 1024: binding a privileged port fails with a permission error that
    # looks exactly like "the service never started".
    ap.add_argument("--port", type=int, default=8710)
    ap.add_argument("--remote", default="",
                    help="calibrate a deployed service instead of booting "
                         "local ones (levers are set over HTTP)")
    ap.add_argument("--token", default=os.environ.get("NIMBUS_ADMIN_TOKEN", ""),
                    help="team token for the remote service")
    ap.add_argument("--assume-deployed", default="",
                    help="comma-separated incidents whose injection env is "
                         "already present on the remote service")
    ap.add_argument("--render-only", action="store_true",
                    help="re-render every stored panel against the current "
                         "scenario.json without measuring anything")
    ap.add_argument("--check-only", action="store_true",
                    help="re-run the collision check against the last "
                         "measurement instead of measuring again")
    args = ap.parse_args()

    remote = args.remote.rstrip("/")
    if args.render_only:
        _render_panels()
        return
    if args.check_only and OUT.exists():
        # Check the set that was actually measured, on the backend it was
        # measured against -- not whatever this invocation happens to default to.
        args.backend = json.loads(OUT.read_text()).get("backend", args.backend)
    if remote:
        args.backend = "google"
        if not args.token:
            sys.exit("--remote needs --token (or NIMBUS_ADMIN_TOKEN).")

    available = for_backend(args.backend)
    names = [n.strip() for n in args.only.split(",") if n.strip()] or available
    skipped = [n for n in names if n not in available]
    names = [n for n in names if n in available]
    if skipped:
        print(f"skipping (not producible on the {args.backend} backend): "
              f"{', '.join(skipped)}", flush=True)

    # Injection is read from the environment at import, so a remote service can
    # only carry an incident it was DEPLOYED with. Rather than silently
    # measuring the wrong thing, say which incidents this run cannot produce.
    if remote:
        assumed = {n.strip() for n in args.assume_deployed.split(",") if n.strip()}
        needs_deploy = [n for n in names
                        if split_env(INCIDENTS[n]["env"])[1] and n not in assumed]
        if needs_deploy:
            print("\nNOT MEASURABLE on this deployment -- fault injection is "
                  "deploy-time only:", flush=True)
            for n in needs_deploy:
                _, injection = split_env(INCIDENTS[n]["env"])
                pairs = " ".join(f"{k}='{v}'" for k, v in injection.items())
                print(f"  {n}: redeploy with {pairs}", flush=True)
                print(f"      then re-run with --only {n} --assume-deployed {n}",
                      flush=True)
            names = [n for n in names if n not in needs_deploy]
            print(flush=True)
        if not names:
            sys.exit("Nothing left to measure.")

    if args.check_only:
        cached = json.loads(OUT.read_text())
        signatures = {k: v for k, v in cached["signatures"].items() if k in names}
        # Only re-check what was actually measured. A cache from a partial run
        # holds fewer incidents than the catalog lists.
        missing = [n for n in names if n not in signatures]
        if missing:
            print(f"not in the last measurement, skipping: {', '.join(missing)}\n",
                  flush=True)
        names = [n for n in names if n in signatures]
        healthy, broken = cached["healthy"], []
        print(f"checking {len(signatures)} cached signatures from "
              f"{cached['measured_at']}\n", flush=True)
        _report(names, signatures, healthy, broken, args, write=False)
        return

    # A healthy run under calm traffic. "Anomalous" is meaningless without it,
    # and the token baselines in scenario.json come from here.
    print("[0] measuring HEALTHY baseline ...", flush=True)
    if remote:
        ensure_warm(remote)
        assumed_any = bool(args.assume_deployed.strip())
        cached_healthy = None
        if assumed_any and OUT.exists():
            try:
                cached_healthy = json.loads(OUT.read_text()).get("healthy")
            except json.JSONDecodeError:
                cached_healthy = None
        # The baseline is subject to the same rule as every signature: it is
        # only valid if the deployment that produced it was carrying no fault.
        # One measured on the retrieval deployment reported 66% `retrieve` as
        # "healthy" -- the reference would have contained the very fault it
        # exists to be compared against.
        if cached_healthy and cached_healthy.get("_injection") not in (None, "none"):
            print(f"  ignoring the cached HEALTHY baseline: it was measured "
                  f"while '{cached_healthy['_injection']}' was deployed",
                  flush=True)
            cached_healthy = None
        if assumed_any and cached_healthy:
            # This deployment carries fault injection, which is read from the
            # environment and cannot be turned off over /levers. Measuring a
            # "healthy" baseline on it would fold the injected fault into the
            # very reference the incident is compared against -- the retrieval
            # incident would be measured against a baseline that already had the
            # retrieval delay in it. Reuse the one taken on a clean deployment.
            print("[0] reusing the HEALTHY baseline from a clean deployment "
                  "(this one carries injection)", flush=True)
            healthy = cached_healthy
            healthy_summary = None
        else:
            healthy_summary = measure_remote(
                "healthy", remote, args.token, split_env(HEALTHY_ENV)[0],
                HEALTHY_TRAFFIC, args.requests)
    else:
        healthy_summary = measure("healthy", HEALTHY_ENV, HEALTHY_TRAFFIC,
                                  args.port, args.requests)
    if healthy_summary is not None:
        healthy = signature(healthy_summary)
        healthy["_injection"] = ("none" if not remote or not args.assume_deployed.strip()
                                 else args.assume_deployed.strip())
    print(f"      {'p95 %6.2fs  ' % healthy_summary['p95'] if healthy_summary else 'cached      '}"
          f"queue {healthy['queue_share']*100:3.0f}%  "
          f"retrieve {healthy['retrieve_share']*100:3.0f}%  "
          f"generate {healthy['generate_share']*100:3.0f}%  "
          f"tok_in {healthy['tokens_in']:.0f}  "
          f"tok_out {healthy['tokens_out']:.0f}", flush=True)

    signatures, summaries, broken = {}, {}, []
    for i, name in enumerate(names):
        print(f"[{i+1}/{len(names)}] measuring {name} ...", flush=True)
        spec = INCIDENTS[name]
        if remote:
            summary = measure_remote(name, remote, args.token,
                                     split_env(spec["env"])[0],
                                     spec["traffic"], args.requests)
        else:
            summary = measure(name, spec["env"], spec["traffic"],
                              args.port + i + 1, args.requests)
        summaries[name] = summary
        signatures[name] = sig = signature(summary)
        # Stamp which fault the measuring deployment was carrying, so a later
        # run can tell a valid signature from one taken under another incident.
        sig["_injection"] = (name if remote and name in
                             {n.strip() for n in args.assume_deployed.split(",") if n.strip()}
                             else expected_injection(name) if not remote
                             else "none")
        print(f"      p95 {summary['p95']:6.2f}s  queue {sig['queue_share']*100:3.0f}%  "
              f"retrieve {sig['retrieve_share']*100:3.0f}%  "
              f"generate {sig['generate_share']*100:3.0f}%  "
              f"tok_in {sig['tokens_in']:.0f}  tok_out {sig['tokens_out']:.0f}  "
              f"retries {sig['retries']:.0f}", flush=True)
        problem = check_expectation(name, sig, summary, healthy)
        if problem:
            broken.append((name, problem))
            print(f"      DOES NOT PRESENT AS ADVERTISED: {problem}", flush=True)

    if healthy_summary is not None:
        # Only republish baselines from a baseline we actually just took. A
        # reused one is already in scenario.json, and rewriting it would stamp
        # a fresh timestamp on a measurement from an earlier deployment.
        _write_baselines(healthy, args.backend)
    _render_panels()
    _report(names, signatures, healthy, broken, args, write=True)


def _write_baselines(healthy: dict, backend: str) -> None:
    """Publish the healthy reference into scenario.json, so the report can say
    what "normal" is instead of printing a number with nothing to compare."""
    import os
    import platform
    scenario = json.loads(SCENARIO_PATH.read_text())
    base = scenario.setdefault("baselines", {}).setdefault("default", {})
    scenario["baselines"]["_backend"] = backend
    base["tokens_in"] = round(healthy["tokens_in"])
    base["tokens_out"] = round(healthy["tokens_out"])
    scenario["baselines"]["_measured_on"] = (
        f"{platform.machine()} {platform.system()} · {os.cpu_count()} cores · "
        f"{backend} backend · calm traffic (rate "
        f"{HEALTHY_TRAFFIC['rate']}, concurrency "
        f"{HEALTHY_TRAFFIC['concurrency']}) · "
        f"{time.strftime('%Y-%m-%d %H:%M:%S')}")
    SCENARIO_PATH.write_text(json.dumps(scenario, indent=2) + "\n")
    print(f"\nbaselines -> tokens_in {base['tokens_in']}, "
          f"tokens_out {base['tokens_out']}", flush=True)


def _render_panels() -> None:
    """Re-render EVERY stored run against the current scenario.

    Not just the ones measured in this pass: a panel states a verdict, and a
    verdict is only meaningful against the constraints in force now. Rendering
    only the fresh ones leaves the deploy-only incidents asserting PASS or FAIL
    against an SLO that no longer exists.
    """
    scenario = json.loads(SCENARIO_PATH.read_text())
    PANELS.mkdir(exist_ok=True)
    stored = {}
    if PAYLOAD_DIR.exists():
        for path in PAYLOAD_DIR.glob("*.json"):
            try:
                stored[path.stem] = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
    stored.update(PAYLOADS)
    for name, payload in stored.items():
        (PANELS / f"{name}.txt").write_text(
            report.render(payload, scenario, pathlib.Path("/nonexistent")))
    reused = sorted(set(stored) - set(PAYLOADS))
    print(f"panels  -> {len(stored)} rendered against the current scenario"
          + (f" ({len(reused)} from stored runs: {', '.join(reused)})" if reused else ""),
          flush=True)


def _report(names, signatures, healthy, broken, args, write: bool) -> None:
    """Collision check, artifact, verdict. Shared by measuring and --check-only."""
    # MERGE, never replace. Three incidents carry deploy-time injection and can
    # only be measured one redeployment at a time, so a run that overwrote the
    # file would mean the full set never existed in one place. Each signature
    # carries its own timestamp, so one measured against an older deployment is
    # visible rather than silently trusted.
    previous = {}
    if write and OUT.exists():
        try:
            cached = json.loads(OUT.read_text())
            if cached.get("backend") == args.backend:
                previous = cached.get("signatures", {})
            elif cached.get("signatures"):
                print(f"  (discarding signatures measured on the "
                      f"{cached.get('backend')} backend)", flush=True)
        except json.JSONDecodeError:
            pass
    # Drop anything measured on a deployment that was carrying the wrong fault.
    valid_previous = {}
    for name, entry in previous.items():
        if name not in INCIDENTS:
            continue
        if entry.get("_injection") == expected_injection(name):
            valid_previous[name] = entry
        elif name not in signatures:
            print(f"  discarding stale {name}: measured while "
                  f"'{entry.get('_injection', 'unknown')}' was deployed, needs "
                  f"'{expected_injection(name)}'", flush=True)
    merged = {**valid_previous, **signatures}
    carried = sorted(set(merged) - set(signatures))
    if carried:
        print(f"  carried forward from earlier runs: {', '.join(carried)}",
              flush=True)

    # Check every pair we know about, not only the ones measured just now --
    # otherwise calibrating one deploy-only incident never checks it against
    # the rest, which is the entire purpose of the check.
    check_names = sorted(merged)
    collisions = []
    for i, a in enumerate(check_names):
        for b in check_names[i + 1:]:
            sep = separations(merged[a], merged[b])
            best_signal = max(sep, key=sep.get)
            if sep[best_signal] > NOISE:
                print(f"  {a} vs {b}: separated by {best_signal} "
                      f"({sep[best_signal]*100:.0f}%)", flush=True)
            elif frozenset({a, b}) in QUALITY_SEPARATED:
                # Declared indistinguishable to the benchmark on purpose: the
                # point of this pair is that infrastructure metrics cannot see a
                # quality regression, and only the eval separates them.
                print(f"  {a} vs {b}: not separated by ANY infrastructure "
                      f"signal -- declared quality-separated, verify with "
                      f"eval_all.py", flush=True)
            else:
                collisions.append((a, b, sep))

    if write:
        OUT.write_text(json.dumps({
            "backend": args.backend,
            "requests": args.requests,
            "noise_threshold": NOISE,
            "absolute_floors": FLOORS,
            "healthy": healthy,
            "signatures": merged,
            "quality_separated": [sorted(pair) for pair in QUALITY_SEPARATED],
            "measured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "_comment": ("Generated by facilitators/calibrate_incidents.py. Never "
                         "hand-edit. Shares are fractions of the p95 request's "
                         "latency budget; token counts are absolute. Latency-shaped "
                         "values are hardware-dependent -- re-measure on the "
                         "hardware the session will actually use, with nothing "
                         "else running on the machine."),
        }, indent=2))
        print(f"\nwrote {OUT.relative_to(ROOT)}")

    failed = False
    if broken:
        failed = True
        print("\nINCIDENTS THAT DO NOT PRESENT AS ADVERTISED:")
        for name, problem in broken:
            print(f"  {name}: {problem}")
    if collisions:
        failed = True
        print("\nSIGNATURE COLLISION -- these incidents are not distinguishable:")
        for a, b, sep in collisions:
            worst = max(sep, key=sep.get)
            print(f"  {a} vs {b}: best signal {worst} differs by only "
                  f"{sep[worst]*100:.0f}% (needs > {NOISE*100:.0f}%, and by more "
                  f"than the absolute floor for that signal)")
        print("\n  If a pair is MEANT to look identical to the benchmark, declare "
              "it in\n  incidents.QUALITY_SEPARATED and say which eval separates it.")
    if failed:
        sys.exit("\nA participant handed one of these would be guessing, not "
                 "diagnosing. Fix the catalog before running a session.")
    print("\nEvery incident presents as advertised, and every pair is separated "
          "by at least one signal.")


if __name__ == "__main__":
    main()
