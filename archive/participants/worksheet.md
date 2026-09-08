# Team investigation worksheet

> Archived material. Follow the [workshop README](../../README.md) for the current activity.

Team: __________  Recorder: __________  Run labels: __________

Keep your service token out of this worksheet. Copy results from your own runs;
mark a value “unknown” when it was not measured.

## User impact and targets

- What problem did students report?
- What are your service's latency, monthly cost, and quality targets?
- Which starting settings will you need to compare or restore?

## Evidence and prediction

- Which target failed in the baseline?
- Which stage or signal needs investigation? Include its value and unit.
- What cause could explain it? What evidence supports that explanation?
- What other explanation remains possible?
- We will change __________ from __________ to __________.
- We predict __________ will increase/decrease because __________.
- We will check __________ to make sure the change did not make it worse.

## Before and after

| Measurement | Baseline | After one change |
| --- | --- | --- |
| Requests / arrival rate / client concurrency | | |
| Successful / rejected / failed requests | | |
| p95 latency (seconds) | | |
| Largest `p95 req` stage and its time | | |
| Input / output token signal used in our hypothesis | | |
| Projected monthly cost (USD) | | |
| Quality score (if evaluated) | | |
| Configuration remained stable | | |
| Recovery result | | |

## Inspect answers after evaluation

| Check | Question we asked | What the answer and notes showed |
| --- | --- | --- |
| Find a fact | | |
| Explain or apply a concept | | |
| Ask something outside the notes | | |

## Report back

“Students experienced __________. We measured __________, which suggested
__________. We changed __________. The result was __________. Our quality
checks showed __________. Recovery is __________, with __________ still
uncertain.”

If the change made things worse, record the restored value and verification run.
If you had more time, what would you measure next?

## Extend to an agent

Suppose Nimbus could create study sessions in a calendar. Name one action it
may take, one permission boundary, one stopping limit, and one test that checks
the actual calendar result. What happens if event creation succeeds but its
response is lost and the agent retries?
