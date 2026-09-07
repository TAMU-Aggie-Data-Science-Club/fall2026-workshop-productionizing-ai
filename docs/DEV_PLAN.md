# Nimbus Workshop — Development Plan

**Symptom-first incident investigation, running entirely on Google Cloud.**

Status: proposal · Target: ADSC session, 20-minute activity slot, 10–20 participants
Supersedes the rung-ladder framing in `service/config.py` and `benchmark/decision_sheet.md`.

---

## 0. The change in one paragraph

Today the activity hands participants a config file with the remediation ladder printed in it
(`RUNG 2 · IMPROVE EFFICIENCY`, `RUNG 5 · ADD CAPACITY`), a single fault that is the same for
every table, and a report that ends with the sentence `hint queue wait exceeds compute. The model
is not your problem.` Nobody diagnoses anything — they walk a menu. The redesign turns it into an
investigation: participants see a **symptom expressed as numbers against a target**, are given
**enough white-box evidence to attribute the time**, and must **commit to a diagnosis before the
system will let them change anything**. Different teams get different faults, so the answer cannot
be copied from the next table.

> **Not this:** "The LLM is slow. Enable caching."
> **This:** "p95 latency is 10.1s against a 5.0s target. Determine whether the time is spent
> waiting, retrieving, or generating."

---

## 0.1 Revisions from implementation

Recorded as they were found. Each of these changed the design, and each was
caught by running the thing rather than by reading it.

| # | Change | Why |
|---|---|---|
| R1 | **Inter-token latency dropped as a signal.** INC-04's discriminator is now output token **count**. | Measured 115 ms/tok idle and 375 ms/tok under load. Every per-token *rate* inflates with contention, so a busy queue and a slow model give the same reading — recreating the exact confusion the ledger exists to remove. A token *count* is load-independent. Strictly better discriminator. |
| R2 | **Baselines must be calibrated under the same traffic profile they are compared against.** | Same cause as R1. A baseline taken on an idle server makes every loaded run look anomalous. |
| R3 | **The ledger has two columns**, `p95 req` (decomposition of the p95-ranked request, sums exactly) and `p95 each` (per-stage p95, does not sum). | Percentiles of parts do not sum to the percentile of the whole, so a single per-stage-p95 column could never satisfy this plan's own "rows must sum" criterion. When the columns disagree, different requests are slow for different reasons — itself INC-05's signature. |
| R4 | **Incident definitions split in two:** mechanism in `service/incident.py`, catalog in `facilitators/incidents.py`, values delivered as deploy-time env vars. | A participant with the repo checked out could otherwise read their own answer. The mechanism file tells you a retrieval delay is *possible*, never that yours is one. |
| R5 | **Per-incident traffic profiles** (`_SURGE` for queue, `_CALM` for the rest) instead of raising `MAX_CONCURRENT` on non-queue incidents. | Raising `MAX_CONCURRENT` to 8 on a 4-core box does not create capacity, it relocates waiting from the queue into generation. Every non-queue incident measured **96% "generate"** and the panel would have blamed the model in all of them. Offering traffic *at* the admission limit leaves both the queue empty and the cores uncontended. |
| R6 | **Explicit `HEALTHY_ENV` reference measurement**, not the shipped default. | The shipped default already carries the 1,200-token system prompt, so INC-03 measured only **1.5×** the baseline token count instead of the 5–6× a participant needs to see. |
| R7 | **Injected retrieval delay raised from p50 400ms/p95 1.8s to p50 2s/p95 8s.** | At 1.8s it was 4% of the latency budget against a multi-second generation, so `retrieve` never became the dominant row. The *ratio* is what has to be realistic, and a badly degraded vector store is why you got paged. |
| R8 | **New script `facilitators/calibrate_incidents.py`** rather than extending `calibrate.py`. | Injection is configured by environment variable, so each incident needs its own server process; the rung ladder uses `/reload` on one long-lived process. Different lifecycles, different scripts. `calibrate.py` keeps doing the ladder. |
| R9 | **Calibrator also checks each incident "presents as advertised"**, not only that pairs are distinguishable. | A collision check proves two incidents differ; it does not prove either one presents correctly. This check is what caught R5, R6 and R7. |
| R10 | **INC-05 `upstream` is not producible on the `local` backend.** | The fault is raised inside the HTTP adapters' real retry loops so it exercises the true code path. The in-process backend has no retry loop. The calibrator skips it and says so. |
| R11 | **Rung language stripped from `app.py` and `levers.py` too**, not just `config.py`. | Seven comments in those two files still named the ladder by rung number, so stripping `config.py` alone did not achieve the intent. |
| R12 | **Mistral is unavailable on this project; the workshop moves to Gemini.** `mistral-small-2503`, `-2506` and `mistral-nemo-2407` all return HTTP 404 in `us-central1` *and* `global`. | Model Garden access was never granted. Verified by direct API call, not by reading docs. The Gemini adapter is therefore promoted from Phase 4 to a **blocker for all cloud work**. |
| R13 | **Gemini added as a third API style inside `cloud_model.py`**, not a separate module as the plan said. | The module already branches on `_api_style()` for endpoint, body, content and usage. Extending that switch reuses one auth path, one retry loop and one incident hook; a parallel module would have duplicated all three. |
| R14 | **`thinkingConfig.thinkingBudget = 0` is mandatory, and forwarded explicitly by `deploy.sh`.** | Gemini 2.5 spends the *output* token budget thinking before it answers. At `MAX_TOKENS=32` it returned `finishReason=MAX_TOKENS` with **zero text parts** and `thoughtsTokenCount=29` — every answer empty while latency and cost read as healthy. An INC-SILENT-shaped failure baked into the shipped default. `"none"` omits the field, which `gemini-2.5-pro` requires. |
| R15 | **Thinking tokens are added to `tokens_out`.** | They bill at the output rate. Charging only visible tokens understated the bill ~3x and made the cost verdict fiction. Kept separately as `tokens_thinking`. |
| R16 | **Gemini's partial `usageMetadata` must not be treated as usage.** | Every streamed chunk carries a `usageMetadata` object but only the last carries counts; the rest hold `{"trafficType": ...}`, which is truthy. The naive check overwrote real counts with zeros and reported the run as free. Keyed off `promptTokenCount`. |
| R17 | **`deploy.sh` stopped forwarding a defaulted `NIMBUS_GOOGLE_MODEL_ID`.** | It defaulted to a Mistral id and always exported it. Since `_model_id()` gives that variable priority over the per-tier ones, it pinned BOTH tiers to one model — silently collapsing the routing lever, and 404ing every request on this project. Now forwarded only when explicitly set. |
| R18 | **`--set-env-vars` uses the `^@^` delimiter.** | The incident stage-delay spec is itself comma-separated for multi-stage degradation, which a comma-delimited env string cannot carry. |
| R19 | **All latency-shaped calibration from Phase 1 is void for cloud.** | Managed Gemini answers in ~0.5s (TTFT 0.40s lite / 0.62s flash) where the local SmolLM tiers took 4–7s. The 5.0s SLO is now trivially met, `MAX_CONCURRENT=2` barely queues, and the 2s/8s retrieval injection would utterly dominate. Token counts and budget shares transfer; milliseconds do not. **The SLO in `scenario.json` must be re-derived on the deployed service.** |

