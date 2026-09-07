"""Verify two disposable team deployments and rehearse the participant CLI.

Requires services deployed by deploy_incident.py --all --teams 2 with the given
prefix (prompt then retrieval). Uses real provider calls and changes only these
services. Credentials stay in memory/child environments, never artifacts.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmark"))
from run_context import run_directory
from report import recovery, summarise
from preflight import check, _service_token


def http(url, token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token: headers["X-Nimbus-Admin-Token"] = token
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, {}


def describe(name, args):
    result = subprocess.run(["gcloud", "run", "services", "describe", name,
        f"--project={args.project}", f"--region={args.region}", "--format=json"],
        capture_output=True, text=True, check=True)
    service = json.loads(result.stdout)
    return {"name": name, "url": service["status"]["url"],
            "revision": service["status"]["latestReadyRevisionName"],
            "image": service["spec"]["template"]["spec"]["containers"][0]["image"]}


def cli(target, token, session, output, *command, allow_failure=False):
    env = {**os.environ, "NIMBUS_URL": target["url"], "NIMBUS_TOKEN": token,
           "NIMBUS_SESSION": session}
    started = time.monotonic()
    result = subprocess.run([sys.executable, str(ROOT / "cli" / "nimbus"), *command],
                            env=env, capture_output=True, text=True, timeout=600)
    print(f"  {' '.join(command)}: exit {result.returncode}, {time.monotonic()-started:.1f}s", flush=True)
    with output.open("a") as file:
        file.write(f"\n$ nimbus {' '.join(command)}\n{result.stdout}\n{result.stderr}\n")
    if result.returncode and not allow_failure:
        raise RuntimeError(f"CLI {command[0]} failed; see {output}")
    return result.returncode


def latest(target, session):
    directory = run_directory(ROOT / ".nimbus-runs", target["url"], session)
    path = max(directory.glob("run-*.json"), key=lambda p: int(p.stem.split("-")[1]))
    return json.loads(path.read_text())


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--prefix", default="nimbus-verify")
    ap.add_argument("--project", default="adsc-nimbus")
    ap.add_argument("--region", default="us-central1")
    ap.add_argument("--session", default=datetime.now(timezone.utc).strftime("verify-%Y%m%dT%H%M%SZ"))
    args = ap.parse_args()
    output = ROOT / "results" / args.session
    output.mkdir(parents=True, exist_ok=True)
    targets = [describe(f"{args.prefix}-{letter}", args) for letter in ("a", "b")]
    tokens = [_service_token(t["name"], args.project, args.region) for t in targets]
    assert tokens[0] != tokens[1], "team credentials are shared"
    assert targets[0]["image"] == targets[1]["image"] and "@sha256:" in targets[0]["image"], "services do not share an immutable image"
    evidence = {"session": args.session, "targets": targets, "isolation": False, "teams": []}
    for i, target in enumerate(targets):
        print(f"Preflight {target['name']}", flush=True)
        problems = check(target["url"], tokens[i])
        assert not problems, problems
        assert http(target["url"] + "/metrics", tokens[1-i])[0] == 401
        assert http(target["url"] + "/levers", tokens[1-i], {"MAX_TOKENS": 32})[0] == 401
        status, declarations = http(target["url"] + "/declarations", tokens[i])
        assert status == 200 and declarations["hypothesis_required"] and not declarations["declarations"], "rehearsal needs fresh gated services"
        assert http(target["url"] + "/levers", tokens[i], {"MAX_TOKENS": 32})[0] == 409
    evidence["isolation"] = True
    started = time.monotonic()
    scenario = json.loads((ROOT / "scenario.json").read_text())
    for i, target in enumerate(targets):
        token = tokens[i]
        log = output / f"{target['name']}.txt"
        team_start = time.monotonic()
        cli(target, token, args.session, log, "brief")
        cli(target, token, args.session, log, "baseline")
        baseline = latest(target, args.session)
        baseline_summary = summarise(baseline, scenario)
        baseline_failed = (baseline_summary["p95"] > scenario["constraints"]["slo_p95_latency_s"]
                           or baseline_summary["usd_per_month"] is None
                           or baseline_summary["usd_per_month"] > scenario["constraints"]["budget_usd_per_month"])
        assert baseline_failed, "assigned incident did not fail a measured constraint"
        if i == 0:
            assert baseline_summary["tokens_in_mean"] >= 3 * scenario["baselines"]["default"]["tokens_in"], "prompt discriminator missing"
        else:
            assert max(baseline_summary["ledger"], key=baseline_summary["ledger"].get) == "retrieve", "retrieval discriminator missing"
        (output / f"{target['name']}-baseline.json").write_text(json.dumps(baseline, indent=2))
        cli(target, token, args.session, log, "diagnose")
        if i == 0:
            proof = f"input tokens average {baseline_summary['tokens_in_mean']:.0f}; inspect excess context"
            cli(target, token, args.session, log, "hypothesis", "--slice", "input token count", "--proof", proof)
            cli(target, token, args.session, log, "set", "SYSTEM_PROMPT=TRIMMED")
            cli(target, token, args.session, log, "bench", "--label", "trim instructions only")
            cli(target, token, args.session, log, "set", "RETRIEVE_K=3")
            cli(target, token, args.session, log, "bench", "--label", "restore retrieval context")
        else:
            proof = f"retrieval is {baseline_summary['ledger']['retrieve']:.0f}ms in the p95 request"
            cli(target, token, args.session, log, "hypothesis", "--slice", "retrieve", "--proof", proof)
            cli(target, token, args.session, log, "set", "SEMANTIC_CACHE=true")
            cli(target, token, args.session, log, "bench", "--label", "reuse answers before retrieval")
        cli(target, token, args.session, log, "eval", allow_failure=True)
        final = latest(target, args.session)
        outcome = recovery(final, scenario)
        (output / f"{target['name']}-final.json").write_text(json.dumps(final, indent=2))
        evidence["teams"].append({"service": target["name"], "baseline_failed": baseline_failed, "baseline": {
            "p95": baseline_summary["p95"], "usd_per_month": baseline_summary["usd_per_month"]},
            "final": {"p95": summarise(final, scenario)["p95"],
                      "quality": final.get("quality"), "recovery": outcome},
            "elapsed_s": round(time.monotonic()-team_start, 1)})
        (output / "summary.json").write_text(json.dumps(evidence, indent=2))
    evidence["elapsed_s"] = round(time.monotonic()-started, 1)
    evidence["passed"] = evidence["isolation"] and all(t["final"]["recovery"]["recovered"] for t in evidence["teams"]) and evidence["elapsed_s"] < 1200
    (output / "summary.json").write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2), flush=True)
    if not evidence["passed"]:
        sys.exit("Cloud rehearsal did not meet acceptance; inspect saved evidence.")


if __name__ == "__main__":
    main()
