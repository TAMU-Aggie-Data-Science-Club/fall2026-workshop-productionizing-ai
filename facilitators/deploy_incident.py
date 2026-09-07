"""Deploy one team's service, carrying its WHOLE incident. NOT FOR PARTICIPANTS.

An incident's configuration lives in two halves. Some of it is lever-settable
(`MAX_TOKENS`, `SYSTEM_PROMPT`, `MODEL_TIER`...) and some is deploy-only
(`stage delay`, `provider fault`, `thinking budget`, the model behind a tier).
Calibration papers over the difference, because the calibrator applies the lever
half over `/levers` after the service is up.

A real team's service has no such step. It has to be born with both halves, and
deploying only the injection produces services that are wrong in ways that look
like nothing:

    decode      deployed at MAX_TOKENS=32 with Pro + thinking, and answered
                every question with the single word "Hello"
    cheapmodel  deployed without MODEL_TIER, so it ran the LARGE model and the
                incident simply was not there
    staleness   deployed without SEMANTIC_CACHE_THRESHOLD, so it ran at 0.92
                and the incident simply was not there

Usage:
    python facilitators/deploy_incident.py --incident decode --service nimbus-team-a
    python facilitators/deploy_incident.py --incident decode --service nimbus-team-a --run
    python facilitators/deploy_incident.py --all --prefix nimbus-team   # the whole room
"""
import argparse
import json
import os
import pathlib
import shlex
import secrets
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "facilitators"))

from incidents import HEALTHY_ENV, INCIDENTS  # noqa: E402

DEPLOY = ROOT / "deploy" / "deploy.sh"
ENV_FILE = ROOT / "deploy" / "cloudrun.env"


def env_for(incident: str, service: str, require_hypothesis: bool) -> dict:
    """Every variable this service must be born with.

    HEALTHY_ENV first so that an incident which does not mention a lever still
    pins it, rather than inheriting whatever the deployment defaults happen to
    be. The incident's own values go on top.
    """
    spec = INCIDENTS[incident]
    env = {**HEALTHY_ENV, **spec["env"]}
    env["NIMBUS_SERVICE"] = service
    team = service.removesuffix("-r1").removesuffix("-r2")
    env["NIMBUS_ADMIN_SECRET"] = f"{team}-token"
    # The PUBLIC half of the incident travels with the deployment so the service
    # can serve it at /brief. The private truth stays here, with the facilitator.
    # public_title, never title: the internal names give the fault away.
    env["NIMBUS_INCIDENT_TITLE"] = spec["public_title"]
    env["NIMBUS_INCIDENT_BRIEF"] = spec["public_symptom"]
    env["NIMBUS_INCIDENT_IMPACT"] = spec["user_impact"]
    # The load the incident was calibrated under. Without this a participant's
    # benchmark uses scenario defaults and measures a different system than the
    # signature describes.
    traffic = spec["traffic"]
    env["NIMBUS_TRAFFIC_REQUESTS"] = str(traffic["requests"])
    env["NIMBUS_TRAFFIC_RATE"] = str(traffic["rate"])
    env["NIMBUS_TRAFFIC_CONCURRENCY"] = str(traffic["concurrency"])
    # A cold container is slow enough to move the dominant ledger row onto the
    # wrong component, so a team's first benchmark would diagnose the platform
    # instead of the incident.
    env["NIMBUS_MIN_INSTANCES"] = "1"
    env["NIMBUS_REQUIRE_HYPOTHESIS"] = "true" if require_hypothesis else "false"
    return env


def load_environment():
    if not ENV_FILE.exists():
        raise SystemExit("Create deploy/cloudrun.env from the example first.")
    result = subprocess.run(["bash", "-c", 'set -a; source "$1"; env -0',
        "bash", str(ENV_FILE)], capture_output=True, check=True)
    return dict(item.decode().split("=", 1) for item in result.stdout.split(b"\0") if item)


def ensure_team_secret(env):
    project = env["GOOGLE_CLOUD_PROJECT"]
    name = env["NIMBUS_ADMIN_SECRET"]
    base = ["gcloud", "secrets"]
    found = subprocess.run(base + ["describe", name, f"--project={project}"],
                           capture_output=True)
    if found.returncode:
        subprocess.run(base + ["create", name, f"--project={project}",
            "--replication-policy=automatic"], check=True, stdout=subprocess.DEVNULL)
    versions = subprocess.run(base + ["versions", "list", name, f"--project={project}",
        "--filter=state:ENABLED", "--limit=1", "--format=value(name)"],
        capture_output=True, text=True, check=True)
    if not versions.stdout.strip():
        subprocess.run(base + ["versions", "add", name, f"--project={project}",
            "--data-file=-"], input=secrets.token_urlsafe(32).encode(),
            check=True, stdout=subprocess.DEVNULL)
    subprocess.run(base + ["add-iam-policy-binding", name, f"--project={project}",
        f"--member=serviceAccount:{env['NIMBUS_RUNTIME_SERVICE_ACCOUNT']}",
        "--role=roles/secretmanager.secretAccessor", "--condition=None"],
        check=True, stdout=subprocess.DEVNULL)