---

## 1. Design principles

These are the non-negotiables. Everything downstream is subordinate to them.

**P1 · Symptom public, cause private.** Every incident has a *public symptom* (what a user or an
alert would report) and a *private truth* (what actually broke). Participants get the symptom and
the instruments. They never get the cause, and it must not be recoverable from the repo,
`/metrics`, `/health`, an error message, or the browser bundle.

**P2 · The instrument must be able to exonerate the model.** The current report can only accuse it:
`compute` is an undifferentiated blob and, because retrieval is a sub-millisecond numpy dot
product, compute *is* generation by construction. Until the panel can attribute time to retrieval,
assembly, generation, provider retries and Cloud Run queueing separately, "is it the LLM?" has no
second answer and the question is theatre.

**P3 · Latency is additive — show the addends.** Every latency row is a slice of the same wall
clock and the rows must sum to the reported end-to-end number. A residual that doesn't sum is a
missing instrument, not rounding.

**P4 · The report names the dominant slice. It never names the fix.** Naming the dominant
contributor enforces measurement. Naming the lever ends the exercise.

**P5 · Diagnosis is enforced by the system, not by facilitators walking the room.** A lever change
is rejected until a hypothesis is on record.

**P6 · Every incident needs a unique discriminator.** If two incidents move the same signals by
the same magnitudes, the diagnosis is a coin flip and the room correctly learns that diagnosis
doesn't work. Checked by column against *generated* calibration data, never by authoring intent.

**P6a · And every incident must present as advertised.** Distinguishable is not the same as
correct: an incident whose dominant ledger row points at the wrong component teaches the opposite
of its lesson. Both properties are asserted by the calibrator and both are build failures.

**P6b · Prefer counts to rates.** A rate (ms per token, requests per second) moves with system
load; a count (input tokens, output tokens, retries) does not. Where a count and a rate would both
serve as a discriminator, the count is the one that survives being measured on a busy server.

**P7 · Sometimes it really is the model.** At least one incident must be genuinely
generation-bound. Otherwise "always blame something else" becomes the winning strategy, which is
the same reflex the activity exists to break, pointed the other way.

**P8 · The four golden signals organise the panel.** Traffic, latency, errors, saturation
(Google SRE). Symptom-level metrics answer *what is broken*; white-box metrics answer *why*. Both
must be present and visibly distinct.

---

## 2. Current state

### 2.1 What already works and must be preserved

| Asset | File | Why it stays |
|---|---|---|
| Queue-vs-compute split | `service/timing.py` | The one measurement the whole activity turns on |
| Per-stage stopwatch | `timing.py` `stage()` | Already records retrieve/assemble/cache/generate |
| Streamed operational trace | `service/app.py` `_trace()` | Safe, participant-visible request path |
| Poisson arrival load model | `benchmark/run.py` `drive()` | `--rate` and `--concurrency` correctly separated |
| PASS/FAIL verdict | `benchmark/report.py` `render()` | Turns measurement into a game with a win condition |
| Frozen constraints | `scenario.json` | SLO 5.0s · $1,500/mo · 80% quality |
| Duplicate-bearing corpus | `benchmark/prompts.jsonl` | Repeating template survives truncation — cache levers have something real to hit |
| Quality harness | `facilitators/eval.py`, `eval_all.py` | Two-tier (extraction / reasoning) split is load-bearing |
| Empty-run guard | `report.py:138` | A run with zero successes must never PASS |
| Marginal-result honesty | `report.py:146` | ±15% of a threshold is flagged, not claimed |

Calibration already proves the incidents are distinguishable in principle:

- Queue-dominated: p95 25.19s, queue 18.01s, compute 7.41s
- After routing: p95 3.29s, queue 1.94s, compute 1.53s
- Small-model trap: quality 77.8% against an 80% bar

### 2.2 What blocks the redesign

| # | Blocker | Evidence |
|---|---|---|
| B1 | Per-stage timings are measured, streamed, then discarded | `app.py:324` emits `stages_ms` → `run.py:87–102` result row omits it → `report.py:182–189` renders queue + compute only |
| B2 | Inter-token latency is recorded and never rendered | `run.py:91` writes `itl_ms`; no reader anywhere |
| B3 | Compute ≡ generation by construction | `retrieval.py:21–52` is one dot product on <1MB; no I/O between admission and `generate()` |
| B4 | The config file is the answer key | `config.py:26–124`, levers grouped and labelled by the rung that fixes them |
| B5 | The participant loop does not close on Cloud Run | `app.py:157` `importlib.reload(config)` re-reads the *container's* file; documented cloud path is env overrides + redeploy |
| B6 | One shared service means every table measures every other table | `deploy/README.md:53` (1 vCPU, concurrency 2, max-instances 1); `app.py:169–172` `/reload` resets semaphore, caches and counters globally |
| B7 | Results are written to an ephemeral filesystem | `run.py:190–196` writes `results/run-N.json`; `report.py:152` reads `run-{N-1}.json` for the before/after. Cloud Run's filesystem is in-memory and vanishes with the instance |
| B8 | Three levers change meaning or become fiction in cloud mode | `MAX_CONCURRENT` (CPU admission → network fan-out), `PREFIX_CACHE` (no local KV cache against a managed endpoint), `REPLICAS` (documented as "only a local workshop simulation") |
| B9 | App queue wait is conflated with Cloud Run's own pending queue | Nothing measures the gap between Cloud Run request latency and app-reported total — which is exactly where cold start and instance scaling live |
| B10 | The report hands over the diagnosis | `report.py:229–232` `hint queue wait exceeds compute. The model is not your problem.` |

