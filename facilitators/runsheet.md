# Nimbus facilitator run sheet

Twenty-minute symptom-first investigation, using predeployed Cloud Run services.
This is for facilitators. Follow [cloud operations](../deploy/README.md) and
[development evidence](../docs/DEVELOPMENT_LOG.md) before handing out URLs.

The whole organiser path is four commands and about twenty minutes, run the day
before. Only the handout assembly grows with the size of the room.

## Deploying the room

One-time: `deploy/cloudrun.env`, created from `cloudrun.env.example`. It is
gitignored and `deploy_incident.py` exits without it.

Dry run first. This prints every service, its incident and the full environment
it would be born with, and deploys nothing:

```bash
python facilitators/deploy_incident.py --all --teams 4 --prefix nimbus-team
```

Then deploy:

```bash
python facilitators/deploy_incident.py --all --teams 4 --prefix nimbus-team --run
```

What runs, in order: source `cloudrun.env`; build **one** image via Cloud Build
(~2-4 min, shared by every team); then per team compute the full environment
(`HEALTHY_ENV` first, the incident's overrides on top, public brief text,
calibrated traffic profile, `min-instances=1`, hypothesis gate), ensure the
team's secret, and deploy (~30-60s each). It ends with a facilitator card
mapping service to incident. That card is the answer key; keep it off the
projector.

Deploy through this script rather than `gcloud run deploy` per team. A service
must be born with its whole incident: deploying only the injection produces a
service that is wrong in a way that looks like nothing at all -- `cheapmodel`
without `MODEL_TIER` ran the large model and the incident was simply absent.
`HEALTHY_ENV` going first is what pins the levers an incident does not mention,
so they cannot inherit deployment defaults. `min-instances=1` matters as much:
identical config measured p95 3.00/12.10/7.87 cold against 1.95/2.03/1.95 warm,
which moved the dominant ledger row from `retrieve` to `generate`. A cold
container invents an incident.

Teams are lettered `-a`, `-b`, `-c`. Add `--rounds` for a round-1 service per
team as well; both rounds share one token.

## Team tokens

Tokens are generated for you. `ensure_team_secret` creates a Secret Manager
secret named `<team>-token`, adds a random `token_urlsafe(32)` value if the
secret has no enabled version, and grants the runtime service account access.
`deploy.sh` injects it as `NIMBUS_ADMIN_TOKEN`.

Tokens are per service and not interchangeable. Team A's token on team B's URL
is a 401.

To choose your own memorable values instead, create the secret **before**
deploying; the script only adds a version when none exists, and still binds the
IAM the service needs:

```bash
printf 'team-a-nimbus-2026' | gcloud secrets create nimbus-team-a-token \
  --data-file=- --replication-policy=automatic --project=adsc-nimbus
```

## Preflight -- before any URL goes out

```bash
python facilitators/preflight.py --all-services --prefix nimbus-team
```

Do not skip this. Per service it checks, with real model calls: `/health` ready
with a built retrieval index; that the configured model is actually reachable
(a service pointed at a model the project cannot reach starts up HEALTHY and
404s every request, because `warm()` validates credentials, not model access);
that a real question returns real text (at low `MAX_TOKENS` Gemini 2.5 spends
the output budget thinking and returns no text at all, while latency and cost
still read fine); that both tiers work (one thinking budget is not always valid
for both, and an out-of-range value is a hard 400 on the tier a team reaches for
as its fix); that no `INCIDENT` key is exposed and that `/metrics` and
`/declarations` return 401 for a missing **and** an invalid token; and that
nothing changed during the check itself.

Every one of those failures presents as a working service. Proceed only on
`All N service(s) ready to hand out.`

## Handout

Read each team's URL and token back:

```bash
gcloud run services describe nimbus-team-a --region=us-central1 \
  --project=adsc-nimbus --format='value(status.url)'
gcloud secrets versions access latest --secret=nimbus-team-a-token \
  --project=adsc-nimbus
```

Send each team **one private message** containing only its own block, with the
credentials already filled in, so nobody types a credential or picks the wrong
block out of a wall of text. Include the URL, the token and nothing about the
incident.

```bash
git clone https://github.com/anh-nguyen28/adsc-workshop.git && cd adsc-workshop
python3 -m venv .participant-venv && .participant-venv/bin/pip install -q httpx==0.28.1
export PATH="$PWD/.participant-venv/bin:$PWD/cli:$PATH"
nimbus init https://nimbus-team-a-xxxx.run.app team-a-nimbus-2026
nimbus brief
```

