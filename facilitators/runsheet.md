# Nimbus facilitator run sheet

Deployment and room operations for the 20-minute team investigation. Use the
[teaching guide](teaching_guide.md) for concepts, demonstration, and the agent
design discussion. Commands come first; the reasoning behind them is at the end
under [Why it works this way](#why-it-works-this-way).

Prepare the day before and rehearse with the actual deployment.

Everything in the deploy path uses system `python3`. `deploy_incident.py` and
`preflight.py` import only the standard library, so **you do not need `.venv` or
`make setup` to deploy the room.** The virtual environment is only needed to run
a benchmark from this machine yourself.

---

## Before you start

| Check | Command | Expect |
| --- | --- | --- |
| gcloud on the right project | `gcloud config get-value project` | `adsc-nimbus` |
| the env file exists | `ls deploy/cloudrun.env` | the file (gitignored) |
| you are in the repo root | `ls Makefile` | `Makefile` |

`deploy_incident.py` exits immediately without `deploy/cloudrun.env`. If it is
missing, copy `deploy/cloudrun.env.example` and set `GOOGLE_CLOUD_PROJECT` and
`NIMBUS_RUNTIME_SERVICE_ACCOUNT`.

## 1. Dry run — deploys nothing

```bash
python3 facilitators/deploy_incident.py --all --only retrieval --teams 10 \
  --prefix nimbus-team
```

Prints every service and the full environment it would be born with, and deploys
nothing. Read the list before continuing.

**Every team gets `retrieval`.** One fault, one brief, one answer key — so every
team runs the same commands and reads the same kind of evidence, and a
facilitator cannot give the wrong hint to the wrong team.

```
nimbus-team-a  retrieval    nimbus-team-f  retrieval
nimbus-team-b  retrieval    nimbus-team-g  retrieval
nimbus-team-c  retrieval    nimbus-team-h  retrieval
nimbus-team-d  retrieval    nimbus-team-i  retrieval
nimbus-team-e  retrieval    nimbus-team-j  retrieval
```

Drop `--only retrieval` to alternate `prompt` and `retrieval` across teams
instead. Do **not** loop `--incident … --service …` to achieve the same thing:
`deploy_incident.py` builds the image once per invocation, so ten invocations
means ten Cloud Builds. `--only` keeps the single shared build.

`queue` is `round: 1` and is not deployable through `--all`. `--rounds` would add
an extra `-r1` service per team, doubling services and cost; a single-round
20-minute activity does not use it.

**Why `retrieval` and not `prompt`:** `retrieval` fails the latency target
visibly (p95 1.98 s against a 1.50 s SLO in rehearsal), so the service feels
broken and the evidence is in the ledger. `prompt` *passes* latency and fails
only on cost, with `generate` as its largest ledger row even though the prompt is
the fault — subtle, and easy for a first-time team to misread as a model problem.

**Sizing when the headcount is unknown:** deploy more than you need. Unused
services idle, cost roughly $2.30/day each, and double as the spare
pre-connected service the fallback order calls for. Hand out only the blocks you
use. `--teams` accepts up to 26, lettered `-a` onward.

## 2. Deploy

```bash
python3 facilitators/deploy_incident.py --all --only retrieval --teams 10 \
  --prefix nimbus-team --run
```

One shared Cloud Build image (~2–4 min), then ~30–60 s per service — budget
**10–15 minutes for ten teams**. Ends with a facilitator card mapping service to
incident. **That card is the answer key. Keep it off the projector.**

## 3. Preflight — do not skip

```bash
python3 facilitators/preflight.py --all-services --prefix nimbus-team
```

Proceed **only** on `All N service(s) ready to hand out.` If it reports NOT
READY, fix the named service and run it again. Never hand out a URL that has not
passed — every failure this catches presents as a working service. Per service,
with real model calls, it checks:

- `/health` ready with a built retrieval index.
- The configured model is actually reachable. A service pointed at a model the
  project cannot reach starts up HEALTHY and 404s every request, because `warm()`
  validates credentials, not model access.
- A real question returns real text. At low `MAX_TOKENS` a thinking model spends
  the whole output budget thinking and returns no text at all, while latency and
  cost still read fine.
- Both tiers work. One thinking budget is not always valid for both, and an
  out-of-range value is a hard 400 on the tier a team reaches for as its fix.
- No `INCIDENT` key is exposed, and `/metrics` and `/declarations` return 401 for
  a missing **and** an invalid token.
- Nothing changed during the check itself.

## 4. Read back each team's URL and token

```bash
for t in a b c d e f g h i j; do
  echo "== nimbus-team-$t"
  gcloud run services describe nimbus-team-$t --region=us-central1 \
    --project=adsc-nimbus --format='value(status.url)'
  gcloud secrets versions access latest --secret=nimbus-team-$t-token \
    --project=adsc-nimbus
done
```

Tokens are generated for you: `ensure_team_secret` creates a Secret Manager
secret named `<team>-token`, adds a random `token_urlsafe(32)` value if the
secret has no enabled version, and grants the runtime service account access.
`deploy.sh` injects it as `NIMBUS_ADMIN_TOKEN`. Tokens are per service and not
interchangeable — team A's token on team B's URL is a 401.

To choose memorable values instead, create the secret **before** deploying; the
script only adds a version when none exists, and still binds the IAM the service
needs:

```bash
printf 'team-a-nimbus-2026' | gcloud secrets create nimbus-team-a-token \
  --data-file=- --replication-policy=automatic --project=adsc-nimbus
```

## 5. Send one private message per team

Credentials already filled in, so nobody types a credential or picks the wrong
block out of a wall of text. Include the [README](../README.md) as the only
participant guide. **Include no incident assignment or answer key.**

```bash
git clone https://github.com/anh-nguyen28/adsc-workshop.git
cd adsc-workshop
python3 -m venv .participant-venv
.participant-venv/bin/python -m pip install httpx==0.28.1
export PATH="$PWD/.participant-venv/bin:$PWD/cli:$PATH"

nimbus init <THIS TEAM'S URL> <THIS TEAM'S TOKEN>
nimbus brief
```

The activity is five commands, run in order: `benchmark`, `infra`, `monitor`,
`optimize` (repeatable), `guard`. `nimbus status` still works and is the fastest
way to confirm a token, but participants no longer need it to start.

Cloud Shell is the path of least resistance: git and Python are already there and
it is identical for everyone. No model weights and no Google credentials are
needed; the only dependency is `httpx`. `NIMBUS_URL` and `NIMBUS_TOKEN` in the
environment work instead of `init` if a team prefers.

Ask people to run this **before** the session, not during it.

## 6. After the session — delete services AND secrets

Delete both, or live tokens outlive the services they belonged to.

```bash
for t in a b c d e f g h i j; do
  gcloud run services delete nimbus-team-$t --region=us-central1 \
    --project=adsc-nimbus --quiet
  gcloud secrets delete nimbus-team-$t-token --project=adsc-nimbus --quiet
done
```

To rotate a token mid-session, add a version and force a new revision. Cloud Run
injects the secret at instance start, so a running container keeps the old value
until it is replaced:

```bash
printf 'new-value' | gcloud secrets versions add nimbus-team-a-token \
  --data-file=- --project=adsc-nimbus
gcloud run services update nimbus-team-a --region=us-central1 --project=adsc-nimbus
```

---

## What is in scope tomorrow

**One incident: `retrieval`.** Every team investigates this and nothing else.

| | |
| --- | --- |
| What a team's `brief` says | "Slow to START answering. The answer itself reads fine." |
| User impact | "Customers stare at a blank box, then get a good answer." |
| Injected fault | a stage delay on retrieval (`lognormal:400:1800`) |
| Discriminator | `retrieve` dominates the ledger while `generate` and token counts sit at baseline |
| Rehearsed baseline | p95 **1.98 s** against the 1.50 s SLO; cost $786/mo — **fails latency, passes cost** |
| Tempting wrong fix | downgrade the model, or cut `MAX_TOKENS` — both falsifiable in one run, because neither touches the slow stage |
| A correct path | the semantic cache is checked **before** retrieval, so a hit skips the slow dependency (rehearsed: p95 → **1.06 s**) |
| Visible in the browser? | yes — per-stage times appear in the request trace |

The gate requires a hypothesis, not a correct one. Do not prescribe the lever.

Present in the repository, **not** used tomorrow:

| Not used | Why |
| --- | --- |
| `docker-compose.local.yml`, `Dockerfile.local`, `make docker-*` | local Ollama path; tomorrow is cloud-only |
| `archive/participants/` | superseded participant docs |
| `prompt` incident | held back this session; re-enable by dropping `--only` |
| `queue` incident | `round: 1`; needs `--rounds` |
| `decode`, `upstream`, `staleness`, `cheapmodel` | `room_enabled: False` — experimental until failure **and** recovery are verified |
| `calibrate_incidents.py`, `eval_all.py`, `gen_prompts.py` | catalog-authoring tools, not session ops |
| `.devcontainer/`, `.github/workflows/` | dev environment and CI |

## Before participants arrive

- One service per team deployed with a validated incident, distinct token,
  min/max one instance, and the hypothesis gate on.
- Authenticated preflight passed and a real warm baseline taken per service.
- Image digest, team/service mapping, traffic profile and recovery evidence
  accessible to facilitators. Do not reveal incident assignments.
- Team setup blocks and the README distributed ahead of time.
- Use the service's `/brief` targets. Do not quote old ladder thresholds; old
  generated ladder/eval cards are historical, not current recovery evidence.
- Venue connectivity tested and a facilitator terminal ready as a fallback.

## Minute by minute

| Time | Action |
| --- | --- |
| 0–4 | `nimbus brief`, one browser question, then `nimbus benchmark`. Read the two gap bars and the model-tier table. Change nothing. |
| 4–6 | `nimbus infra`. No traffic. Split the bill into tokens and hosting. |
| 6–9 | `nimbus monitor`. No traffic. Name the dominant stage and what the token counts rule out. |
| 9–15 | `nimbus optimize`, two or three times. One setting per run, same traffic profile, prediction before each. |
| 15–18 | `nimbus guard`. Quality on the measured configuration, then the printed scorecard. |
| 18–20 | Read the scorecard aloud: evidence, change, user impact, remaining limits. |

`infra` and `monitor` send no benchmark traffic, so they do not contend for the
service and a lagging team can run them at any time.

These times start at the team investigation. The teaching guide covers the
preceding explanation and the following agent design discussion.

The gate requires an existing hypothesis, not a correct one. Enforce one change
at a time and ask for evidence rather than prescribing a lever. Only one member
generates a team's load at a time. Do not rebuild images or change traffic
profiles mid-comparison.

## When a team cannot connect

| What they see | Cause | Fix |
| --- | --- | --- |
| `WARNING: /health returned …` | wrong URL, or service not up | resend the block; confirm the service |
| `That token was not accepted` | another team's token | resend that team's own block |
| `Benchmark needs authenticated /metrics` | also a wrong token | same |
| `Run 'nimbus init' first` | different machine; config is per machine | paste the block again |
| `set` returns 409 | no hypothesis recorded yet | `nimbus hypothesis` first — the gate is intentional |

`nimbus init` validates the URL only — `/health` and `/brief` take no
authentication, so a wrong token passes setup silently and is detected by
`nimbus status` or `nimbus baseline`. That is why the setup block ends with
`status`. For a `/metrics` complaint, check the URL/token pair first, then
service readiness.

Fallback order: pair with a teammate whose terminal works (only one member should
generate load anyway), then the facilitator terminal, then one of the spare
services from step 1.

## Recovery and fallback

A latency/cost 2/2 is not recovery. Check successful-request rate, quality,
configuration stability and the explicit RECOVERY line. The quality evaluator is
a small keyword proxy; it can miss subtle errors.

If a service restarts, its runtime changes and declarations may be lost. Inspect
status and begin a new baseline/session; do not compare silently against another
configuration. If a model call or authentication fails, use the facilitator
terminal and resolve deployment readiness before asking participants to diagnose.

If time is short, reduce share-out time. Do not skip quality, and do not turn
failed measurements into a success claim.

---

## Why it works this way

**Deploy through the script, not `gcloud run deploy` per team.** A service must
be born with its whole incident. Deploying only the injection produces a service
that is wrong in a way that looks like nothing at all — `cheapmodel` without
`MODEL_TIER` ran the large model and the incident was simply absent. `HEALTHY_ENV`
going first is what pins the levers an incident does not mention, so they cannot
inherit deployment defaults.

**`min-instances=1` matters as much.** Identical configuration measured p95
3.00/12.10/7.87 cold against 1.95/2.03/1.95 warm, which moved the dominant ledger
row from `retrieve` to `generate`. A cold container invents an incident.

**What a deploy actually does, in order:** source `cloudrun.env`; build one image
via Cloud Build, shared by every team; then per team compute the full environment
(`HEALTHY_ENV` first, the incident's overrides on top, public brief text,
calibrated traffic profile, `min-instances=1`, hypothesis gate), ensure the team's
secret, and deploy.

**The automated cloud rehearsal** demonstrates command execution and recovery
time. It does not establish the time a human team needs to reason; keep a human
dry run as an event-readiness check.
