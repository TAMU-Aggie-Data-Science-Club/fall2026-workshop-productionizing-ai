# Current update · 2026-09-06

The implementation and live Cloud Run verification in [DEVELOPMENT_LOG.md](DEVELOPMENT_LOG.md)
supersede the historical status below. **100 tests pass; prompt, retrieval and queue
recovery have been measured live.** Two-team credential isolation, the diagnosis
gate, both real model tiers, quality checks and a concurrent final run passed.

The default round-2 room is prompt/retrieval. Decode/upstream and the two quality
cases remain experimental. The old quality-separation claim is not reinstated.
Use the current README, participant quickstart, CONTRIBUTING and deploy/README.
A human workshop dry run remains distinct from the completed scripted rehearsal.

---

## Historical status retained for context

# Build Status

State of the symptom-first redesign described in [`DEV_PLAN.md`](DEV_PLAN.md).
**`DEV_PLAN.md` is the design; this file is where the work actually is.**

> **The goal.** A 20-minute activity where each team gets a *different* fault,
> sees it only as numbers against a target, must commit to a diagnosis before
> the system will let them change anything, and can prove their fix worked.
> On Google Cloud. Participants need a terminal, a URL and a team token.

Nothing is marked done without the evidence that it works. "The code exists" is
not done; "I ran it and here is what it printed" is.

---

## Now

| | |
| --- | --- |
| **Blocked on a decision** | The quality axis does not discriminate on Gemini. See below. |
| Deployed | `nimbus-eval` (~$2.29/day) — kept for further eval runs |
| Tests | 88 passing (`python -m unittest discover -s tests`, ~2s) |
| Last verified end to end | 2026-09-04 — see "Verification run" below |

### Verification run · 2026-09-04

Both paths exercised from a clean tree. What actually printed:

**Cloud** — `nimbus-eval`, Gemini 2.5 Flash, warm, carrying the `queue` incident.

* `GET /health` → ready, backend `google`, 48 note chunks
* `GET /brief` → symptom only ("Everyone is waiting"), targets, calibrated traffic profile
* `POST /ask` → real answer in **0.67s**; stats reported
  `queue 1.7ms · retrieve 28.6ms · generate 640.2ms`, provider `google`,
  model `gemini-2.5-flash`, usage from the provider
* `/metrics`, `/levers` → **401** with no token and with a wrong token
* `nimbus brief` → renders; cause absent
* `nimbus baseline` → p95 **2.63s** vs 1.5s SLO **FAIL**, cost **$790/mo** vs $1,500 **PASS**,
  verdict 1/2. Ledger residual **+0.0%**. `READ THIS FIRST`: *APP QUEUE WAIT (64%)*,
  then generate 32%; tokens in and out both at baseline
* `nimbus diagnose` → three questions, no lever named

The `queue` incident therefore still **presents as advertised**: queue dominant, tokens
steady, and the report names the slice without naming the fix.

**Local** — SmolLM2 tiers, `make serve` + `run.py`.

* Service up in ~10s, `/ask` streamed with the full stage ledger
* 16 requests: p95 **46.23s**, ledger residual **+0.0%**,
  `READ THIS FIRST`: *APP QUEUE WAIT (83%)*

**Not verified**: anything requiring the admin token. `gcloud secrets versions access` is
blocked in this environment, so `POST /levers`, the `409 diagnose first` gate against a live
service, `/metrics` contents, and `preflight.py --all-services` were checked only for correct
rejection, not for correct acceptance.

### Two defects found while verifying  ⚠ NOT YET FIXED

Both are in `benchmark/report.py`, and both are the same shape: a comparison that does not
check it is comparing like with like.

1. **`_baseline()` ignores which backend was measured.** It reads
   `scenario.json` → `baselines.default` unconditionally, while the file records
   `baselines._backend: "google"` two lines away and nothing consults it. The healthy local
   run above printed `input tokens 794 avg · baseline 226 · +252%` — which is exactly the
   advertised signature of the `prompt` incident (`tokens_in` ≥ 3×) on a service carrying no
   incident at all. It also contradicts the `At baseline:` line, which the whole
   rule-a-suspect-out half of the diagnosis rests on.

2. **The previous-run comparison crosses backends.** `report.py:286` reads
   `run-{N-1}.json` and guards only on `ok > 0`. The local run quoted a Cloud Run + Gemini
   run as the number to beat: `VERDICT 0/2 constraints met (run 9: p95 3.19s, $781/mo)`
   against a 46.23s / $2,791 local run. Same class as the empty-run guard already fixed —
   that guard just needs to also cover the provider.

Neither bites while a session runs entirely on Cloud Run, which is why calibration did not
catch them. Both bite the moment local and cloud runs share a `results/` directory.

### The quality axis does not work as designed  ⚠ NEEDS A DECISION

Measured against the deployed service, 36 questions, bar 80%:

| config | overall | extraction | reasoning | verdict | should be |
| --- | ---: | ---: | ---: | --- | --- |
| healthy | 94.4% | 100% | 83.3% | PASS | PASS ✅ |
| cheapmodel | 86.1% | 87.5% | 83.3% | **PASS** | FAIL ❌ |
| staleness | 91.7% | 100% | 75.0% | **PASS** | FAIL ❌ |

