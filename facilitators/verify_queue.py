"""Exercise the round-1 queue recovery on a fresh disposable Cloud Run service."""
import argparse
import json
import pathlib
import sys
import time

from verify_cloud import ROOT, cli, describe, latest, http
from preflight import check, _service_token
from report import summarise, recovery


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--service", default="nimbus-verify-queue")
    ap.add_argument("--project", default="adsc-nimbus")
    ap.add_argument("--region", default="us-central1")
    ap.add_argument("--session", default="queue-verification")
    args = ap.parse_args()
    target = describe(args.service, args)
    token = _service_token(args.service, args.project, args.region)
    problems = check(target["url"], token)
    assert not problems, problems
    status, metrics = http(target["url"] + "/metrics", token)
    assert status == 200 and metrics["config"]["MAX_CONCURRENT"] == 1 and not metrics["config"]["RESPONSE_CACHE"], "requires fresh queue incident"
    output = ROOT / "results" / args.session
    output.mkdir(parents=True, exist_ok=True)
    log = output / "cli.txt"
    scenario = json.loads((ROOT / "scenario.json").read_text())
    start = time.monotonic()
    cli(target, token, args.session, log, "brief")
    cli(target, token, args.session, log, "baseline")
    baseline = latest(target, args.session)
    initial = summarise(baseline, scenario)
    assert initial["p95"] > scenario["constraints"]["slo_p95_latency_s"]
    assert max(initial["ledger"], key=initial["ledger"].get) == "queue"
    (output / "baseline.json").write_text(json.dumps(baseline, indent=2))
    cli(target, token, args.session, log, "diagnose")
    cli(target, token, args.session, log, "hypothesis", "--slice", "app queue wait", "--proof", f"queue contributes {initial['ledger']['queue']:.0f}ms to the p95 request")
    cli(target, token, args.session, log, "set", "RESPONSE_CACHE=true")
    cli(target, token, args.session, log, "bench", "--label", "reuse repeated answers")
    candidate = recovery(latest(target, args.session), scenario)
    if not (candidate["latency_ok"] and candidate["availability_ok"]):
        cli(target, token, args.session, log, "set", "MAX_CONCURRENT=2")
        cli(target, token, args.session, log, "bench", "--label", "increase application admission after removing repeated work")
    cli(target, token, args.session, log, "eval", allow_failure=True)
    final = latest(target, args.session)
    (output / "final.json").write_text(json.dumps(final, indent=2))
    outcome = {"target": target, "baseline_p95": initial["p95"],
               "final_p95": summarise(final, scenario)["p95"],
               "quality": final.get("quality"), "recovery": recovery(final, scenario),
               "elapsed_s": round(time.monotonic()-start, 1)}
    (output / "summary.json").write_text(json.dumps(outcome, indent=2))
    print(json.dumps(outcome, indent=2), flush=True)
    if not outcome["recovery"]["recovered"]:
        sys.exit("Queue recovery did not meet acceptance.")


if __name__ == "__main__":
    main()
