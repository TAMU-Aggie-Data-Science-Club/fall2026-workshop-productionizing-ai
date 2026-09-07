# Nimbus facilitator run sheet

Twenty-minute symptom-first investigation, using predeployed Cloud Run services.
This is for facilitators. Follow [cloud operations](../deploy/README.md) and
[development evidence](../docs/DEVELOPMENT_LOG.md) before handing out URLs.

## Before participants arrive

- Deploy one service per team with a validated incident, distinct team token,
  minimum/maximum one instance, and the intended hypothesis gate.
- Complete authenticated preflight and a real warm baseline for each service.
  The current default round-2 catalog is prompt and retrieval.
- Keep the image digest, team/service mapping, traffic profile and recovery
  evidence accessible to facilitators. Do not reveal incident assignments.
- Distribute the real repository URL and participant quickstart ahead of time.
  Participants need the CLI and httpx; no generation models are installed.
- Use the service's /brief targets. Do not quote old 5-second ladder thresholds.
- Test venue connectivity and keep a facilitator terminal ready as a fallback.
  Old generated ladder/eval cards are historical, not current recovery evidence.

## Minute by minute

| Time | Action |
| --- | --- |
| 0–2 | Hand out team URL/token. Run init and brief. Explain student impact and the targets. |
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