---

## 3. Target architecture

### 3.1 Component map

```
Participant Cloud Shell
        │
        ├── nimbus brief / baseline / set / deploy / benchmark / diagnose
        │
        ├──── runtime lever change ────────────┐
        └──── trigger benchmark ───┐           │
                                   ▼           ▼
                     Cloud Run Job          Participant Nimbus service
                     nimbus-bench           nimbus-team-<id>
                     (load generator)  ───▶  shed → queue → cache →
                            │                retrieve → assemble → generate
                            │                       │
                            │                       ▼
                            │                Vertex AI model endpoints
                            │                Gemini · Mistral · Gemma
                            │                       │
                            ▼                       ▼
                  Firestore run store        Cloud Logging / Monitoring
                  (durable run summaries)    (revision, instances, cold starts,
                            │                 4xx/5xx, quota events)
                            ▼
                  Nimbus UI  +  facilitator board
```

**Why Cloud Run Jobs for the benchmark.** It is a batch task that exits when finished and exposes
per-execution logs. Three concrete wins over the alternatives:

- It does **not** run in the participant's Cloud Shell VM, which is a small shared instance whose
  CPU contention would corrupt every latency number.
- It does **not** run inside the Nimbus container, so the load generator never competes with the
  service it is measuring.
- Its execution ID becomes the natural key for the run record.

**Why Firestore.** Cloud Run's filesystem is in-memory and disappears when the instance stops
(B7). The before/after comparison — the thing that makes a lever change legible — needs the
previous run to still exist. Firestore holds sanitized run summaries; Cloud Storage optionally
holds raw per-request artifacts. Neither stores raw student questions or any secret.

### 3.2 The two-speed control loop

This is the single most important timing decision in the plan. A full Cloud Run deploy inside a
six-minute investigation round is fatal, and a workshop where nothing is ever deployed loses the
"you shipped a revision" moment. So there are two speeds, and which lever belongs to which is a
teaching decision, not an implementation convenience.

| Speed | Command | Mechanism | Latency | Levers |
|---|---|---|---|---|
| **Fast** | `nimbus set K=V` | `POST /levers` on the running service, team token, applied in-process, caches cleared | ~1s | `RESPONSE_CACHE`, `SEMANTIC_CACHE`, `SEMANTIC_CACHE_THRESHOLD`, `MAX_TOKENS`, `SYSTEM_PROMPT`, `RETRIEVE_K`, `ROUTE_EASY`, `MODEL_TIER`, `MODEL_ID` (from allow-list), `SHED_ABOVE_QUEUE`, `RETRIEVE_TIMEOUT_MS`, `MAX_CONCURRENT` |
| **Slow** | `nimbus deploy` | `gcloud run services update --update-env-vars` on the **already-built image** | ~25–40s | `MIN_INSTANCES`, `MAX_INSTANCES`, container `--concurrency`, CPU/memory |

**Invariant: never rebuild the image during a session.** `gcloud run deploy --source` triggers
Cloud Build and takes 2–4 minutes. `gcloud run services update --update-env-vars` against an
existing image is a metadata-only revision at ~25–40s. The image is built once, the morning of.

The slow path is deliberately reserved for infrastructure capacity — which is precisely the class
of lever the activity wants participants to reach for *last*, and making it visibly slower is
honest rather than punitive. It also produces a new **revision ID**, which is what the run record
and the `CHANGE DETECTED` panel key their before/after on.

### 3.3 Isolation model

One Cloud Run service per team: `nimbus-team-a`, `nimbus-team-b`, … Non-negotiable (B6). Each has:

- its own `NIMBUS_INCIDENT` (never exposed),
- its own team token in Secret Manager (participants never get an admin token),
- its own queue, caches, lever state and revision history,
- `min-instances=0` outside the session, so standing cost is token spend only.

Deployment is a loop over the existing `deploy/deploy.sh`. The facilitator gets a card of
team → URL → token → assigned incident.

**The shared endpoint is the one thing that stays shared**, so there is one Vertex AI budget and
one place to watch spend. See risk R3 — shared quota is how INC-05 can fire accidentally across
every team at once.

---

## 4. Observability contract

### 4.1 Metric inventory

Organised by the four golden signals, and split symptom / white-box as P8 requires.

**User-facing (symptom level — answers "what is broken")**

- Successful request rate, failed request rate *(traffic, errors)*
- p50 / p95 / p99 end-to-end latency *(latency)*
- Time to first token *(latency)*
- Requests exceeding the latency target — count and share *(latency)*
- Answer quality score, split extraction / reasoning *(quality)*
- Grounding: retrieved source count and top-score *(quality)*

**Application (white-box — answers "why")**

- App queue wait — time between arrival and semaphore acquisition
- Stage durations: cache lookup, retrieve, assemble, generate
- Output token **count** per request — the load-independent decode signal (see R1: the
  per-token *rate* was tried first and inflates with contention)
- Cache hit rate, by cache type
- Input tokens, output tokens, provider-cached tokens
- Provider retry count and terminal status code
- Provider / model ID actually used, and routed tier
- Concurrent in-flight requests, queue depth at arrival *(saturation)*

**Cloud (white-box — answers "why", and the part the app cannot see itself)**

- Cloud Run request latency (Monitoring) vs app-reported total — **the residual is Cloud Run's own
  pending queue plus cold start** (B9)
- Revision ID, instance count, instance ID
- Container concurrency setting vs observed concurrent requests
- Cold start count and container startup latency
- Cloud Run 4xx / 5xx
- Vertex AI throttle / quota events

### 4.2 The additive latency ledger

The centrepiece of the panel. Rows sum to the top number; a non-zero unexplained residual is a bug
in the instrumentation, not noise.

