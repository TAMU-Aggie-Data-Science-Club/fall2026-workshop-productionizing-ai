# Nimbus — operate a live AI service

Nimbus is a small retrieval-augmented question-answering service. It is
deployed, it is serving real traffic, and it is missing its targets. Your team
is on call.

**Productionizing** means making an application dependable for its users and
proving with measurements that it actually is. This activity walks the five
stages of that work, one command each.

| | Stage | Command | What it does |
| --- | --- | --- | --- |
| 1 | Model selection | `nimbus benchmark` | Measures the service and prices the model you are running |
| 2 | Infrastructure | `nimbus infra` | Shows where it runs and what the hosting costs |
| 3 | Monitoring | `nimbus monitor` | Attributes the latency to a stage |
| 4 | Scaling | `nimbus optimize` | Predict, change one setting, measure again |
| 5 | Safety | `nimbus guard` | Checks the answers survived the change |

Steps 2 and 3 send no traffic, so they are free to repeat. Step 4 is meant to be
repeated; three attempts is normal and a wrong one costs about forty seconds.

**You do not have to fix the incident to succeed.** A diagnosis you can support
with evidence is the deliverable.

---

## What you need

No prior experience with cloud services, machine learning, or model evaluation
is assumed. You do not install a model, use Docker, or need cloud credentials.

- A **web browser**
- A **terminal** with Git and Python 3.10+
- Your team's **service URL** and **team token**, from your facilitator