Cloud Shell is the path of least resistance: git and Python are already there
and it is identical for everyone. No model weights and no Google credentials are
needed; the only dependency is httpx. `NIMBUS_URL` and `NIMBUS_TOKEN` in the
environment work instead of `init` if a team prefers that.

## Before participants arrive

- Deploy one service per team with a validated incident, distinct team token,
  minimum/maximum one instance, and the intended hypothesis gate.
- Complete authenticated preflight and a real warm baseline for each service.
  The current default round-2 catalog is prompt and retrieval.
- Keep the image digest, team/service mapping, traffic profile and recovery
  evidence accessible to facilitators. Do not reveal incident assignments.
- Distribute the participant blocks and quickstart ahead of time, and ask people
  to run the setup paste before the session rather than during it.
- Use the service's /brief targets. Do not quote old 5-second ladder thresholds.
- Test venue connectivity and keep a facilitator terminal ready as a fallback.
  Old generated ladder/eval cards are historical, not current recovery evidence.

## Minute by minute

| Time | Action |
| --- | --- |
| 0–2 | Confirm each team is connected -- `nimbus brief` renders. Explain student impact and the targets. |
| 2–5 | Run baseline. Read outcome counts and the additive p95 request ledger. Change nothing. |
| 5–8 | Diagnose. State the dominant slice or token anomaly and the evidence that rules out alternatives. Record a hypothesis. |
| 8–13 | Change one setting, benchmark with the same profile, and explain the observed difference. Repeat only if evidence supports another change. |
| 13–16 | Run eval on the measured configuration; inspect real answers and recovery status. |
| 16–19 | Compare two teams with different symptoms. Each states evidence, change, resulting user impact and remaining limits. |
| 19–20 | Close with the distinction between latency, availability, modeled cost and answer quality. |

The gate requires an existing hypothesis, not a correct one. Facilitators enforce
one change at a time and ask for evidence rather than prescribing a lever.
Only one member generates a team's load at a time. Do not rebuild images or
change traffic profiles mid-comparison.

## When a team cannot connect

| What they see | Cause | Fix |
| --- | --- | --- |
| `WARNING: /health returned …` | Wrong URL, or service not up | Resend the block; confirm the service |
| `That token was not accepted` | Another team's token | Resend that team's own block |
| `Benchmark needs authenticated /metrics` | Also a wrong token | Same |
| `Run 'nimbus init' first` | Different machine; the config is per machine | Paste the block again |

`nimbus init` validates the URL only -- `/health` and `/brief` take no
authentication, so a wrong token passes setup silently and first fails at
`nimbus baseline`. Treat any `/metrics` complaint as a credential problem, not a
benchmark problem.

Fallback order: pair with a teammate whose terminal works (only one member
should generate load anyway), then the facilitator terminal, then a spare
pre-connected service on the facilitator machine.

## Recovery and fallback

A latency/cost 2/2 is not recovery. Check successful-request rate, quality,
configuration stability and the explicit RECOVERY line. The quality evaluator
is a small keyword proxy; it can miss subtle errors.

If a service restarts, its runtime changes and declarations may be lost. Inspect
status and begin a new baseline/session; do not compare silently against another
configuration. If a model call or authentication fails, use the facilitator
terminal and resolve deployment readiness before asking participants to diagnose.

If time is short, reduce share-out time; do not skip quality or turn failed
measurements into a success claim. Do not use cheapmodel/staleness as a surprise
quality reveal until new measurements support that separation.

The automated cloud rehearsal demonstrates command execution and recovery time.
It does not establish the time a human team needs to reason; retain a human dry
run as an event-readiness check.

## After the session

Delete the secrets as well as the services, or live tokens outlive the services
they belonged to:

```bash
for s in nimbus-team-a nimbus-team-b nimbus-team-c nimbus-team-d; do
  gcloud run services delete $s --region=us-central1 --project=adsc-nimbus --quiet
  gcloud secrets delete ${s}-token --project=adsc-nimbus --quiet
done
```

To rotate a token mid-session, add a version and force a new revision. Cloud Run
injects the secret at instance start, so the running container keeps the old
value until it is replaced:

```bash
printf 'new-value' | gcloud secrets versions add nimbus-team-a-token \
  --data-file=- --project=adsc-nimbus
gcloud run services update nimbus-team-a --region=us-central1 --project=adsc-nimbus
```
