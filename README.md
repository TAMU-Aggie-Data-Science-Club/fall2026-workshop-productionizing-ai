# Nimbus Workshop

Nimbus is a small retrieval-augmented study assistant used for a hands-on
incident-investigation exercise about latency, cost, quality, and capacity.

**The activity is symptom-first.** Each team is paged to a different fault on
their own Cloud Run service, sees it only as numbers against a target, and has
to attribute the time before the system will let them change anything.

The design is [`DEV_PLAN.md`](DEV_PLAN.md); where the work actually stands is
[`BUILD_STATUS.md`](BUILD_STATUS.md).

## Choose a path

| Who | Start here | What you need |
| --- | --- | --- |
| **Participant in the session** | [`participant-quickstart.md`](participant-quickstart.md) | A terminal, plus a URL and team token from the facilitator |
| Facilitator deploying the room | [`deploy/README.md`](deploy/README.md) and `facilitators/deploy_incident.py` | Google Cloud project and permissions |
| Facilitator running the session | [`facilitators/runsheet.md`](facilitators/runsheet.md) | The deployed room, preflighted |
| Facilitator benchmarking Cloud Run | [`02_benchmark/README.md`](02_benchmark/README.md) | A prepared checkout and admin token |
| Anyone running it locally | [`participant-preflight.md`](participant-preflight.md) | Docker Desktop, 8 GB RAM, about 8 GB disk |

The detailed local service guide is [`01_deploy/README.md`](01_deploy/README.md).
Contributor and pull-request checks are in [`CONTRIBUTING.md`](CONTRIBUTING.md).

> **Facilitator materials are not for participants.** `facilitators/` holds the
> incident catalog and the answer key. A participant with the repository checked
> out can read `01_deploy/incident.py` and learn that a retrieval delay is
> *possible*; nothing there tells them whether theirs is one.

## What the workshop teaches

Each team is paged to a **different** fault on **their own** service. They see
it only as numbers against a target, must commit to a diagnosis before the
system will let them change anything, and then prove the fix worked.

The loop is: **measure → attribute → commit to a diagnosis → change one thing →
measure again.**

The report names the largest contributor to latency. It deliberately never
names the lever that fixes it — that part is the exercise. The distinctions it
exists to make visible are:

- High **app queue wait** means requests are waiting for capacity.
- High **generate** means each request is doing too much model work.
- High **retrieve** means a dependency is degraded, not the model.
- **Token counts** separate a fat prompt from a slow model, and unlike
  per-token rates they do not move with load.
- Green latency and cost with **bad answers** is its own failure, and only the
  quality eval sees it.

## Architecture

```text
participant terminal  (cli/nimbus)          participant browser
        │  brief · baseline · diagnose              │
        │  hypothesis · set · bench                 │
        └───────────────┬───────────────────────────┘
                        ▼
        nimbus-team-<id>   one Cloud Run service per team
                        │
   shed → queue → cache → retrieve → assemble → generate
                        │            ▲
                        │            └── incident.py injects the fault here,
                        │                INSIDE the timing context
                        ▼
        Vertex AI · gemini-2.5-flash / -flash-lite / -pro
```

The FastAPI service is the proxy. It keeps model credentials out of the browser,
retrieves course notes, controls admission, records metrics, and streams
answers. A second API gateway is not required for a 10–20 participant workshop.

**Latency is additive, and the report shows the addends.** Every row is a slice
of the same wall clock and the rows sum to the reported end-to-end number; a
residual that does not sum is a missing instrument, not rounding. The split that
matters most is **queue wait versus compute** — an overloaded queue and a slow
model look identical from outside and have opposite fixes.

**Two speeds, deliberately.** `nimbus set` applies a lever in-process in about a
second. Capacity changes require a new revision at ~25–40s. Which lever belongs
to which speed is a teaching decision: the slow path holds exactly the levers
participants should reach for last.

**One service per team.** Own incident, own token, own queue, own caches, own
revision history. Shared, every table's load lands in every other table's
numbers.

## Cloud Run quick start

This is the path the session runs on.

### For participants