If you have any doubt about your terminal, use
[Google Cloud Shell](https://shell.cloud.google.com) — Git and Python are
already installed and it behaves identically for everyone. On Windows, use Cloud
Shell or WSL.

The team token permits reading and changing your team's settings. Keep it
private. Use the same terminal for the whole activity, and **only one person per
team should send traffic** — teammates read the evidence and take notes.

---

## Set up your terminal

Run these one line at a time, waiting for each to finish.

```bash
git clone https://github.com/anh-nguyen28/adsc-workshop.git
cd adsc-workshop
python3 -m venv .participant-venv
.participant-venv/bin/python -m pip install httpx==0.28.1
export PATH="$PWD/.participant-venv/bin:$PWD/cli:$PATH"
```

The virtual environment keeps the one dependency the CLI needs off your system
Python. The `export` line puts `nimbus` on your path for this terminal only.

### Verify the setup

```bash
nimbus --help
```

You should see something like:

```
usage: nimbus [-h]
              {init,brief,status,eval,baseline,bench,benchmark,infra,monitor,optimize,guard,diagnose,requests,hypothesis,set} ...

Nimbus — the incident you are on call for.

FIVE STEPS, in order. One per stage of putting an AI service into production:

    nimbus init <url> <token>   point this terminal at your team's service
    nimbus benchmark            1. measure it, and price the model choice
    nimbus infra                2. where it runs, and what that costs
    nimbus monitor              3. where the time actually goes
    nimbus optimize             4. predict, change ONE thing, measure again
    nimbus guard                5. check the answers survived
```

| Result | Meaning |
| --- | --- |
| The usage block above | Setup worked. Continue. |
| `nimbus: command not found` | The `export PATH=...` line did not run, or you are in the wrong directory. `cd` into the repository and run it again. |
| `No module named ...` | The virtual environment was not used. Re-run the `venv` and `pip install` lines. |

---

## Connect to your team's service

```bash
nimbus init https://YOUR-TEAM-SERVICE.run.app YOUR-TEAM-TOKEN
```

`init` saves the URL and token to a private `~/.nimbus.json`, starts a new run
session, and immediately calls the service's `/health` endpoint to check both
values before you rely on them.

**Success** — you should see:

```
Pointed at https://nimbus-team-a-h7zuiuiwtq-uc.a.run.app
Service is up.  Try:  nimbus brief
```

**Failure** — a health warning instead of the second line:

```
Pointed at https://nimbus-team-a-h7zuiuiwtq-uc.a.run.app
WARNING: /health returned 404. Check the URL with your facilitator.
```

| Result | What to do |
| --- | --- |
| `Service is up.` | Continue to `nimbus brief`. |
| `WARNING: /health returned ...` | The URL is wrong or the service is not running. Check it with your facilitator. |
| `That token was not accepted` on a later command | The URL and token belong to different teams. Re-run `init` with a matching pair. |
| A connection error or timeout | Network or service problem. Ask a facilitator. |

Run history is stored locally per service and per session. Running `init` again
starts a fresh session, so do it once.

### Read your incident

```bash
nimbus brief
```

Prints the symptom that was reported, who it affects, and the three numbers you
are judged against. It sends no traffic.

You should see something like:

```
  INCIDENT — EVERYONE IS WAITING

  WHAT WAS REPORTED
    Every student is waiting, and it is worse at busy times.

  WHO IT AFFECTS
    Answers that used to arrive in seconds now take most of a minute.

  TARGETS
    p95 latency    at most 1.5 s
    monthly cost   at most $1,500
    answer quality at least 80%

  YOUR TASK
    Attribute the latency before you change anything. The report names the
    largest contributor; it will not tell you what to do about it.

  Start with:  nimbus baseline
```

**You are connected when `brief` prints your incident and your targets.** Every
team gets a different incident, so the title you see will differ from the one
above.

### Ask it something first

Open your team's service URL in a browser and ask a question. The page shows the
answer, which retrieved chunks grounded it, and where that single request spent
its time.

Nimbus answers **only** from the notes it was given at build time, and says so
when a question falls outside them. That is correct behaviour, not a broken bot:
it is instructed to ground every answer in its own notes rather than in general
knowledge, because a confident answer from general knowledge would be wrong for
this deployment. Step 5 is where that rule gets tested.

Ask one question in the browser before you start step 1.

### How an answer is produced

```mermaid
flowchart LR
    Q[Question] --> W[Wait for capacity]
    W --> R[Retrieve notes]
    R --> P[Assemble instructions, notes, and question]
    P --> M[Select model and generate]
    M --> A[Stream answer back]
```

**Retrieval** finds relevant passages, called chunks. **Generation** uses the
assembled input, called a prompt, to write the answer. Combining the two is
**retrieval-augmented generation (RAG)**. A **cache** stores previous work for
reuse — Nimbus can check for a *similar* cached question before retrieval, or an
*exact* cached prompt after assembly, so which cache you enable decides which
stages get skipped.

A model **token** is a unit of text, roughly a word or part of one. It has
nothing to do with your team token, which is a credential.

---

## How to read a benchmark report

Every measuring command prints the same report. Read it once here and the five
steps become skimmable.

```
NIMBUS BENCHMARK - run 1  baseline
====================================================================
requests     11 ok · 5 shed · 0 failed      duration  8.5 s
throughput   1.3 req/s · 39 output tok/s

latency      median     5.23 s
             p95        5.76 s   SLO 1.50 s   FAIL
             slowest    5.76 s
TTFT         p95        5.33 s
             note: with 11 requests, "p95" is the 1st-slowest
             request, not a true percentile. Repeat runs vary ~12%.
             9 of 11 request(s) exceeded the 1.5s target

             ── where the time went ─────────────────────────────
                      p95 req  p95 each
  client + network     0.25 s         -  █
  app queue wait       4.86 s     4.86s  ████████████████████████
  cache lookup         0.00 s     0.00s  ▏
  retrieve             0.05 s     0.10s  ▏
  assemble             0.00 s     0.00s  ▏
  generate             0.59 s     2.31s  ███
  other (app)          0.00 s         -  ▏
                     --------
  sum of rows          5.76 s   end-to-end 5.76 s · residual +0.0%

             ── how the model behaved ───────────────────────────
  provider retries        0           upstream status: none
  provider           google

             ── work per request ────────────────────────────────
  input tokens          222 avg      baseline 226 · normal
  output tokens          30 avg      baseline 31 · normal
  cache hit rate         0%
  prefix-cached          0%          0 of 2,445 input tokens

cost         $0.142 / 1k requests
             $638 tokens + $140 Cloud Run estimate
             $778 / month @ 150,000/day   budget $1,500   PASS

--------------------------------------------------------------------
VERDICT  1/2 constraints met
availability 69% successful · FAIL
quality      NOT VERIFIED / FAIL
RECOVERY     NOT PROVEN
READ THIS FIRST
  Largest contributor to the p95 request: APP QUEUE WAIT (84%).
  Then: generate 10%, client + network 4%.
  Below 1% of the budget: retrieve, other (app), cache lookup, assemble.
  At baseline: tokens in, tokens out.
```

| Block | What it tells you |
| --- | --- |
| `requests` | `ok` were served, `shed` were rejected before work started, `failed` errored. Anything but `0 shed · 0 failed` is an availability problem. |
| `latency` | `p95` is the slow end of successful requests, compared against the SLO. |
| `where the time went` | The rows add up to one request, so a percentage share is real. This is your attribution. |
| `how the model behaved` | Provider retries and upstream errors. Zero retries rules the provider out. |
| `work per request` | Token counts against a calibrated `baseline`. `normal` means this is *not* your problem — ruling a suspect out is half a diagnosis. |
| `cost` | Tokens plus hosting, projected to a month at the scenario's traffic. |
| `VERDICT` | How many of the two computable constraints you met. |
| `READ THIS FIRST` | The largest contributor, named for you. It does **not** name the setting that fixes it. |

**Pass and fail markers:**

| Marker | Meaning |
| --- | --- |
| `PASS` | Measurement is inside its target. |
| `FAIL` | Measurement is outside its target. |
| `MARGINAL` | Inside the ~12% run-to-run noise band. Run it again before believing it. |
| `NOT VERIFIED / FAIL` | Not measured yet — quality stays `NOT VERIFIED` until `nimbus guard` runs. |
| `RECOVERY NOT PROVEN` | At least one of the five recovery conditions is unmet. |

> **On noise.** With 16 requests, "p95" is the second-slowest request, not a true
> percentile, and repeat runs vary by about **12%**. Treat any difference inside
> that band as noise, not as a result.

---

## Step 1 — Benchmark

```bash
nimbus benchmark
```

Warms the service, sends a fixed and repeatable set of requests, and measures the
result. This is your **baseline** — the number every later run is compared
against. Change nothing before you run it. It then prices each model tier against
the tokens this run actually used, sending no extra traffic.

Takes about 30 seconds. You should see something like:

```
  STEP 1 of 5 — BENCHMARK
  Measure before you touch anything. This is the number you will
  be judged against for the rest of the activity.

warming the service (these requests are discarded)...
sending 16 requests at 4.0/s (up to 8 at once)...

  ── are you meeting your targets? ───────────────────────────

  p95 latency        5.76 s   target 1.50 s     ▲ 4.26 s OVER  FAIL
  ├─────────┼────────────────────────▲─────────┤
            target                   5.76 s

  cost                 $778   target $1,500     ▼ $722 under  PASS
  ├──────────────────▲───────────────┼─────────┤
                     $778            target

  ── what would each model cost? ─────────────────────────────

    tier    model                        $/month       vs now
    large   gemini-2.5-flash                778            —  <- now
    small   gemini-2.5-flash-lite           294         -484

    Cost is arithmetic. ANSWER QUALITY IS NOT IN THIS TABLE,
    because a run cannot tell you it. Only `nimbus guard` can.

  ── the five steps ──────────────────────────────────────────
   ▸ 1  benchmark   measure it, and price the model
     2  infra       see where it runs and what that costs
     3  monitor     find where the time goes
     4  optimize    change one thing and re-measure
     5  guard       check the answers survived

  Next:  nimbus infra
```

Each bar shows the measurement, the target, and the distance between them. `▲`
is where you are; `┼` is the target.

| Result | Meaning |
| --- | --- |
| Both bars `PASS` | Latency and cost are inside target — but quality is still unverified, so this is not recovery. |
| Either bar `FAIL` | You have a real gap. Its size is the number in the `▲ ... OVER` column. |
| `warming the service` never finishes | The service is cold or unreachable. Wait, then ask a facilitator. |
| Many `shed` or `failed` requests | An availability problem, which no latency fix alone will clear. |

The tier table is the model-selection lesson: it prices the alternative, and it
deliberately leaves quality out, because a benchmark cannot measure quality.

---

## Step 2 — Infra

```bash
nimbus infra
```

Sends no traffic. Reads the deployment as it already is: platform, revision,
which models it can reach, how many requests it will handle at once, how many
note chunks are indexed — and the part that is otherwise invisible, the monthly
bill split into tokens and hosting.

You should see something like:

```
  STEP 2 of 5 — INFRA
  Somebody is paying to keep this running. This step sends no
  traffic; it only reads what is already there.

  ── where nimbus runs ───────────────────────────────────────

    platform          Google Cloud Run
    service           nimbus-team-a
    revision          nimbus-team-a-00001-xk5
    model (large)     gemini-2.5-flash
    model (small)     gemini-2.5-flash-lite
    capacity          2 requests at once
    notes             128 chunks indexed

  ── your monthly bill has two halves ────────────────────────

    tokens to the model provider         638    82%
                                    ████████████████████
    keeping the server on                140    18%
                                    ████
                                    --------
    total per month                      778

    You pay the second line whether or not anyone asks a question.
```

| Result | Meaning |
| --- | --- |
| The two panels above | Working as intended. |
| `Run \`nimbus benchmark\` first ...` | Step 2 prices your last run. Run step 1 first. |
| `That token was not accepted.` | The token does not match this service. Re-run `init`. |
| `Could not read the service (503)` | The service is unhealthy. Ask a facilitator. |

`capacity` is worth reading against the traffic in step 1: a service admitting
2 requests at a time while the benchmark offers 8 will queue, and the queue will
dominate everything else.

---

## Step 3 — Monitor

```bash
nimbus monitor
```

Sends no traffic — it re-reads the run you already took, so run it as often as
you like. A total tells you there is a problem; a breakdown tells you where. It
also lists what is sitting at its calibrated normal, because ruling a suspect out
is half of a diagnosis.

You should see something like:

```
  STEP 3 of 5 — MONITOR
  A total tells you there is a problem. A breakdown tells you where.
  This step sends no traffic.

  ── where the 5.76 s goes ───────────────────────────────────

    wait for a slot     4.86 s  ████████████████████  84%
    write the answer    0.59 s  ██                    10%
    network             0.25 s  █                      4%
    find the notes      0.05 s  █                      1%
                                below 1%: check the cache, build the prompt, other app work

    These rows add up to one request, so a share is real: wait for a slot
    is 84% of it.

  ── already normal — not your problem ───────────────────────

    tokens in            222   baseline 226    ✓
    tokens out            30   baseline 31     ✓
    provider retries       0   baseline 0      ✓

    tokens in, tokens out at baseline — the model is doing a normal
    amount of work. Whatever is slow, it is not the amount of text.
    9 of 11 requests missed the 1.50 s target.
```

| Row shows | Read it as |
| --- | --- |
| `wait for a slot` dominant | Requests are queueing before any work starts — a capacity or admission problem. |
| `write the answer` dominant | Generation is the cost — look at output length, model tier, or output caps. |
| `find the notes` dominant | Retrieval is the cost — look at how much is being retrieved. |
| `network` dominant | Time outside the service. Usually a cold container or a distant client. |
| `✓` next to a token row | That value is at its calibrated normal. Rule it out. |
| `+422%` (or similar) next to a token row | That value has moved. This is a lead. |

**This step will not tell you which setting to change.** Naming the lever would
end the exercise. Attribution is what it gives you; the diagnosis is your job.

---

## Step 4 — Optimize

```bash
nimbus optimize
```

Offers five changes, takes your **prediction before applying anything**, writes
your reasoning into a sentence you can copy into your notes, applies the setting,
clears the cache, and re-measures with **the same traffic**.

The prediction is the entire point of the step and it costs one keystroke.

```
  STEP 4 of 5 — OPTIMIZE
  Change one thing. Say what you expect first, then find out.

  Pick ONE thing to change:

    1  Reuse answers to similar questions
       Checks whether a similar question was already answered, before
       looking anything up.
       SEMANTIC_CACHE: off → on

    2  Use the cheaper, faster model
       Sends every question to the small model instead of the large one.
       MODEL_TIER: large → small

    3  Look up fewer notes per question
       Puts less material into each prompt.
       RETRIEVE_K: 3 → 1

    4  Write shorter answers
       Caps how much the model is allowed to generate.
       MAX_TOKENS: 32 → 16

    5  Handle more questions at once
       Raises how many requests may compute simultaneously.
       MAX_CONCURRENT: 2 → 8

  Your pick (1-5) > 5

  You chose: Handle more questions at once
  That sets MAX_CONCURRENT to 8.

  Predict: does p95 latency go (u)p, (d)own or stay the (s)ame? > d

  Recorded — this is your writeup sentence, copy it:
    "wait for a slot dominates (4.86s of a 5.76s p95 request (84%)).
     Setting MAX_CONCURRENT=8 should make p95 go down."

  Applied: MAX_CONCURRENT  2 → 8
  (the cache was cleared, so this is measured fresh)

sending 16 requests at 4.0/s (up to 8 at once)...

  ── did it move the way you said? ───────────────────────────

  p95 latency        1.06 s   target 1.50 s     ▼ 0.44 s under  PASS
  ├────────────────────────▲─────────┼─────────┤
                           1.06 s    target

  cost                 $417   target $1,500     ▼ $1,083 under  PASS
  ├──────────▲───────────────────────┼─────────┤
             $417                    target

    p95   5.76 s → 1.06 s (-82%)
    you predicted DOWN · it went DOWN · CORRECT

    ✓ LATENCY PASS — but fast is not the same as correct.
      Check the answers:  nimbus guard
```

| Verdict line | Meaning | What to do |
| --- | --- | --- |
| `CORRECT` | The number moved the way you said, by more than the noise band. | Keep the change and go to step 5. |
| `WRONG` | It moved the other way. | **A wrong prediction is a result.** It rules the setting out. Write down why you expected otherwise, then try another. |
| `TOO CLOSE TO CALL` | It moved your way, but by less than the ~12% noise. | The measurement cannot tell them apart yet. Run it again. |
| `it went SAME` | Nothing moved outside the noise. | Real information: this setting does not touch whatever is slow. |
| `Still over.` | Latency is not yet inside target. | Run `nimbus optimize` again — restoring the previous setting first if this one made things worse. |

Change **one** thing at a time, or you will not know which one did it. If a
change makes things worse, run the step again and put it back. Repeat as often as
time allows.

---

## Step 5 — Guard

```bash
nimbus guard
```

Asks 36 real questions — 24 fact-finding, 12 reasoning — makes real model calls,
and reads the answers. Takes about a minute; let it finish. It then prints your
scorecard, already filled in from your own runs.

**Fast and cheap is not the same as working.** `RECOVERY PASS` requires all five
conditions below, not two of them.

You should see something like:

```
  STEP 5 of 5 — GUARD
  Fast and cheap is not the same as working. This asks 36 real
  questions and reads the answers.

  asking 36 questions (this makes real model calls)...

  ── did the answers survive? ────────────────────────────────

    fact-finding        100%
    reasoning            83%
    overall              94%   bar 80%   PASS

    This is a keyword check, not a grader. A wrong answer can
    contain the right words. Read a few yourself in the browser.

  ── your scorecard — copy this into your notes ──────────────

                            before            after
    setting changed         —                 MAX_CONCURRENT=8
    requests / rate / conc  16/4.0/8          16/4.0/8
    ok / shed / failed      11/5/0            16/0/0
    p95 latency             5.76 s            1.06 s
    largest stage           wait for a slot   write the answer
    cost / month            $778              $417
    answer quality          not measured      94%

    ✓ latency target
    ✓ cost budget
    ✓ every request served
    ✓ answer quality
    ✓ config held still

    RECOVERY  PASS

    You predicted p95 would go DOWN; it went DOWN.
```

**The five recovery conditions:**

| Condition | Passes when |
| --- | --- |
| `latency target` | p95 is at or under the SLO. |
| `cost budget` | Projected monthly cost is at or under budget. |
| `every request served` | Zero shed and zero failed requests. |
| `answer quality` | Eval score is at or above the quality bar. |
| `config held still` | Nothing changed between the measurement and the eval. |

**Failure modes:**

| What you see | What it means |
| --- | --- |
| `RECOVERY  NOT PROVEN` + a `✗` row | That condition failed. Say which one, and what you would measure next. `nimbus guard` also exits non-zero. |
| `The configuration changed after your last measurement` | A setting moved since your last run. Re-run `nimbus benchmark`, then `nimbus guard`, so both describe the same service. |
| `Quality evaluation failed` | The eval could not complete. Recovery stays unverified; ask a facilitator. |
| High score, wrong answers | Expected. The check looks for keywords, so a wrong answer can contain the right words and a correct paraphrase can miss them. Read a few yourself. |

Read several answers in the browser yourself and check each against the retrieved
notes shown alongside it: does it match the notes, does it apply them correctly
rather than restating them, does it pass on a caution the notes contain instead
of reassuring, and does it decline a question the notes do not cover?

### Write it up

Copy the scorecard into your notes and explain:

> what users experienced → what you measured → what you changed → what happened →
> whether the answers stayed useful → what is still uncertain

If recovery failed, say **which condition** failed and **what you would measure
next**. That is a complete answer.

---

## Driving it directly

The five steps are wrappers. Every measurement underneath is available on its
own:

```
nimbus baseline · bench · diagnose · requests · hypothesis · set · eval · status
```

```bash
nimbus requests --slow
```

The most useful of these. Prints the individual requests behind your p95 and says
whether the slow ones were all slow for the same reason.

---

## Setting reference

Use the setting your evidence points at. These are options to investigate, not a
checklist to work through. Booleans accept `true` or `false`.

| Setting | Values | Effect, and the tradeoff to check |
| --- | --- | --- |
| `SYSTEM_PROMPT` | `LONG`, `TRIMMED`, `VERBOSE` | Selects the instruction block. Check input size *and* whether required answer behaviour is preserved. |
| `RETRIEVE_K` | Integer 0–20 | How many note chunks enter the prompt. Fewer may cut work but omit needed facts. |
| `MAX_TOKENS` | Integer 1–1024 | Caps generated output. A low cap truncates answers, or leaves no visible text at all on a reasoning model. |
| `MODEL_TIER` | `small`, `large` | Default tier. `small` sends every question there, so check the difficult ones. |
| `ROUTE_EASY` | Boolean | With a large default, routes short pattern-matched questions to the small tier. The rule can misjudge difficulty. |
| `RESPONSE_CACHE` | Boolean | Reuses an answer for an identical assembled prompt. Retrieval still runs. |
| `SEMANTIC_CACHE` | Boolean | Reuses an answer to a *similar* question, before retrieval. Similarity can hide a meaningful difference. |
| `SEMANTIC_CACHE_THRESHOLD` | Number 0–1 | Required similarity. Lowering it accepts more matches, including wrong ones. |
| `MAX_CONCURRENT` | Integer 1–64 | Simultaneous work inside Nimbus. Raising it can move the pressure to the model provider. |
| `SHED_ABOVE_QUEUE` | Integer ≥0; `SHED_ABOVE_QUEUE=` clears | Rejects requests beyond the waiting limit. Check rejection counts alongside latency. |
| `PREFIX_CACHE` | Boolean | Requests reuse of static prompt computation in the local adapter. Cloud reuse is provider-managed, so this does not guarantee a cloud benefit. |

Apply one with `nimbus set KEY=VALUE`, then re-measure with `nimbus bench`.

---

## If something goes wrong

| What you see | What to do |
| --- | --- |
| Git, Python, or environment setup fails | Use Cloud Shell or a teammate's working terminal; ask a facilitator to check setup. |
| `nimbus: command not found` | `cd` into the repository and repeat the `export PATH=...` line. |
| A message asking you to run `nimbus init` | Run `init` on this machine with your team's URL and token. |
| Health warning or connection error | Check the service URL with your facilitator. |
| `That token was not accepted` | The URL and token belong to different teams. |
| `No measurement yet` | Run `nimbus benchmark` first — steps 2 to 5 all read that measurement. |
| `The configuration changed after your last measurement` | A setting moved. Re-run `nimbus benchmark`, then `nimbus guard`. |
| Nimbus says a question is outside what it covers | Expected. Ask about something the indexed notes contain. |
| Empty answers, or every request fails | Ask a facilitator to check service readiness and model access. |

Settings, caches, and predictions live in service memory and are lost if the
service restarts. If that happens, have a facilitator check the service, inspect
`nimbus status`, and start again from `nimbus benchmark` before comparing
anything — **a run taken under one configuration cannot be compared against a run
taken under another.**

---

## Applying the lesson to an agent

Suppose Nimbus could also propose study sessions and create calendar events. A
**tool** is an operation the application exposes to the model, such as reading a
calendar or creating an event. Discuss what that extension would need:

| Concern | What the agent would need |
| --- | --- |
| Permissions | Access only to authorized calendars, enforced outside the model |
| Valid actions | Checked dates and tool arguments, and user review before events are created |
| Bounded work | Limits on steps, elapsed time, retries, and spending |
| Safe retries | A way to identify an already-completed operation so a lost reply does not duplicate an event |
| Persistent state | Saved progress, so a restart does not lose track of completed actions |
| Untrusted content | Instructions found in notes or tool results treated as data, never as authority |
| Evaluation | Tests over actual calendar state, denied actions, and partial failures — not just the final answer |
| Monitoring and rollout | Traced tool outcomes, problem detection, gradual release, and a way back to a previous version |

These are design considerations for an extension; Nimbus does not implement a
calendar agent. Its public chat endpoint and in-memory settings are workshop
choices. A wider deployment would also need user authentication, data and abuse
controls, and ongoing monitoring. **A passing lab run is evidence for the tested
workload, not for every future user or task.**

---

## For facilitators

Setup, deployment, incident injection, and the answer key live in
`facilitators/` — see `facilitators/runsheet.md` and
`facilitators/teaching_guide.md`. Participants should not read that directory.

Local development:

```bash
make setup     # virtualenv, pinned dependencies, build the note index
make check     # unit tests, compile checks, dependency check
make serve     # run the service locally on :8000
make bench     # benchmark whatever URL is in $URL
```
