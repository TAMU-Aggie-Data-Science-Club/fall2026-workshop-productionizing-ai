# Facilitator troubleshooting

Use this with the [run sheet](runsheet.md). The session uses predeployed team
services and the participant CLI. Keep setup failures separate from the incident
students are meant to investigate.

| Problem | Response |
| --- | --- |
| Terminal, Git, Python, or dependency setup fails | Move the operator to Cloud Shell, a working teammate's terminal, or a prepared facilitator terminal; investigate setup separately |
| `nimbus` is not found | Enter the repository directory and repeat the `export PATH=...` line from the README setup |
| Service health or connection fails | Confirm that team's URL and service readiness before starting the investigation |
| `status` rejects the token or baseline needs authenticated `/metrics` | Confirm the URL/token pair; `init` alone does not validate the credential |
| `set` returns 409 | Have the team record a hypothesis with measured evidence, then retry the intended setting |
| Every request fails or returns empty text | Stop the investigation and rerun authenticated service preflight; inspect model access and output behavior |
| Evaluation reports configuration changed | Wait for all traffic and changes to finish; benchmark the current settings, then evaluate again |
| The service restarts | Inspect settings, restore the intended incident through the facilitator workflow if needed, and begin a new participant session and baseline |
| A command is taking too long | Check service health and provider errors; reduce repeat experiments or share-out time while preserving evaluation |

Do not send participants through full local model installation during the cloud
activity. Keep the same traffic profile before and after a change. Changing
request count or concurrency mid-comparison makes it a different experiment.

## Connectivity is unavailable

Before the event, save and print a recent validated baseline, a corresponding
changed-configuration report, and quality evidence for a demonstration service.
Include the configuration and workload, and remove tokens. Keep the second
report hidden until teams have written a prediction.

Use those reports to practice interpretation and comparison. State that students
are analyzing recorded evidence and cannot establish live recovery. If no such
materials are available, use the clearly labeled arithmetic example in the
README and the agent design exercise. Do not present historical incident
panels or invented quality scores as current measurements.

## A team finishes early

Ask them to explain a remaining uncertainty, inspect another answer against its
sources, or design a failure test for the calendar-agent extension. An additional
load experiment is useful only after they save the original evidence and identify
it as a new workload; it should not replace the original recovery comparison.

## Someone challenges a result

Use the distinction between observed data and assumptions. Latency and outcomes
come from that run. Monthly cost is an exercise projection. The quality score
comes from keyword checks. Small samples, cached answers, and provider variation
limit conclusions. Inspect the record together and state what remains unknown.