Participants get a **URL and a team token** from the facilitator and drive the
investigation from the `nimbus` CLI. See
[`participant-quickstart.md`](participant-quickstart.md).

```bash
nimbus init <url> <token>   # point this terminal at your team's service
nimbus brief                # what was reported, and the targets to hit
nimbus baseline             # measure, change nothing
nimbus diagnose             # read the last run back
nimbus hypothesis ...       # record what you think is wrong
nimbus set KEY=VALUE        # change one setting on the running service (~1s)
nimbus bench                # measure again
nimbus status               # what the service is configured with
```

`POST /levers` returns **`409 diagnose first`** until a hypothesis is on record,
when the service is deployed with `NIMBUS_REQUIRE_HYPOTHESIS=true`. That gate is
what makes "diagnose before you change anything" a property of the system rather
than a facilitator walking the room.

The browser UI at `/` is the "what is this thing" view — it renders the request
trace, retrieved note excerpts, and the queue-wait versus compute split.
Participants never receive the admin token for a service they do not own.

### For the facilitator

Each team gets **its own Cloud Run service**, carrying its own incident, token,
queue, caches and revision history. One shared service means every table
measures every other table's load.

1. Ask the cloud owner for the project ID, region, runtime service account,
   model access, and the `nimbus-admin-token` Secret Manager secret.
2. Copy and fill the deployment variables:

   ```bash
   cp deploy/cloudrun.env.example deploy/cloudrun.env
   # edit deploy/cloudrun.env; do not commit it
   source deploy/cloudrun.env
   ```

3. Deploy one service per incident. A service must be **born with its whole
   incident** — deploying only the injection produces services that are wrong in
   ways that look like nothing at all:

   ```bash
   # the whole room, one service per team
   python facilitators/deploy_incident.py --all --prefix nimbus-team

   # or a single team
   python facilitators/deploy_incident.py --incident retrieval --service nimbus-team-a
   ```

   `deploy/deploy.sh` builds the image once and reuses it when the tree is
   clean. **Never rebuild during a session** — `--update-env-vars` on an
   existing image is ~30s, `--source` is 2–4 minutes and will end the activity.

4. Confirm every service *before* URLs go out. `/health` alone is not
   confirmation — a service pointed at a model the project cannot reach starts
   up healthy and 404s every request:

   ```bash
   python facilitators/preflight.py --all-services
   ```

`min-instances=1` is required per service. A cold container is slow enough to
move the largest row of the report onto the wrong component, so a team's first
benchmark would diagnose the platform instead of the incident.

Cloud mode uses ADC from the Cloud Run runtime service account; no API key or
service-account JSON file belongs in this repository.

The adapter speaks three API styles (`gemini`, `mistral`, `openai`) and this
project uses **`gemini`**. The two routing tiers are
`gemini-2.5-flash` (large) and `gemini-2.5-flash-lite` (small); `gemini-2.5-pro`
is used by the decode incident only.

> **Mistral is not available on this project.** `mistral-small-2503`, `-2506`
> and `mistral-nemo-2407` all return HTTP 404 in `us-central1` *and* `global`
> — Model Garden access was never granted. Verified by direct API call. The
> Mistral price entry in [`scenario.json`](scenario.json) is retained for
> reference and marked retired.

`NIMBUS_GEMINI_THINKING_BUDGET=0` is mandatory and `deploy.sh` forwards it
explicitly. Gemini 2.5 spends the *output* token budget thinking before it
answers, so at the workshop's `MAX_TOKENS=32` it returns **no text at all**
while latency and cost still read as healthy.

Token prices were verified against the Gemini pricing page on 2026-09-04 and
are tracked as auditable assumptions in [`scenario.json`](scenario.json).
Recheck them before the event.

## Local-first Docker quick start

Run and benchmark the complete application locally before deploying anything
to Cloud Run. Docker Compose starts the Ollama model server, pulls the default
free-to-run Llama 3.1 8B weights into a persistent volume, builds the retrieval
index, and starts Nimbus. No Google credentials are used.

From `adsc-workshop/`:

