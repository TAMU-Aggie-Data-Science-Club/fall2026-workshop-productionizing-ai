# You are on call

Nimbus is a university study assistant. Your team must diagnose its symptom,
change one setting at a time, and show that service quality has recovered.
Use your own team's service; keep its token private.

## Prepare a terminal

Open Cloud Shell, or use a local terminal with Python. Participants need only
httpx and the CLI; model weights and Google model credentials are unnecessary.

```bash
git clone https://github.com/anh-nguyen28/adsc-workshop.git
cd adsc-workshop
python3 -m venv .participant-venv
.participant-venv/bin/python -m pip install httpx==0.28.1
export PATH="$PWD/.participant-venv/bin:$PWD/cli:$PATH"
nimbus init https://YOUR-TEAM-SERVICE.run.app YOUR-TEAM-TOKEN
```

Use the URL and token your facilitator supplies. `init` starts a new session and
stores the credential in a private `~/.nimbus.json`. Run history is separated by
service URL and session. A later `init` preserves earlier runs but starts new
history. Only one team member should generate benchmark traffic at a time.

## Investigate

```bash
nimbus brief
nimbus baseline
nimbus diagnose
nimbus hypothesis --slice 'the stage or signal you observed' --proof 'your measured evidence'
nimbus set KEY=VALUE
nimbus bench --label 'one change and predicted effect'
nimbus status
nimbus eval
```

Choose the setting and value from your diagnosis. A gated service returns 409
until a hypothesis exists. The gate does not grade the hypothesis or enforce
one change at a time; that is your team's responsibility.

The report's `p95 req` column decomposes one slow request and adds up. The
`p95 each` column contains separate stage percentiles and does not add up.
Compare queue wait, retrieval, generation, token counts, provider retries and
successful/rejected requests. At sixteen requests, percentiles are coarse:
repeat comparable runs before drawing conclusions close to a threshold.

| Setting | Effect |
| --- | --- |
| RESPONSE_CACHE | Reuse an answer for the same assembled prompt; retrieval still runs |
| SEMANTIC_CACHE | Reuse a similar answer before retrieval; check quality carefully |
| SEMANTIC_CACHE_THRESHOLD | Required similarity, from 0 to 1 |
| MAX_TOKENS | Limit generated output |
| SYSTEM_PROMPT | LONG, TRIMMED or VERBOSE instructions |
| RETRIEVE_K | Number of course-note chunks in context |
| ROUTE_EASY | Route short, simple questions to the smaller tier |
| MODEL_TIER | Select small or large for all questions |
| MAX_CONCURRENT | Application admission limit |
| SHED_ABOVE_QUEUE | Reject excess waiting requests |
| PREFIX_CACHE | Application-managed prefix reuse locally; cloud reuse is provider-managed |

## Establish recovery

`nimbus eval` evaluates the same configuration as your latest benchmark and prints
`RECOVERY PASS` only when latency, modeled cost, availability and answer quality
all pass. A changed configuration requires another benchmark. The quality check
is a small keyword-based exercise proxy; inspect real answers too.

A latency/cost `2/2` is not sufficient: rejected requests and poor answers matter.
The report's monthly cost is an exercise projection, not your team's cloud bill.
