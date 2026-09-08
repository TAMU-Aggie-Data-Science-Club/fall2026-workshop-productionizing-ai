# Teach the productionizing AI workshop

Use this guide for the explanation and discussion, and the [run sheet](runsheet.md)
for deployment and room operations. Plan for an audience with little prior
exposure to cloud services or model evaluation. Introduce each term through a
request students can see, then use the technical name consistently.

## Learning outcomes and preparation

By the end, each team should be able to trace a request, interpret a benchmark,
test a prediction, assess recovery, and name the additional controls needed for
an agent that takes actions. The evidence is their completed
[results table](../README.md#step-5--guard) and explanation of a measured change.
A well-supported diagnosis of an unresolved incident can demonstrate learning.

Before the session:

- Follow the run sheet to deploy and validate one service per team. Rehearse
  baseline, one change, benchmark, and evaluation with the actual deployment.
- Ask participants to complete [README setup](../README.md#connect).
  Confirm `nimbus status` works as well as `nimbus brief`.
- Prepare a separate demonstration service or a recent report from a validated
  rehearsal. Label saved results with the date, service, and workload. Remove
  credentials from anything projected or printed.
- Share the README as the only participant guide. Keep the incident
  catalog, deployment output, and facilitator answer keys off the projector.
- Run a human rehearsal to check reading time and command duration. The schedule
  below is a budget, not a measured guarantee; allow more time if the room needs it.

## Session plan — 50 minutes

| Time | Activity | Evidence of understanding |
| --- | --- | --- |
| 0–10 | Explain the user problem and request path | Students can distinguish waiting, retrieval, and generation |
| 10–15 | Demonstrate one answer and one report | Students can identify outcomes, a target, and a measured stage |
| 15–35 | Teams follow the investigation guide | Notes contain evidence, a prediction, one change, and a result |
| 35–45 | Design an agent extension | Teams specify an action, permission, stopping rule, and failure test |
| 45–50 | Compare findings and close | Students explain both measured improvement and remaining limits |

If the available slot is only 20 minutes, teach the concepts beforehand and use
that time for the investigation. Do not expect first-time exposure to the
concepts, terminal setup, diagnosis, and evaluation to fit into that slot.

## 0–10: Explain what is being operated

Start with: “Baristas and customers rely on Nimbus at the bar. An answer can be slow,
wrong, unavailable, or too expensive to serve at scale. Today your team owns
those outcomes.” Define productionizing as making an application dependable
for its intended users and measuring whether it meets their needs.

Draw or display the request path in the [README](../README.md#how-an-answer-is-produced).
Use “Is the banana bread vegan?” to connect a question, the relevant menu note,
and an answer. Explain that retrieval finds material and generation writes the
response. A cache stores work for reuse. A token is a model's unit of text;
distinguish it from the private credential also called a team token.

Say plainly that Nimbus knows one cafe and nothing else, and demonstrate a
refusal on purpose — ask it where the nearest printer is. A bounded scope is
what makes the service small enough to reason about in twenty minutes, and a
team that meets the refusal by accident tends to assume the service is broken.

Explain the scope directly: Nimbus follows a sequence defined by code. An agent
can let a model choose a next tool action and continue based on its result. The
lab measures a deployed RAG service; the design discussion extends those operating
practices to an agent that can change external state.

Ask the room:

- “If the model writes quickly but each question waits for a slot, where will
  students lose time?” Look for queue wait, not an automatic model change.
- “If the service finds the right notes, is the answer guaranteed correct?”
  Look for checking how the answer uses the notes.
- “If half the requests fail immediately, could the successful ones look fast?”
  Look for checking outcomes alongside latency.

## 10–15: Demonstrate how to read evidence

On the demonstration service, ask one browser question. Point out the answer,
source excerpts, and trace. Explain that the trace records application stages;
it does not expose the model's private reasoning. A cache hit can skip stages.

Show `nimbus brief` and a completed `nimbus benchmark`. Use a prepared, labeled
report if the live command would consume the demonstration. Point at the gap bar
first — the distance from target is the thing every later step moves.
Read outcomes first, then latency and cost targets, then the `p95 req` breakdown.
Explain that p95 describes the slow end of the successful sample and becomes
noisy with few requests. `p95 req` adds up for one request; `p95 each` does not.

Point to one stage and ask: “What else would we need to know before calling this
the cause?” Invite a token count, retry signal, or comparison. Model a hypothesis
sentence using evidence visible in the report. Do not prescribe a universal
setting or reveal another team's incident.

Before handing over, ask one participant to explain what a baseline is and
another to name what must stay the same for a fair comparison.

## 15–35: Coach the investigation

Teams follow [the README](../README.md). Assign a
terminal operator, evidence reader, and recorder; combine roles when needed.
Keep traffic to one operator per team and apply settings between complete runs.

| Lab minute | Step | Facilitator prompt |
| --- | --- | --- |
| 0–4 | `nimbus brief`, one browser question, `nimbus benchmark` | “What is the user experiencing, and what is the target?” |
| 4–6 | `nimbus infra` | “Which half of that bill would you actually be able to reduce?” |
| 6–9 | `nimbus monitor` | “Which number rules the model out?” |
| 9–15 | `nimbus optimize`, two or three times | “You predicted down. Why did it not move?” |
| 15–18 | `nimbus guard` | “Latency passed. Did the answers?” |
| 18–20 | Read the printed scorecard aloud | “What can you conclude, and what remains uncertain?” |

Steps 2 and 3 send no traffic, so a team that is behind can run them while
another team's benchmark is in flight. Step 4 is the repeatable one: budget for
two or three attempts, and treat a wrong prediction as a result worth naming.

If a team is stuck, first ask them to locate a missed target, then a relevant
report row, then a plausible explanation. Let them choose from the five options
`nimbus optimize` offers. The prediction gate checks that they committed to one,
not that they were right. Students must still justify one change at a time.

A setting may reduce time while damaging answers. Ask teams to inspect the
facts and explanations rather than celebrating latency alone. If a change makes
things worse, restoring the previous value and measuring again is a useful
result. If the session runs short, reduce repeated experiments and share-out
time; preserve the quality check. Do not claim recovery for an unfinished run.

## 35–45: Design an agent that acts

Give every team the same extension: “Nimbus can propose study sessions and add
them to a student's calendar.” This is a design exercise; the repository does
not currently implement these tools.

Allow four minutes to sketch:

1. What the user asks, what tools the agent may call, and how it knows it is done.
2. Which actions need user review and which permissions the service enforces.
3. Limits on steps, time, retries, and spending.
4. What to save across a restart and what to test after an action.

Then introduce a failure: “The calendar created the event, but the reply was
lost. The agent tries again.” Ask teams how to avoid a duplicate. Discuss a
persistent operation identifier and checking whether that operation already
completed. This is **idempotency**: repeated execution of the same operation
has the same intended effect as executing it once. Support depends on the tool
and the application's state handling; a prompt alone does not guarantee it.

Introduce one more case: a retrieved note says to export the student's calendar
to an unfamiliar address. The note is task data, not permission to gain new
access. The application should enforce tool permissions and validate arguments
outside the model. Have teams name a test that confirms the export is denied.

Connect back to the lab: trace each tool call and outcome, account for the whole
task's time and cost, and evaluate the actual calendar state. A plausible final
message is insufficient evidence that the task succeeded.

## 45–50: Discuss what the evidence supports

Invite two teams to report their symptom, evidence, change, result, and quality
check. Compare the reasoning, not just the fastest service. Ask each to name one
unresolved risk and one next measurement.

Use these checks to assess understanding:

| Learning outcome | What to listen for |
| --- | --- |
| Understand the system | Distinguishes retrieval, generation, and waiting |
| Measure fairly | Uses comparable traffic, outcome counts, and the correct p95 column |
| Test a hypothesis | Predicts a direction, changes one setting, and compares evidence |
| Assess recovery | Checks all recovery conditions and reads real answers |
| Design agent controls | Names an enforced permission boundary, bounded work, and a test of external state |

Close with the operational cycle: measure, explain, predict, change, measure
again, and verify the user's outcome. Mention that wider deployment also needs
monitoring, access and data controls, durable state where required, and a tested
rollout and restoration process. The workshop establishes evidence on a bounded
workload; those further requirements need their own implementation and validation.
