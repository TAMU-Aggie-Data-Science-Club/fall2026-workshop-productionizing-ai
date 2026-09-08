# Investigate your team's study assistant

> Archived material. Follow the [workshop README](../../README.md) for the current activity.

Students have reported a problem with Nimbus. Your team will measure it, explain
a likely cause, test one change, and show whether the service recovered. Allow
20 minutes for the investigation after setup and the shared demonstration.

Complete [preparation](preflight.md) first. Keep [the concepts](concepts.md) and
[team worksheet](worksheet.md) open. Choose a terminal operator, an evidence
reader, and a recorder; combine roles in smaller teams. Use the same terminal
and session throughout. Send traffic from only one teammate at a time, and wait
for each command to finish before starting the next.

## 1. Understand the problem — 2 minutes

```bash
nimbus brief
nimbus status
```

`brief` describes the user impact and the targets for your service. `status`
shows the current settings. Record the targets and the starting configuration.
The targets come from your service; use them rather than numbers from another
team or a previous workshop.

Open your team's service URL in a browser and ask one question, such as “What
is overfitting?” Look at the answer, sources, and request trace. Finish this
request before starting a benchmark. One answer helps you understand the path;
the next step measures a set of requests.

## 2. Measure before changing anything — 3 minutes

```bash
nimbus baseline
nimbus diagnose
```

`baseline` warms the service, sends the incident's configured workload, and
saves a report. Warm-up requests are excluded from the reported sample.
`diagnose` redisplays the latest results and asks you to interpret them; it does
not send another benchmark.

Read the report in this order:

1. **Outcomes:** how many requests succeeded, were rejected, or failed?
2. **Targets:** which latency or projected-cost target was missed?
3. **Time:** which row in `p95 req` accounts for the largest part of that slow
   request? The rows add up; `p95 each` is a separate set of percentiles.
4. **Clues:** do input/output tokens, retrieval time, queue wait, cache behavior,
   or provider retries help explain the symptom?

Record numbers and units. A large stage tells you where to investigate; it does
not, by itself, identify the cause. If the largest row is `client + network`,
the report cannot separate startup, transit, and other unmeasured work.

## 3. Record a prediction — 3 minutes

Write: “We think ___ because we measured ___. Changing ___ from ___ to ___
should ___. We will also check ___ for a regression.” A **regression** is
something that gets worse after a change.

Replace the quoted text below with your evidence and prediction:

```bash
nimbus hypothesis \
  --slice 'stage or signal we observed' \
  --proof 'measured value, unit, and comparison' \
  --lever 'SETTING_NAME' \
  --expect 'metric we predict will change and in which direction'
```

Add `--model` if your hypothesis implicates model generation. Recording a
hypothesis opens the change gate; the service checks that one exists but does
not grade it. Your team must justify the prediction.

## 4. Test one change — 5 minutes

Choose a setting from the reference below and write down its old value. Replace
`KEY=VALUE` with your chosen setting and value; it is a placeholder.

```bash
nimbus set KEY=VALUE
nimbus bench --label 'setting: old value to new value; predicted effect'
nimbus status
```

`set` changes the running service and prints the old and new values. `bench`
measures again with the service's traffic profile. Keep request count, arrival
rate, and client concurrency the same as the baseline. Make changes only
between completed runs. The CLI accepts multiple settings, but this activity
uses one at a time so you can interpret the result.

Compare against your prediction. If the result is worse, use `nimbus set` with
the old value and benchmark again to verify the restoration. If it is close to
a threshold, repeat the same workload before making a strong claim. Record a
new hypothesis before another experiment.

## 5. Check recovery and answer quality — 4 minutes

```bash
nimbus eval
```

`eval` checks 36 questions against the configuration from your latest benchmark
and adds the quality score to that run. Wait for it to finish; it makes real
model calls. If settings changed since the benchmark, run `bench` again first.

`RECOVERY PASS` requires passing latency, modeled cost, all benchmark requests
succeeding, and the quality threshold, with a stable observed configuration.
A latency/cost `2/2` alone does not establish recovery. A failed recovery check
is a valid result to explain, not something to conceal by changing the workload.

After evaluation, use the browser to inspect a factual answer, an explanation,
and a question the notes cannot answer. Compare answers with the retrieved
notes. The keyword score can miss errors; record any you find even if the
automated result passes.

## 6. Explain your result — 3 minutes

Use your worksheet to report the symptom, evidence, change, before/after result,
quality checks, and any unresolved issue. State whether the evidence supports
recovery. Finish with one additional control this service would need if it could
take an action, such as creating calendar events.

## Setting reference

These are options to investigate, not a sequence of changes to apply. Your
measurements determine which is relevant. Booleans accept `true` or `false`.

| Setting | Accepted values | Effect and tradeoff to check |
| --- | --- | --- |
| `SYSTEM_PROMPT` | `LONG`, `TRIMMED`, `VERBOSE` | Select instructions; check input size and whether required answer behavior is preserved |
| `RETRIEVE_K` | Integer 0–20 | Select how many note chunks enter the prompt; fewer may reduce work but omit needed facts |
| `MAX_TOKENS` | Integer 1–1024 | Cap generated output; a low cap can truncate an answer or leave no visible text on a reasoning model |
| `MODEL_TIER` | `small`, `large` | Choose the default tier; `small` sends every question there, so check difficult questions |
| `ROUTE_EASY` | Boolean | With the large default, route short questions matching fixed patterns to the small tier; the rule can misjudge difficulty |
| `RESPONSE_CACHE` | Boolean | Reuse an answer for the same assembled prompt; retrieval still runs |
| `SEMANTIC_CACHE` | Boolean | Reuse an answer to a similar question before retrieval; similarity can hide a meaningful difference |
| `SEMANTIC_CACHE_THRESHOLD` | Number 0–1 | Set required similarity; lowering it accepts more matches, including potentially wrong ones |
| `MAX_CONCURRENT` | Integer 1–64 | Limit simultaneous work inside Nimbus; raising it can move pressure to the model provider |
| `SHED_ABOVE_QUEUE` | Integer ≥0; `SHED_ABOVE_QUEUE=` clears it | Reject requests beyond the waiting limit; check rejection counts alongside latency |
| `PREFIX_CACHE` | Boolean | Request reuse of static prompt computation in the local adapter; cloud reuse is provider-managed, so this switch does not guarantee a cloud benefit |

Runtime settings and hypotheses can be lost if the service restarts. If that
happens, ask the facilitator to check the service, inspect `status`, and start
a fresh session and baseline. Troubleshooting setup is in [preparation](preflight.md).