Both quality incidents clear the bar, so three things silently stop working:

* the cheap-model trap never fires — a team that downgrades sees 86% and ships
* INC-SILENT, the reveal, has nothing to reveal
* the `recovered` flag, gated on quality ≥ 80%, lets both through

The cause is that the design was calibrated on SmolLM-135M vs -360M, where the
small model scored 78% against 94%. Gemini 2.5 Flash-Lite is simply a good
model: its reasoning score is **83.3%, identical to Flash's**. The gap the
activity depends on is not there.

---

## What is done

| | evidence |
| --- | --- |
| Additive latency ledger; per-stage timings plumbed through | live Cloud Run run, rows sum to end-to-end, residual +0.0% |
| `READ THIS FIRST` replaces the answer-giving `hint` | test fails if any of 10 lever names appears in the report |
| Token averages exclude cache hits | a prompt regression can no longer hide behind a healthy cache |
| Empty previous run not quoted as a comparison | a 0-of-4-success run was being offered as the number to beat |
| Gemini adapter (`streamGenerateContent`, thinking, usage) | TTFT 0.40s lite / 0.62s flash, correct token accounting |
| Per-model thinking-budget floors | flash-lite no longer 400s at budget 128 |
| `POST /levers` + `409 diagnose first` | 0.06s vs 3m59s for a redeploy |
| Shared lever schema for startup and runtime | a batch with one bad value applies nothing |
| Incident mechanism split from the catalog | `/metrics` on a live service: no incident leak |
| All 7 incidents calibrated on Cloud Run | every pair separated or declared quality-separated |
| Constraints derived from repeated measurement | SLO 1.5s; healthy passes, each incident fails its own axis |
| Gemini token prices verified | input/output were right; two cached-input rates were wrong |
| Scenario arithmetic made consistent | `qps_peak` 45 → 5, infra $70 → $140; a healthy service still passes |
| `deploy_incident.py` — a service is born with its whole incident | freshly deployed `cheapmodel` served flash-lite with no lever call |
| `preflight.py` — confirms a service before URLs go out | `/health` alone is not confirmation |
| `cli/nimbus` + quickstart — the participant path | full loop live: 1.99s FAIL → diagnose → fix → 1.20s PASS |
| Build once, deploy many | implemented; **unverified** — needs a clean tree to exercise |
| `README.md` and `CLAUDE.md` describe the current activity | rewritten 2026-09-04; no rung-ladder or Mistral-default claims remain in either |

## What is left

| | |
| --- | --- |
| **Quality axis** | blocked on the decision above |
| **Two report defects** | cross-backend baseline and cross-backend previous-run comparison, both found 2026-09-04 and both still open |
| **Materials** | run sheet, decision sheet, answer key, eval card, paper track all still describe the rung ladder on laptops. So do `benchmark/README.md` and `deploy/README.md` |
| **Signature matrix** | `signatures.json` still lists `cheapmodel`/`staleness` as `quality_separated`, which the eval no longer supports. It will keep asserting a separation that is not there until the quality decision lands |
| **Dry run** | deploy the room, preflight, walk two teams through, time it, tear down |
| **Housekeeping** | `.Dockerfile.swp` (a vim swap file) is tracked in git; `*.swp` is not in `.gitignore` |

## Deliberately not built

The CLI path makes these unnecessary for a working session: browser UI (Cloud
Shell was the original spec), Firestore run store (the CLI keeps runs locally and
before/after works), Cloud Run Job (Cloud Shell is already in-region), projected
board (paper cards, which are the wifi fallback anyway), model catalog beyond
the two tiers.

---

## Measurement rules learned the hard way

Each was a wrong answer before it was a rule.

1. **Never calibrate a cold container.** Identical config measured p95
   3.00/12.10/7.87 cold and 1.95/2.03/1.95 warm. A cold run reported the
   retrieval incident as 87% `generate`; warm it is 65% `retrieve`.
2. **Never trust a signature measured on a deployment carrying another
   incident's fault.** `cheapmodel` once had a higher retrieve-share than the
   retrieval incident itself.
3. **Suspect the stack before the provider.** A 13% spike rate to ~7s looked
   like Gemini having a bad day. Measured directly, bypassing Nimbus: p50 838ms,
   p95 1492ms, zero spikes.
4. **Percentile-shaped signals are degenerate at 16 requests.** p99 is the
   slowest request and p95 the second; their ratio is one unlucky sample.
5. **Token counts are stable where latency is not.** Across runs varying 4x in
   p95, token counts did not move at all.
6. **Set a threshold from a distribution, not a run.** An SLO picked from one
   0.74s measurement scored MARGINAL against the next healthy run.
7. **A client that picks its own concurrency measures a different system.** Each
   incident is calibrated under a specific load; the service now states it.

## Environment

* Project `adsc-nimbus`, billing on, five APIs enabled, build IAM granted
* Models: `gemini-2.5-flash` (large), `gemini-2.5-flash-lite` (small),
  `gemini-2.5-pro` (decode only), thinking budget resolved per model
* **Mistral is 404 on this project** — Model Garden access was never granted
* Docker daemon down, no Ollama models — the local Docker path is unavailable
* `min-instances=1` is required per service; a cold container invents incidents
