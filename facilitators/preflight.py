"""Confirm a deployed Nimbus is actually usable. NOT FOR PARTICIPANTS.

Run this after deploying and before handing out URLs. It checks the things that
have actually gone wrong on this project, in the order they went wrong:

  1. the service is serving traffic at all
  2. /health reports ready, on the expected backend, with the note index built
  3. the model it will call is the one you meant -- a service configured with a
     model the project cannot reach starts up HEALTHY and 404s every request,
     because warm() validates credentials, not model access
  4. a real question returns real text -- Gemini 2.5 spends the output budget
     thinking before answering, and at a low MAX_TOKENS returns NO text at all
     while latency and cost still look fine
  5. both tiers work -- one thinking budget across two models is not always
     valid for both, and an out-of-range value is a hard 400 on the tier a team
     reaches for as their fix
  6. the incident is not readable from any participant-facing endpoint

Usage:
    python facilitators/preflight.py --url https://...run.app
    python facilitators/preflight.py --all-services        # every nimbus-team-*
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

TIMEOUT = 120


def _get(url, token=None):
    req = urllib.request.Request(url, headers={"X-Nimbus-Admin-Token": token} if token else {})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def _ask(url, question, max_tokens=None):
    body = {"question": question}
    if max_tokens:
        body["max_tokens"] = max_tokens
    req = urllib.request.Request(f"{url}/ask", method="POST",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    text, stats, error = [], None, None
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        for raw in r:
            line = raw.decode(errors="replace").strip()
            if not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload == "[DONE]":
                break
            try:
                event = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if "delta" in event:
                text.append(event["delta"])
            elif "stats" in event:
                stats = event["stats"]
            elif "error" in event:
                error = event["error"]
    return "".join(text), stats, error


def _post(url, token, body=None):
    req = urllib.request.Request(url, method="POST",
        data=json.dumps(body or {}).encode(),
        headers={"Content-Type": "application/json", "X-Nimbus-Admin-Token": token})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read())


def check(url: str, token: str) -> list[str]:
    """Check readiness without changing controls, declarations, or gate state."""
    if not token:
        return ["team token required: both model tiers and configuration must be verified"]
    problems = []
    try:
        health = _get(f"{url}/health")
        if not health.get("ok") or health.get("status") != "ready" or not health.get("note_chunks"):
            return ["service is not ready with a built retrieval index"]
        before = _get(f"{url}/metrics", token)
        declarations = _get(f"{url}/declarations", token)
        runtime = before.get("runtime", {})
        if health.get("backend") != "google" or runtime.get("provider") != "google":
            problems.append("cloud preflight requires the google backend")
        if any("INCIDENT" in key.upper() for key in before.get("config", {})):
            problems.append("private incident configuration is exposed")
        for endpoint in ("metrics", "declarations"):
            for bad in (None, "preflight-invalid-token"):
                try:
                    _get(f"{url}/{endpoint}", bad)
                    problems.append(f"/{endpoint} accepted missing or invalid authentication")
                except urllib.error.HTTPError as exc:
                    if exc.code != 401:
                        problems.append(f"/{endpoint} rejected authentication with {exc.code}, expected 401")
        verified = _post(f"{url}/verify-models", token)
        if not verified.get("ok"):
            problems.append("model verification failed")
        for tier in ("large", "small"):
            result = verified.get("tiers", {}).get(tier, {})
            expected = runtime.get(f"model_{tier}")
            if not result.get("ok") or not result.get("text", "").strip():
                problems.append(f"{tier} tier returned no usable text")
            if not expected or result.get("model") != expected:
                problems.append(f"{tier} tier did not confirm its configured model")
            if result.get("usage_source") != "provider":
                problems.append(f"{tier} tier did not report provider usage")
            print(f"    {tier}: {result.get('model')} ok={result.get('ok')}")
        answer, stats, error = _ask(url, "What is in a flat white?")
        if error or not answer.strip() or not stats:
            problems.append("normal /ask returned no complete usable answer")
        after = _get(f"{url}/metrics", token)
        if after.get("config") != before.get("config"):
            problems.append("configuration changed during preflight")
        if _get(f"{url}/declarations", token) != declarations:
            problems.append("declarations or hypothesis gate changed during preflight")
    except Exception as exc:
        problems.append(f"preflight could not complete: {type(exc).__name__}")
    return problems


def _service_token(name, project, region):
    """Resolve a service's own secret; never print the credential."""
    raw = subprocess.run(["gcloud", "run", "services", "describe", name,
        f"--project={project}", f"--region={region}", "--format=json"],
        capture_output=True, text=True, check=True)
    env = json.loads(raw.stdout)["spec"]["template"]["spec"]["containers"][0]["env"]
    ref = next(e["valueFrom"]["secretKeyRef"] for e in env if e["name"] == "NIMBUS_ADMIN_TOKEN")
    result = subprocess.run(["gcloud", "secrets", "versions", "access", ref["key"],
        f"--secret={ref['name']}", f"--project={project}"],
        capture_output=True, text=True, check=True)
    return result.stdout.strip()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", help="one service URL")
    ap.add_argument("--all-services", action="store_true",
                    help="check every Cloud Run service whose name starts with nimbus")
    ap.add_argument("--prefix", default="nimbus-team-", help="service prefix for --all-services")
    ap.add_argument("--token", default=os.environ.get("NIMBUS_ADMIN_TOKEN", ""))
    ap.add_argument("--project", default=os.environ.get("GOOGLE_CLOUD_PROJECT", "adsc-nimbus"))
    ap.add_argument("--region", default=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"))
    args = ap.parse_args()

    if args.all_services:
        listing = subprocess.run(
            ["gcloud", "run", "services", "list", f"--project={args.project}",
             f"--region={args.region}", "--format=value(metadata.name,status.url)"],
            capture_output=True, text=True, check=True)
        targets = [tuple(line.split("\t")) for line in listing.stdout.splitlines()
                   if line.startswith(args.prefix)]
        if not targets:
            sys.exit("no nimbus services are deployed.")
    elif args.url:
        targets = [(args.url.rstrip("/").split("//")[-1].split(".")[0], args.url)]
    else:
        ap.error("give --url or --all-services")

    failed = {}
    for name, url in targets:
        print(f"\n  {name}  {url}")
        try:
            token = args.token or (_service_token(name, args.project, args.region) if args.all_services else "")
            problems = check(url.rstrip("/"), token)
        except Exception as exc:
            problems = [f"cannot access service credential: {type(exc).__name__}"]
        if problems:
            failed[name] = problems
            for p in problems:
                print(f"    FAIL      {p}")

    print()
    if failed:
        print(f"NOT READY -- {len(failed)} of {len(targets)} service(s) have problems:")
        for name, problems in failed.items():
            for p in problems:
                print(f"  {name}: {p}")
        sys.exit(1)
    print(f"All {len(targets)} service(s) ready to hand out.")


if __name__ == "__main__":
    main()