```
latency      median    21.40 s
             p95       25.19 s   target 5.00 s   FAIL
             p99       25.83 s
             note: with 16 requests "p95" is the 2nd-slowest request.

             ── where the time went (p95, additive) ─────────────────
  client + network        0.09 s   ▏
  cloud run queue         0.02 s   ▏          ← Monitoring minus app total
  app queue wait         18.01 s   ████████████████████████
  cache lookup            0.00 s   ▏
  retrieve                0.01 s   ▏
  assemble                0.00 s   ▏
  generate                7.40 s   █████████
                        ───────
                         25.53 s   (end-to-end 25.19 s · residual −1.3%)

             ── how the model behaved ──────────────────────────────
  TTFT p95               18.6 s      18.0 s of it was queue
  provider retries       0           429/5xx: 0
  provider               vertex:mistral-small-2503

             ── work per request ───────────────────────────────────
  input tokens           1,480       baseline 1,480 · normal
  output tokens          32          cap 32
  cache hit rate         0%

             ── saturation ─────────────────────────────────────────
  peak in-flight         8 / 2 admitted
  instances              1           cold starts 0
  revision               nimbus-team-a-00007-xyz
```

Every row except the three marked below already exists somewhere in the codebase and simply is not
plumbed through. **New instrumentation required:** `cloud run queue` residual, `provider retries`,
baseline comparators.

### 4.3 What the report says, and what it must never say

The verdict block ends with an attribution and stops:

```
VERDICT  0/2 constraints met

READ THIS FIRST
  Largest contributor to p95: APP QUEUE WAIT (71%).
  Generation is 29%. No other stage exceeds 1%.
  Inter-token latency and input tokens are both at baseline.
```

It names the dominant slice, states what is *not* anomalous (which is half of diagnosis), and
refuses to name a lever. `report.py:229–232` — the current `hint ... The model is not your
problem.` — is deleted (B10, P4).

---

## 5. Incident catalog

### 5.1 Structure

Each incident is a scenario ID baked into a team's deployment (`NIMBUS_INCIDENT=retrieval`). It
carries a **public brief** shown to participants and a **private truth** in the facilitator key.

The public brief is symptom-only:

```
INCIDENT 02 — DEGRADED RESPONSE TIME

Students report the assistant "takes forever to start answering."
Complaints began Tuesday. Nothing was deployed on Tuesday.

TARGETS
  p95 latency    < 5.0 s
  quality        ≥ 80%
  monthly cost   < $1,500

YOUR TASK
  Attribute the latency, then change one thing.
```

### 5.2 The incidents

| ID | Public symptom | Private truth | Unique discriminator |
|---|---|---|---|
| **INC-01** `queue` | Slow for everyone; worse the busier it gets | Admission limit (2) far below arrival rate (8) | App queue wait dominates while ITL and tokens are at baseline |
| **INC-02** `retrieval` | Slow to *start* answering; the answer itself is fine | Hosted vector store + reranker, p95 1.8s, fat tail | `retrieve` stage p95 is the dominant slice |
| **INC-03** `prompt` | Bill tripled; latency mildly worse | `RETRIEVE_K` 4→12 plus 900 extra tokens of instructions | Input tokens ~5× baseline with output tokens unchanged |
| **INC-04** `decode` | Answers start instantly then crawl | `MAX_TOKENS` 32→256, `VERBOSE` prompt, Gemini 2.5 Pro large tier with thinking enabled | Output token **count** far above baseline, with `generate` dominant |
| **INC-05** `upstream` | Mostly fine, occasionally terrible | Vertex 429/5xx on ~1 call in 6; adapter retries silently | Non-zero provider retries; p99 ≫ p95 with all stages normal on successes |
| **INC-06** `coldstart` | First question of the morning is awful, rest are fine | `min-instances=0`, heavy container startup | Cloud-Run-minus-app residual on first request only; instance count 0→1 |
| **INC-07** `staleness` | Nobody complained about speed. Answers are wrong. | `SEMANTIC_CACHE_THRESHOLD` 0.92→0.55 | Cache hit rate ~84%; eval fails across **both** extraction and reasoning |
| **INC-08** `cheapmodel` | Fast and cheap; tutors say answers got shallow | Small model for everything | Eval failure concentrated in **reasoning** (67%) while extraction holds (83%) |
| **INC-09** `deployment` | Service unhealthy; `/health` unavailable | IAM / model-access / region misconfiguration | Zero successful requests — the report must refuse to score it |

**INC-07 vs INC-08 is a deliberate near-collision** and the resolution is already measured in
`benchmark/eval_card.md`: a stale cache degrades everything uniformly, while a too-small model
holds extraction and collapses on reasoning. Two teams handed "green dashboards, bad answers" must
reach different causes. This pair is the strongest test of P6 and must be re-verified after every
calibration.

**Assignment policy for the 20-minute session:**