```bash
make docker-up
curl -fsS http://127.0.0.1:8000/health
make docker-bench
```

The first `make docker-up` can take several minutes because it downloads the
roughly 8B-class model. Subsequent app rebuilds reuse the `ollama-models`
volume. Stop the stack with:

```bash
make docker-down
```

The default uses `llama3.1:8b` for both routing tiers to avoid downloading two
large models. You can choose separate Ollama-compatible models, including a
larger 12B–14B-class model when the machine has enough RAM:

```bash
NIMBUS_OLLAMA_MODEL_SMALL=llama3.1:8b \
NIMBUS_OLLAMA_MODEL_LARGE=your-12b-or-14b-model \
make docker-up
```

The Llama weights are free to run locally under Meta's Llama license. Review
that license and the selected model's terms before redistribution or hosted
commercial use. CPU-only Docker works everywhere; supported Linux hosts can
also use an accelerator through Ollama. On macOS, use Docker for the
CPU-compatible path or run Ollama natively if you need Apple GPU acceleration.

The benchmark runs inside the Nimbus container and writes its JSON results to
the repository's `results/` directory:

```bash
make docker-bench ARGS="--requests 4 --concurrency 1"
```

## Local Python quick start

The offline path. Useful for developing on the repository and for the original
optimization activity, but **it is not what the session runs** — it uses the
lightweight SmolLM2 tiers rather than Gemini, so its latency numbers describe a
different system.

```bash
make setup       # create .venv, install dependencies, build the note index
make serve       # start the service on http://127.0.0.1:8000
```

In another terminal:

```bash
curl -N -X POST http://127.0.0.1:8000/ask \
  -H 'Content-Type: application/json' \
  -d '{"question":"What is Big-O notation?"}'
```

The response is Server-Sent Events. It contains safe `trace` events describing
the request path, answer deltas, a final `stats` event, and `[DONE]`. The
browser UI at `/` renders the same trace, including retrieved note excerpts
and the queue-wait versus compute split, so participants can see how the
deployed assistant works without exposing private model reasoning.

Run the benchmark:

```bash
make bench
```

This path uses the lightweight SmolLM2 Hugging Face tiers. Use the Docker path
above for the local 8B–14B-class Llama setup, or Cloud Run for the real thing.

> Note: `scenario.json` records its measured baselines as `_backend: "google"`.
> Token comparators printed against a *local* run are therefore comparing across
> backends, and the report does not currently say so.

Change one setting in `01_deploy/config.py`, reload, and measure again. The
Docker stack mounts this control file, so no image rebuild is needed for a
configuration lever:

```bash
make docker-reload
make docker-bench ARGS="--label 'trimmed prompt'"
```

For the Python-local path:

```bash
make reload
make bench ARGS="--label 'trimmed prompt'"
```

For a Cloud Run benchmark, export `NIMBUS_URL` and `NIMBUS_ADMIN_TOKEN` first.
The token is used only for protected `/metrics` and `/reload`; it is not sent
to participant `/ask` requests or written to benchmark results.

## API reference

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| `GET` | `/` | None | Participant browser UI |
| `GET` | `/health` | None | Readiness/liveness check |
| `GET` | `/brief` | None | The incident's public symptom, targets, and the traffic profile it was calibrated under |
| `POST` | `/ask` | None | Stream an answer as SSE |
| `POST` | `/hypothesis` | Team token | Record a diagnosis. Deliberately not graded |
| `POST` | `/levers` | Team token | Change a setting on the running service (~1s). `409` until a hypothesis exists |
| `GET` | `/declarations` | Team token | Hypotheses and lever changes recorded so far |
| `GET` | `/metrics` | Admin header in cloud mode | Read config and counters |
| `POST` | `/reload` | Admin header in cloud mode | Re-read the container's `config.py` and clear caches |

`/brief` carries the **symptom only**. The cause is never served by the
application, and `NIMBUS_INCIDENT*` values must not appear in `/metrics`,
`/health`, a trace event, an error message or the browser bundle — one leak
turns an investigation into a lookup.