def build_image(env):
    result = subprocess.run(["bash", str(DEPLOY)], cwd=ROOT,
        env={**env, "NIMBUS_BUILD_ONLY": "1"}, stdout=subprocess.PIPE, text=True)
    # Cloud Build progress remains on stderr. Only the digest is machine-read.
    if result.returncode:
        raise SystemExit("Image build failed; no team services deployed.")
    image = next((line.partition("=")[2] for line in result.stdout.splitlines()
                  if line.startswith("NIMBUS_IMAGE=")), None)
    if not image or "@sha256:" not in image:
        raise SystemExit("Build did not return an immutable image digest.")
    return image


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--incident", help="one incident from the catalog")
    ap.add_argument("--service", help="Cloud Run service name")
    ap.add_argument("--all", action="store_true",
                    help="deploy every round-2 incident, one service each")
    ap.add_argument("--rounds", action="store_true",
                    help="with --all: also deploy a round-1 service per team, "
                         "so the switch is a URL handout rather than a redeploy")
    ap.add_argument("--teams", type=int, default=0,
                    help="with --all: number of teams (default: one per "
                         "round-2 incident, duplicating incidents if more)")
    ap.add_argument("--prefix", default="nimbus-team",
                    help="service name prefix when using --all")
    ap.add_argument("--no-gate", action="store_true",
                    help="leave the diagnose-first gate off (round 1)")
    ap.add_argument("--include-experimental", action="store_true",
                    help="allow incidents without a verified room recovery path")
    ap.add_argument("--run", action="store_true",
                    help="actually deploy; otherwise print the command")
    args = ap.parse_args()

    if args.all:
        names = sorted(n for n, s in INCIDENTS.items() if s.get("round") == 2
                       and (args.include_experimental or s.get("room_enabled", True)))
        count = args.teams or len(names)
        # More teams than incidents means duplicates, which is fine: neighbours
        # having different faults is what matters, not every fault being unique.
        assigned = [names[i % len(names)] for i in range(count)]
        targets = []
        for i, incident in enumerate(assigned):
            team = f"{args.prefix}-{chr(ord('a') + i)}"
            if args.rounds:
                # Round 1 is a shared capacity incident and is entirely
                # lever-settable. Round 2 incidents carry deploy-time injection
                # that fires from container start, so one service cannot serve
                # both cleanly -- and a redeploy costs minutes the activity does
                # not have. Two services per team, handed out in turn.
                targets.append(("queue", f"{team}-r1"))
            targets.append((incident, f"{team}-r2" if args.rounds else team))
    elif args.incident and args.service:
        targets = [(args.incident, args.service)]
    else:
        ap.error("give --incident and --service, or --all")

    unknown = [n for n, _ in targets if n not in INCIDENTS]
    if unknown:
        sys.exit(f"unknown incident(s): {', '.join(unknown)}; "
                 f"have {', '.join(sorted(INCIDENTS))}")

    if args.teams < 0 or args.teams > 26:
        ap.error("--teams must be between 0 and 26")
    experimental = [name for name, _ in targets if not INCIDENTS[name].get("room_enabled", True)]
    if experimental and not args.include_experimental:
        ap.error("Incidents need recovery validation: " + ", ".join(experimental) +
                 ". Use --include-experimental only for facilitator validation.")
    base_env = load_environment() if args.run else {}
    image = build_image(base_env) if args.run else None
    card = []
    for index, (incident, service) in enumerate(targets):
        # Round 1 teaches everyone to read the panel on the same fault, so the
        # diagnose-first gate stays off. Round 2 is where committing to a
        # diagnosis before changing anything is the point.
        gate = (not args.no_gate) and not service.endswith("-r1")
        env = env_for(incident, service, gate)
        assignment = " ".join(f"{k}={shlex.quote(v)}" for k, v in sorted(env.items()))
        command = f"set -a; source {shlex.quote(str(ENV_FILE))}; set +a; {assignment} bash {shlex.quote(str(DEPLOY))}"

        print(f"\n=== {service}  <-  {incident} ===", flush=True)
        for key in sorted(env):
            print(f"  {key}={env[key]}")

        if args.run:
            step_env = {**base_env, **env, "NIMBUS_IMAGE": image}
            ensure_team_secret(step_env)
            result = subprocess.run(["bash", str(DEPLOY)], cwd=ROOT, env=step_env)
            if result.returncode != 0:
                sys.exit(f"{service}: deploy failed ({result.returncode})")
        else:
            print(f"\n  to deploy:\n    {command}")
        card.append((service, incident))

    if args.run and card:
        print("\n=== FACILITATOR CARD -- do not show participants ===")
        for service, incident in card:
            gate = "  gate OFF" if args.no_gate or service.endswith("-r1") else "  gate ON"
            print(f"  {service:<22} {incident:<12} "
                  f"{INCIDENTS[incident]['title']}{gate}")
        print("\nEach team's token is in its own <team>-token Secret Manager secret.")
        print(f"Shared immutable image: {image}")



if __name__ == "__main__":
    main()