- **Round 1 (shared):** INC-01. Everyone. This is instrument calibration, not competition.
- **Round 2 (assigned, one per team):** INC-02, INC-03, INC-04, INC-05. Four teams' worth; with
  six teams, duplicate INC-02 and INC-04 — they are the cleanest "is it the LLM" pair (one is, one
  isn't).
- **Reveal (facilitator-run, front of room):** INC-07. Nobody finds a silent quality failure in
  eight minutes, and a team that fails to find it learns nothing. Put a **2/2 PASS** report on the
  projector, ask the room whether to ship, take the vote, then run the eval.
- **Not in the timed session:** INC-06, INC-08, INC-09. INC-06 needs a cold instance and therefore
  a dedicated slot; INC-08 is the trap already reachable from any round; INC-09 is a preflight
  drill for facilitators, not a teaching incident under time pressure.

### 5.3 Signature matrix — generated, not authored

`facilitators/calibrate.py` runs every incident and emits `facilitators/signatures.json` plus a
rendered matrix. **The matrix in a design document is a hypothesis; the shipped one is measured**,
in exactly the way `eval_card.md` and `answer_key.md` are already generated rather than
hand-edited.

The calibrator must **fail the build** if any two incidents fall within noise on every column
(P6). That check is the whole reason the matrix is generated.

```
                queue  retrieve  generate  tok-in  tok-out  p99/p95  errors  cloud-resid  eval
INC-01 queue     ███      ·         ·        ·       ·        ·        ·         ·        ok
INC-02 retrieval  ·      ███        ██       ·       ·       ███       ·         ·        ok
INC-03 prompt     ·       ·        ███      ███      ·        ·        ·         ·        ok
INC-04 decode     ·       ·        ███       ·      ███       ·        ·         ·        ok
INC-05 upstream   ·       ·         ██       ·       ·       ███      ███        ·        ok
INC-06 coldstart  ·       ·         ·        ·       ·       ███       ·        ███       ok
INC-07 staleness  ▼       ▼         ▼        ▼       ·        ·        ·         ·      FAIL both
INC-08 cheapmodel ▼       ·         ▼        ·       ·        ·        ·         ·      FAIL reasoning
```

Read it **by column**. Retrieve moves in one. Input tokens in one. Output tokens in one. Errors in
one. Cloud residual in one. Every incident has a column nothing else touches.

*Illustrative only.* The shipped matrix is generated into `facilitators/signatures.json` by
`calibrate_incidents.py`, which fails the build on a collision or on an incident that does not
present as advertised.

### 5.4 Injection mechanics

`service/incident.py`, read once at import from `NIMBUS_INCIDENT`.

| Incident | Injection | Notes |
|---|---|---|
| `queue` | None — real `asyncio.Semaphore` at `MAX_CONCURRENT=2` against concurrency-8 load | The bottleneck is genuine |
| `retrieval` | **Log-normal** delay in the `retrieve` stage: median 0.4s, p95 1.8s | Must be log-normal, not constant — see invariant I2 |
| `prompt` | Config only: `SYSTEM_PROMPT=LONG`, `RETRIEVE_K=12` | No code path needed |
| `decode` | Config plus deploy-time model settings: `MAX_TOKENS=256`, `SYSTEM_PROMPT=VERBOSE`, `MODEL_TIER=large`, `ROUTE_EASY=false`, `NIMBUS_GOOGLE_MODEL_LARGE=gemini-2.5-pro`, `NIMBUS_GEMINI_THINKING_BUDGET=128` | Requires Gemini calibration; Pro's minimum thinking budget is 128 |
| `upstream` | Fault rate in `cloud_model.py` raising `RetryableProviderError` for a share of calls | Exercises the retry path that already exists |
| `coldstart` | `min-instances=0` plus an artificial startup delay in `lifespan` | Requires a genuinely cold service |
| `staleness` | Config only: `SEMANTIC_CACHE_THRESHOLD=0.55`, `SEMANTIC_CACHE=true` | |
| `cheapmodel` | Config only: `MODEL_TIER=small` | Already the existing trap |
| `deployment` | Deliberately wrong model ID or revoked IAM binding | Facilitator drill only |

Injection is seeded per run so a team can reproduce its own result — an unreproducible incident
teaches that measurement is unreliable.

---

## 6. Data model

Three collections in Firestore. Sanitized: no raw student questions, no tokens, no secrets.

### Incident (seeded, read-only to participants)

```
id                  "inc-02-retrieval"
title               "Degraded response time"
public_symptom      participant-visible brief text
user_impact         "Students report the assistant takes forever to start answering"
traffic_profile     { requests, rate, concurrency, corpus_seed }
targets             { p95_latency_s, quality_pct, cost_usd_month }
work_items          [ work_item_id ]
private_truth       facilitator-only; NOT served to team-scoped readers
```

### Run (one per benchmark execution)

```
id                  Cloud Run Job execution ID
session_id          "team-a"
incident_id
revision_id         Cloud Run revision serving the run
job_execution
timestamp
config_snapshot     effective levers at run time, from /metrics
provider            { provider, model_id, api_style, region }
traffic             { requests, rate, concurrency, ok, shed, failed }
latency             { p50, p95, p99, ttft_p95, itl_ms_p95 }
stages_ms           { client_network, cloudrun_queue, app_queue, cache,
                      retrieve, assemble, generate }
errors              { provider_retries, provider_status, cloudrun_5xx }
saturation          { peak_inflight, admitted, instances, cold_starts }
tokens              { input, output, cached }
quality             { overall_pct, extraction_pct, reasoning_pct, eval_run_id }
cost                { usd_per_1k, usd_tokens_month, usd_infra_month, usd_month }
verdict             { latency, cost, quality, met, marginal }
previous_run_id     ← replaces report.py's filesystem lookup of run-{N-1}.json
```

`previous_run_id` is the fix for B7. `report.py:152` currently reads
`results_dir / f"run-{N-1}.json"`; on Cloud Run that file does not survive the instance. The
before/after comparison must come from the run store, keyed by session.

### Work item (the unit of "what would fix this")

```
id
incident_id
issue_category      queue | retrieval | prompt | decode | provider | cache | model | capacity
expected_signal     which metric should move, and in which direction
allowed_change      the lever(s) legitimately in scope
success_condition   e.g. p95 < 5.0 AND quality >= 80 AND cost < 1500
regression_condition e.g. quality < 80 OR cost > 1500
```

`regression_condition` is what makes the traps bite automatically: INC-04's tempting fix
(`MODEL_TIER=small`) satisfies latency and cost and trips the quality regression.

### Declaration (success flagging — see §8)

```
id, session_id, incident_id, kind, timestamp, payload, run_id
kind ∈ { hypothesis, ruled_out, recovered, stuck }
```

---

## 7. Participant workflow

### 7.1 The CLI

The terminal stays essential. The UI mirrors it — it does not replace it.

```bash
nimbus brief          # incident brief + targets, symptom only
nimbus baseline       # run the benchmark with nothing changed; establishes run 1
nimbus diagnose       # attribution of the last run, and the questions it raises
nimbus hypothesis     # record a diagnosis — REQUIRED before any lever change
nimbus set K=V        # fast path: runtime lever change (~1s)
nimbus deploy         # slow path: new revision for capacity levers (~30s)
nimbus benchmark      # trigger the Cloud Run Job; stream execution logs
nimbus eval           # run the quality harness
nimbus declare        # flag success (see §8)
nimbus status         # current config, revision, last verdict
```

### 7.2 The four screens

**1 · Brief** — symptom, user impact, targets, task. Cause absent.

**2 · Baseline** — explicitly instructs *do not change anything yet*, lists what is being measured,
and closes on the diagnostic question rather than an answer:

```
BASELINE MEASUREMENT
Do not change configuration yet.

Measuring: end-to-end p95 · TTFT · app queue wait · stage durations ·
           error rate · provider latency · quality · projected cost

QUESTION
Is the service waiting, computing, retrieving, or failing?
```

**3 · Diagnose** — evidence and interpretation, stopping short of the fix. The interpretation
section presents *hypotheses and the next discriminator*, never a lever:

```
OBSERVED
  p95 latency  10.1s      queue wait  4.7s      compute  5.4s
  errors       0%         quality     94%       TTFT     9.2s

INTERPRETATION
  Time is split between waiting and computing. Neither dominates.
  You need one more discriminator before choosing a fix.

NEXT MEASUREMENT
  Inter-token latency separates slow decode from slow everything-before-decode.
  Input tokens against baseline separates prompt growth from model speed.
```

**4 · Change detected** — the before/after panel, keyed on config snapshot and revision diff. This
is where the learning consolidates, and it must state user impact and a decision, not just deltas:

```
CHANGE DETECTED
  Model            Mistral Small → Gemini Flash
  Config           NIMBUS_GOOGLE_MODEL_ID
  Revision         00007-xyz → 00008-abc

BEFORE / AFTER
  p95 latency      10.1s → 3.8s
  app queue wait    4.7s → 0.6s
  generate p95      5.4s → 2.9s
  inter-token     168ms → 94ms
  quality           94% → 91%
  cost/month      $1,910 → $840

USER IMPACT
  Students receive answers sooner. Quality remains above target.

DECISION
  Keep. The bottleneck was model/provider work, not Cloud Run capacity.
```

---

## 8. Success flagging

The governing rule: **a flag only counts if it was committed before the evidence that would
confirm it.** Otherwise a team changes something at random, sees PASS, and writes the diagnosis
backwards from the result.

### Round 1 — shared incident, calibration not competition

**`DIAGNOSED`** — submitted before any lever change. Three fields, all populated from rows already
on screen:

```json
{ "dominant_slice": "app queue wait",
  "model_implicated": false,
  "proof_metric": "inter-token latency at baseline" }
```

**Auto-graded immediately**, and it says so. Round 1's goal is that everyone leaves with the
instrument working, so confirming here is correct. This replaces a facilitator enforcing rung 1
table by table; the gate to move on is "5 of 6 teams green on the board."

**`RECOVERED`** — the command refuses unless the *last recorded run* reports 2/2. Not typed
numbers; the run record is the evidence.

### Round 2 — assigned incidents, ordering enforced

**`HYPOTHESIS`** — and `POST /levers` returns **`409 diagnose first`** until one exists (P5).

```json
{ "dominant_slice": "retrieve",
  "model_implicated": false,
  "proof_metric": "generate p95 and ms/token both at baseline",
  "predicted_lever": "SEMANTIC_CACHE",
  "predicted_direction": "p95 down, generate unchanged" }
```

**Not graded.** Round 1 confirms; Round 2 records and stays silent — confirming here would end the
investigation before it is tested. Teams may revise; both versions stay on the board, timestamped,
the way an incident timeline does.

**`RULED_OUT`** — optional and worth celebrating:

```json
{ "ruled_out": "decode", "how": "MAX_TOKENS 256→16, p95 moved 4%", "run_id": "..." }
```

This exists to reward the INC-02 moment: a team that spends a run *disproving* the model deserves
credit, and today nothing notices. Counted on the board.

**`RECOVERED`** — gated on 2/2 **and** quality ≥ 80%. Non-negotiable in Round 2: INC-04's tempting
fix passes latency and cost and fails quality at 78%. Without the gate the trap does not bite;
with it, the team discovers the trap themselves. Practically, `nimbus declare recovered` runs the
eval before it will succeed — and that ~15s wait is a feature, because it makes the cost of the
quality axis physical, which is what `eval_card.md` already argues in prose.

**`STUCK`** — a page-for-help button. Six minutes is short; escalation is part of incident
response and should not be a raised hand nobody sees.

### The board

One projected page, one row per team, incident column **masked until the reveal** — unmasking it
*is* the poll beat, and the room discovers the faults differed rather than being told.

```
TEAM   INCIDENT   HYPOTHESIS   RULED OUT   RECOVERED   p95    $/mo   QUALITY   LEVERS
a      ███████    09:12 ✓      1           09:17 ✓     3.1s   $402   92%       2
b      ███████    09:14 ✓      0           —           8.4s   $611   —         4
c      ███████    —            0           —           ⚠ STUCK
```

**Do not sort by time.** A speed leaderboard drives teams straight to `MODEL_TIER=small`, the
precise reflex the activity exists to break. Sort by nothing, or by fewest levers used — which is
continuous with the poll `facilitators/runsheet.md:29` already runs.

The interesting quadrant at reveal is **recovered with a wrong hypothesis** — got lucky. Name it
warmly: it is the most common real-incident outcome and the reason timelines get written down.

**Paper fallback** (also the wifi-dies path, so it must exist regardless): three card colours per
table — teal `DIAGNOSED`/`HYPOTHESIS` (facilitator initials and times it), green `RECOVERED`
(facilitator checks the quality number before initialling), amber `STUCK`. The only thing that
does not survive the paper version is the `409 diagnose first` gate — which is ~10 lines in
`app.py` and enforces the workshop's central claim without a human in the loop. Build it first.

---

## 9. Model catalog (after the diagnosis workflow works)

Sequencing matters: the catalog is an amplifier, not a foundation. Build it in Phase 4.

**Per-model metadata**, server-side, participants select by key only:

```
key, display_name, provider_protocol, model_id, regions,
usd_per_1m_input, usd_per_1m_output, usd_per_1m_cached_input,
quality_baseline_pct, max_output_tokens, expected_latency_range_s
```

**The browser and CLI must never submit an arbitrary model ID.** Participants choose from an
allow-list; anything else is rejected server-side. This is both a cost control and a safety
control.

**Adapter work.** `service/cloud_model.py` currently speaks the Mistral publisher
`streamRawPredict` shape and an OpenAI-compatible shape. **Gemini uses `generateContent` /
`streamGenerateContent` and needs a separate adapter** — different request body, different
streaming envelope, different usage field names. Factor the existing module into a protocol
interface with `mistral`, `openai` and `gemini` implementations behind one `generate()` contract,
so `app.py` is unchanged.

First matrix: Gemini Flash, Gemini Pro, Mistral Small, one Gemma. Verify region availability and
current pricing with the cloud owner immediately before the event and update `scenario.json`,
which already tracks these as auditable assumptions.

This turns model selection into a real lever with real trade-offs — directly serving the deck's
model-selection half, which two SmolLM tiers could only gesture at.

---

## 10. Delivery phases

Each phase is independently shippable and leaves the workshop in a runnable state.

### Phase 0 — Signal plumbing *(~1 day; highest value per line in the whole plan)*

Makes symptom-first diagnosis possible with **no new infrastructure at all**.

- `run.py`: record `stages_ms` in the result row *(one line — B1)*
- `report.py`: render the additive ledger, inter-token latency, tokens vs baseline, provider
  retries, residual
- `report.py`: delete the `hint` line; add `READ THIS FIRST` *(B10, P4)*
- `cloud_model.py`: count retries into `stats` instead of swallowing them
- `scenario.json`: per-incident baseline values so the report can print "normal" beside a number

**Done when:** a local baseline run prints an additive breakdown whose rows sum to end-to-end
within 2%, and names the dominant slice without naming a lever.

### Phase 1 — Incident layer *(~2 days)*

- `service/incident.py` — `NIMBUS_INCIDENT`, per-stage delay hook, provider fault rate, seeded
- `app.py` — wrap the `retrieve` stage in the hook; never expose the incident ID
- `config.py` — strip the rung headers; keep the levers and the honest per-lever comments *(B4)*
- `facilitators/calibrate.py` — calibrate all incidents, emit `signatures.json`, **fail if any two
  incidents are within noise on every column** *(P6)*
- `benchmark/paper_track.md` — one printed panel per incident

**Done when:** the generated signature matrix shows a unique discriminator column per incident, and
INC-07 vs INC-08 separate on extraction-vs-reasoning.

### Phase 2 — Cloud runtime *(~3–4 days; the critical path)*

- `POST /levers` with team-token auth, in-process apply, cache clear *(B5)*
- `409 diagnose first` gate
- `deploy/deploy.sh` — loop over teams; one service each with its own incident and token; emit the
  facilitator card *(B6)*
- Cloud Run Job `nimbus-bench` — containerised `run.py`, takes target URL + session ID
- Firestore run store; `report.py` reads `previous_run_id` from the store instead of the
  filesystem *(B7)*
- Cloud metrics ingestion: revision, instances, cold starts, Cloud Run request latency → the
  cloud-queue residual *(B9)*
- `nimbus` CLI

**Done when:** two teams run concurrent benchmarks and neither team's numbers move when the other
runs.

### Phase 3 — Diagnosis UX *(~2 days)*

- `brief` / `baseline` / `diagnose` output
- `CHANGE DETECTED` before/after panel, keyed on config + revision diff
- Declarations, the board, the paper cards
- `benchmark/decision_sheet.md` restructured from rungs to diagnosis: *dominant slice · what you
  ruled out and with which number · hypothesis · what changed · did it move*
- `service/web/index.html` — mirror the CLI; keep the existing trace view as the "what is this
  thing" view

**Done when:** a dry run with two facilitators playing teams produces a legible board and a correct
before/after panel.

### Phase 4 — Model catalog *(~2 days)*

- Protocol interface + Gemini adapter
- Allow-list, per-model metadata, cost/quality baselines
- `scenario.json` price table extended

**Done when:** `nimbus set MODEL=gemini-flash` changes the model, the run record shows the new
provider and model, and cost is priced from the catalog rather than a hardcoded tier.

### Minimum cut, if there are only three days

Phase 0 + Phase 1 + the `POST /levers` endpoint and per-team services from Phase 2, driven from
Cloud Shell with `run.py` invoked directly instead of as a Job, and paper success cards instead of
the board. That is a complete symptom-first activity. It loses durable run history (so the
before/after must be read off two consecutive terminal outputs) and the projected board.

---

## 11. Invariants

Break any of these and the activity stops working **without producing an error**. Written in the
style of the existing list in `CLAUDE.md`, to which these should be appended.

- **I1 · Every incident must have a unique discriminator column.** Verified by the calibrator, by
  column, against measured data. Not by authoring intent.
- **I2 · Injected delays must be log-normal, not constant.** A constant delay appears identically in
  p50 and p95 and quietly teaches that percentiles do not matter.
- **I3 · `NIMBUS_INCIDENT` must never appear** in `/metrics`, `/health`, an error message, a log
  line the participant can read, or the browser bundle. One leak turns the exercise into a lookup.
- **I4 · The report must not name a fix.** It may name the dominant slice and what is at baseline.
  It may not name a lever or a rung.
- **I5 · At least one assigned incident must be genuinely model-bound (INC-04).** Otherwise "always
  blame something else" is the winning strategy.
- **I5a · No per-token rate may be published as a diagnostic signal.** Rates inflate with
  contention, so a busy queue and a slow model read the same. Use counts.
- **I5b · Non-queue incidents must not be queue-starved.** Offer traffic at the admission limit
  rather than raising the admission limit — raising it relocates the wait into generation and makes
  every incident look model-bound.
- **I5c · Every incident must be measured against `HEALTHY_ENV`, not against the shipped default.**
  The shipped default is itself an incident configuration.
- **I6 · Never rebuild the container image during a session.** `--update-env-vars` on an existing
  image is ~30s; `--source` is 2–4 minutes and will end the activity.
- **I7 · `MAX_CONCURRENT` must stay below the benchmark's `concurrency`.** *(Existing invariant.)*
  If they match, nothing queues, queue wait reads 0.00s, and INC-01 disappears silently.
- **I8 · `prompts.jsonl` must stay generated by `gen_prompts.py` from a repeating template.**
  *(Existing invariant.)* The benchmark sends the first N rows; sprinkled duplicates vanish under
  truncation and the cache levers look useless.
- **I9 · The report must never PASS with zero successful requests.** *(Existing invariant, and the
  reason INC-09 is scoreable at all.)*
- **I10 · Round 2 must re-baseline.** Switching incidents without clearing caches and run history
  lets a team read Round 1's cache hits as Round 2's behaviour.
- **I11 · One service per team.** This is the existing "never run anything else while calibrating"
  invariant restated for a shared deployment.
- **I12 · The Cloud Run Job and the local `run.py` must share corpus, seed and arrival process.**
  If they diverge, the answer key stops describing what the room sees.
- **I13 · Latency is hardware- and region-dependent; cost is not.** *(Existing invariant.)*
  Re-derive the SLO in `scenario.json` from calibration on the actual deployment before the session.
- **I14 · Run summaries must be sanitized.** No raw student questions, no tokens, no secrets in
  Firestore or on the board.

---

## 12. Risk register

| # | Risk | Impact | Mitigation |
|---|---|---|---|
| **R1** | Cloud Shell blocked by org policy, or the 50h/week quota is exhausted | Participants cannot start | Verify with a student account 3 days ahead; fall back to the browser UI, which needs only a URL |
| **R2** | Cloud Run Job cold start eats the round budget | 6-minute rounds become 4 | Pre-warm one execution during the brief; measure job start-to-first-request and publish it |
| **R3** | **Shared Vertex quota → real 429s across every team at once** | INC-05 fires accidentally everywhere; every signature is corrupted | Check quota headroom for `teams × concurrency × runs` before the session; request an increase; cap per-service request rate; have a lower-traffic profile ready |
| **R4** | Token spend runs away with 6 teams × N runs | Budget overrun | Budget alert; per-service max request count; `min-instances=0`; cap `--requests` in the Job |
| **R5** | A team's revision fails to deploy mid-session | That team is dead for the round | `nimbus deploy` verifies `/health` and rolls back to the last good revision automatically |
| **R6** | Firestore write from the Job blocked by IAM | Runs vanish; no before/after | Explicit `roles/datastore.user` on the Job service account; verified in preflight |
| **R7** | Signature collision discovered late | An incident is undiagnosable | The calibrator fails the build on collision — makes this a build-time error, not a live-session discovery |
| **R8** | The 20-minute slot cannot absorb two rounds | Reveal gets cut | Reveal is protected; cut the share-out first. Round 2 falls back to two incidents |
| **R9** | Participant wifi variance lands in client-side numbers | Noisy verdicts | The Job runs in Google Cloud, not on participant machines — this is largely designed out by §3.1 |
| **R10** | Gemini adapter work slips | Model catalog absent | It is Phase 4 precisely so the activity ships without it |

---

## 13. Open decisions

1. **How many teams, and does the cloud owner allow N Cloud Run services + N Secret Manager
   entries?** Recommendation: six services, deployed the morning of, torn down after.
2. **Four incidents in Round 2 or two?** Build four; if calibration time is tight, assign INC-02
   and INC-04 — the cleanest "is it the LLM" pair, one is and one isn't.
3. **Firestore or Cloud Storage for run summaries?** Recommendation: Firestore for summaries
   (queryable by session, cheap, trivially read by the board), Cloud Storage only if raw
   per-request artifacts are wanted for post-session analysis.
4. **Does the deck need a new slide?** No new slides, but deck item 3 ("latency is additive") must
   *show* an additive breakdown once, in the same shape as the panel — otherwise Round 1 reads as a
   mystery instead of a tool. This is a sixth entry for the consistency-risk list in
   `activity-alignment-check.md`.
5. **`REPLICAS` replacement.** The fake replica multiplier is the only lever with a bill and it is
   a simulation. Recommendation: replace with Cloud Run `max-instances` on the slow path (real,
   billable, and the thing actually being taught) and drop the simulation.

---

## Appendix A — Run of show

| Time | Beat | Facilitator |
|---|---|---|
| 0:00 | **The pager** | Read the brief. Targets on the board. Hand out URLs and team tokens. Services are already warm. |
| 1:30 | **Baseline — everyone** | `nimbus baseline`. Same INC-01, same FAIL. |
| 3:00 | **Round 1 · read the panel** *(protected)* | "Which slice is biggest? What is inter-token latency doing? Is the model the problem — and which number says so?" Gate on `DIAGNOSED` flags, not on a vibe. |
| 6:00 | **Round 1 · fix it** | Two levers, two runs, back inside both constraints. Builds the change-one-thing habit. |
| 8:30 | **Round 2 · the second page** | "A new incident just opened on your service. It is not the same one." Hypothesis required before `nimbus set` will work. |
| 14:30 | **Poll** | Unmask the incident column. "Who concluded the model was the problem? Who *proved* it wasn't?" |
| 16:00 | **Share** | Two teams with *different* incidents, 45s each: what the panel said, what you ruled out, what you changed. |
| 17:30 | **Reveal · INC-07** *(protected)* | 2/2 PASS on the projector. "Ship it?" Vote. Then run the eval. |

Closing line, unchanged: *Scaling is diagnosis first. The cheapest fix is usually a config change —
not a bigger bill, and not a worse model.*

---

## Appendix B — File-by-file change list

| File | | Change |
|---|---|---|
| `service/incident.py` | **new** | Reads `NIMBUS_INCIDENT` at import; per-stage delay hook; provider fault rate; seeded RNG |
| `service/levers_api.py` | **new** | `POST /levers` handler, team-token auth, `409 diagnose first` gate |
| `service/gemini_model.py` | **new** *(P4)* | `generateContent` / `streamGenerateContent` adapter |
| `benchmark/store.py` | **new** | Firestore run-summary read/write; `previous_run_id` resolution |
| `cli/nimbus` | **new** | brief · baseline · diagnose · hypothesis · set · deploy · benchmark · eval · declare · status |
| `service/app.py` | edit | Wrap `retrieve` in the incident hook; add `upstream_retries`, `error_class`, saturation counters to the stats event; mount `/levers`, `/eval`, `/declare`; never expose the incident |
| `service/cloud_model.py` | edit | Count retries into `stats`; optional injected fault rate; surface provider `cached_tokens`; factor into a protocol interface |
| `service/config.py` | edit | Strip rung headers; keep levers and honest comments; add `RETRIEVE_TIMEOUT_MS` |
| `benchmark/run.py` | edit | Record `stages_ms`; accept session ID; write to the run store instead of `results/` |
| `benchmark/report.py` | edit | Additive ledger; ITL; tokens vs baseline; retries; cloud residual; `READ THIS FIRST` replaces `hint` |
| `service/web/index.html` | edit | Mirror the CLI screens; run history with change log; keep the trace view |
| `scenario.json` | edit | Per-incident baselines; model catalog prices; `max-instances` replacing `replica_usd_per_month` |
| `deploy/deploy.sh` | edit | Per-team loop; incident + token per service; facilitator card; `--update-env-vars` fast path |
| `deploy/bench_job.yaml` | **new** | Cloud Run Job definition for `nimbus-bench` |
| `facilitators/calibrate.py` | edit | Calibrate all incidents; emit `signatures.json`; fail on collision |
| `facilitators/runsheet.md` | edit | Two-round structure; flag gates; masked board |
| `benchmark/decision_sheet.md` | edit | Rungs → diagnosis worksheet |
| `benchmark/paper_track.md` | edit | One printed panel per incident |
| `facilitators/eval*.py`, `data/`, `retrieval.py`, `embed.py` | **keep** | Unchanged. The flat index becomes the deterministic fallback for INC-02 |