`/reload` re-reads the *container's* `config.py`, which a participant cannot
edit, so on Cloud Run it can never apply their change. `/levers` takes the value
from the request instead. That is the difference between the two.

Cloud admin calls use:

```text
X-Nimbus-Admin-Token: <secret value>
```

## Configuration

Local participants edit `01_deploy/config.py`. Cloud deployments use the same
source defaults plus `NIMBUS_*` environment overrides, and in a session teams
change them at runtime with `nimbus set` (`POST /levers`), which is validated
against one allow-list in `config.LEVERS`.

| Lever | Effect |
| --- | --- |
| `RESPONSE_CACHE` | Exact-match cache of finished answers. A hit costs nothing at all |
| `PREFIX_CACHE` | Reuse of the static prompt block. Discounts *input* only; generation still bills |
| `SEMANTIC_CACHE` | Matches re-phrasings by embedding similarity. A hit costs nothing |
| `SEMANTIC_CACHE_THRESHOLD` | Similarity above which two questions count as the same. Lower = more hits, more wrong answers |
| `MAX_TOKENS` | Caps generated output, and so both latency and cost |
| `SYSTEM_PROMPT` | `LONG`, `TRIMMED`, or `VERBOSE` instructions |
| `RETRIEVE_K` | How many note chunks enter the prompt |
| `ROUTE_EASY` | Send easy questions to the small tier |
| `MODEL_TIER` | `large` or `small`. `small` makes latency and cost look fantastic — check the eval before shipping it |
| `MAX_CONCURRENT` | How many requests may compute at once. The rest wait, and that wait is what `app queue wait` measures |
| `SHED_ABOVE_QUEUE` | Return `429` once the queue is deeper than this |

Capacity levers are deploy-time, not runtime: `NIMBUS_MIN_INSTANCES`,
`NIMBUS_MAX_INSTANCES`, Cloud Run `--concurrency`, CPU and memory. Making them
visibly slower than a lever change is honest — they are the class of fix the
activity wants participants to reach for *last*.

**`MAX_CONCURRENT` must stay below the benchmark's concurrency.** If they match,
nothing ever queues, `app queue wait` reads 0.00s, and the capacity incident
disappears with no error at all.

`REPLICAS` is only a local workshop simulation. Cloud Run instance count must be
set at deployment and then verified by measurement.

## Troubleshooting

- `make serve` fails because the port is busy: run `make serve PORT=8001`.
- `make bench` reports zero successes: check `curl .../health`, the URL, and
  whether the service finished startup. A run with no successes must never
  score a PASS — percentiles over an empty list are 0.0, and `0.0 <= SLO`.
- Cloud `/metrics` or `/reload` returns `401`: export the correct
  `NIMBUS_ADMIN_TOKEN` in the facilitator terminal.
- `nimbus set` returns `409 diagnose first`: that is the gate working. Record a
  hypothesis first.
- Cloud startup fails: verify the runtime service account has Vertex AI access,
  the model is enabled in the selected region, and `GOOGLE_CLOUD_PROJECT` and
  `GOOGLE_CLOUD_LOCATION` are correct.
- **The service is healthy but every answer is empty**: the thinking budget.
  Gemini 2.5 spends the output budget thinking before it answers; at
  `MAX_TOKENS=32` it returns `finishReason=MAX_TOKENS` with no text parts while
  latency and cost still read as fine. `preflight.py` checks for exactly this.
- Cost is shown as `UNKNOWN`: the streaming provider did not return token usage,
  or the selected model has no price entry in `scenario.json`. Do not treat
  missing usage as zero cost.
- **Latency numbers look wrong by ~2x**: something else was running on the
  machine, or the container was cold. Both have produced wrong answer keys on
  this project. Warm the service and measure with nothing else running.

## Before a session

Latency is hardware- and region-dependent; cost is not. Re-derive the SLO in
`scenario.json` from several warm runs on the deployment the session will
actually use, then preflight every service before URLs go out.

`facilitators/eval_card.md`, `facilitators/answer_key.md` and
`facilitators/signatures.json` are **generated from measurement** — never
hand-edit them.
