# Nimbus — operate a live AI service

Nimbus is a small retrieval-augmented question-answering service: ask it for a
drink order and it answers with the recipe. It is deployed, it is serving
traffic, and it is missing its targets. Your team is on call.

**Productionizing** means making an application dependable for its users and
proving with measurements that it is. This activity walks the five stages of
that work, one command each.

| | Stage | Command | What it does |
| --- | --- | --- | --- |
| 1 | Model selection | `nimbus benchmark` | Measures the service, prices the model |
| 2 | Infrastructure | `nimbus infra` | Where it runs, what hosting costs |
| 3 | Monitoring | `nimbus monitor` | Attributes the latency to a stage |
| 4 | Scaling | `nimbus optimize` | Predict, change one setting, measure again |
| 5 | Safety | `nimbus guard` | Checks the answers survived |

Steps 2 and 3 send no traffic, so repeat them freely. Step 4 is meant to be
repeated — three attempts is normal, and a wrong one costs about forty seconds.

**You do not have to fix the incident to succeed.** A diagnosis you can support
with evidence is the deliverable.

## What you need

No prior experience with cloud services, machine learning, or model evaluation
is assumed. You do not install a model, use Docker, or need cloud credentials.

- A web browser
- A terminal with Git and Python 3.10+
- Your team's **service URL** and **token**, from your facilitator

If you have any doubt about your terminal, use
[Google Cloud Shell](https://shell.cloud.google.com) — Git and Python are
already there and it behaves identically for everyone. On Windows, use Cloud
Shell or WSL.

Keep the token private; it can read and change your team's settings. Use one
terminal for the whole activity, and **only one person per team should send
traffic** — teammates read the evidence and take notes.

---

## Setup

Run these one line at a time, waiting for each to finish.

```bash
git clone https://github.com/anh-nguyen28/adsc-workshop.git
cd adsc-workshop
python3 -m venv .participant-venv
.participant-venv/bin/python -m pip install httpx==0.28.1
export PATH="$PWD/.participant-venv/bin:$PWD/cli:$PATH"
```

The virtual environment keeps the CLI's one dependency off your system Python.
The `export` line puts `nimbus` on your path for this terminal only.

Verify it:

```bash
nimbus --help
```

```
usage: nimbus [-h]
              {init,brief,status,eval,baseline,bench,benchmark,infra,monitor,optimize,guard,diagnose,requests,hypothesis,set} ...

Nimbus — the incident you are on call for.

FIVE STEPS, in order. One per stage of putting an AI service into production:

    nimbus init <url> <token>   point this terminal at your team's service
    nimbus benchmark            1. measure it, and price the model choice
    ...
```

- **Works** — you get the usage block above.
- **`nimbus: command not found`** — you are outside the repository, or the
  `export` line did not run. `cd` back in and repeat it.

---

## Connect

```bash
nimbus init https://YOUR-TEAM-SERVICE.run.app YOUR-TEAM-TOKEN
```

Saves the URL and token to a private `~/.nimbus.json`, starts a run session, and
calls `/health` to check both values before you rely on them.

```
Pointed at https://nimbus-team-a-h7zuiuiwtq-uc.a.run.app
Service is up.  Try:  nimbus brief
```

- **Works** — the second line says `Service is up.`
- **`WARNING: /health returned 404`** — the URL is wrong or the service is down.
  Check it with your facilitator.

Run `init` once. Doing it again starts a fresh session and splits your history.

### Read your incident

```bash
nimbus brief
```

Prints the reported symptom, who it affects, and the three numbers you are
judged against. Sends no traffic.

```
  INCIDENT — EVERYONE IS WAITING

  WHAT WAS REPORTED
    Every customer is waiting, and it is worse at busy times.

  WHO IT AFFECTS
    Answers that used to arrive in seconds now take most of a minute.

  TARGETS
    p95 latency    at most 1.5 s
    monthly cost   at most $1,500
    answer quality at least 80%

  YOUR TASK
    Attribute the latency before you change anything. The report names the
    largest contributor; it will not tell you what to do about it.
```

**You are connected when `brief` prints your incident and your targets.** Every
team gets a different incident, so your title will differ from the one above.

---

## Look at it first

Open your service URL in a browser and ask a question. The page shows the
answer, which retrieved chunks grounded it, and where that request spent its
time.

Nimbus covers exactly one thing: the recipe notes it was built with — hot
drinks, cold drinks, and the build standards that apply across both. Try both
sides of that boundary.

| Ask | What should happen |
| --- | --- |
| *What is in a caramel macchiato?* | Gives the build, and shows the chunk it used |
| *Explain how Q-learning works.* | Declines — reinforcement learning is not in the notes |

The second one is the interesting case. A model has plenty to say about
Q-learning; it just has no *source* for it here. Left unconstrained it would
produce a fluent, confident answer anyway — that is **hallucination**, and it is
most dangerous where it is least visible, because a wrong answer reads exactly
like a right one. **Grounding** is the constraint that turns a gap in the notes
into "I don't cover that" instead of an invention. Refusing is the feature.

Remember that at step 4: four of its five changes make Nimbus faster by giving
it *less* to work with, and each can quietly turn a grounded answer into a guess
while latency and cost both improve. Step 5 is what catches that.

Ask one question of each kind before you start step 1.

### How an answer is made

```mermaid
flowchart LR
    Q[Question] --> W[Wait for capacity]
    W --> R[Retrieve notes]
    R --> P[Assemble instructions, notes, and question]
    P --> M[Select model and generate]
    M --> A[Stream answer back]
```

**Retrieval** finds relevant passages, called chunks. **Generation** uses the
assembled input, called a prompt, to write the answer. Together they are
**retrieval-augmented generation (RAG)**. A **cache** reuses previous work —
Nimbus can match a *similar* question before retrieval, or an *exact* prompt
after assembly, so which cache you enable decides which stages get skipped.

A model **token** is a unit of text, roughly a word or part of one. Unrelated to
your team token, which is a credential.

---

## Reading a report

`nimbus baseline`, `bench` and `diagnose` all print the same report. Read it
once here and the five steps become skimmable.

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
```

| Block | What it tells you |
| --- | --- |
| `requests` | `ok` served, `shed` rejected before work started, `failed` errored. Anything but `0 shed · 0 failed` is an availability problem |
| `latency` | `p95` is the slow end of successful requests, against the SLO |
| `where the time went` | Rows add up to one request, so a share is real. This is your attribution |
| `how the model behaved` | Retries and upstream errors. Zero retries rules the provider out |
| `work per request` | Token counts against a calibrated `baseline`. `normal` means *not* your problem — ruling a suspect out is half a diagnosis |
| `cost` | Tokens plus hosting, projected to a month at the scenario's traffic |
| `READ THIS FIRST` | Names the largest contributor. It does **not** name the setting that fixes it |

Verdict markers: **`PASS`** inside target · **`FAIL`** outside it ·
**`MARGINAL`** inside the noise band, run it again · **`NOT VERIFIED`** not
measured yet, which is where quality stays until step 5 ·
**`RECOVERY NOT PROVEN`** at least one of the five recovery conditions is unmet.

> **On noise.** With 16 requests, "p95" is the second-slowest request, not a true
> percentile, and repeat runs vary by about **12%**. Any difference inside that
> band is noise, not a result.

---

## Step 1 — Benchmark

```bash
nimbus benchmark
```

Warms the service, sends a fixed and repeatable set of requests, and measures.
This is your **baseline** — the number every later run is compared against, so
change nothing before you run it. It then prices each model tier against the
tokens this run actually used, sending no extra traffic. Takes about 30 seconds.

```
  STEP 1 of 5 — BENCHMARK

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

Each bar shows measurement, target, and the distance between them: `▲` is where
you are, `┼` is the target. Every step ends with that progress footer; the
examples below omit it.

- **Both bars `PASS`** — latency and cost are inside target, but quality is
  still unverified, so this is not recovery.
- **Either bar `FAIL`** — you have a real gap, and the `▲ ... OVER` column is
  its size.
- **Many `shed` or `failed` requests** — an availability problem, which no
  latency fix alone will clear.

The tier table is the model-selection lesson. It prices the alternative and
deliberately omits quality, because a benchmark cannot measure quality.

## Step 2 — Infra

```bash
nimbus infra
```

Sends no traffic. Reads the deployment as it already is — platform, revision,
reachable models, how many requests it handles at once, how many note chunks are
indexed — plus the otherwise invisible part: the bill split into tokens and
hosting.

```
  STEP 2 of 5 — INFRA

  ── where nimbus runs ───────────────────────────────────────

    platform          Google Cloud Run
    service           nimbus-team-a
    revision          nimbus-team-a-00001-xk5
    model (large)     gemini-2.5-flash
    model (small)     gemini-2.5-flash-lite
    capacity          2 requests at once
    notes             50 chunks indexed

  ── your monthly bill has two halves ────────────────────────

    tokens to the model provider         638    82%
                                    ████████████████████
    keeping the server on                140    18%
                                    ████
                                    --------
    total per month                      778

    You pay the second line whether or not anyone asks a question.
```

If the second panel is replaced by a prompt to run `nimbus benchmark` first,
that is because step 2 prices your last run — so take one.

Read `capacity` against the traffic in step 1. A service admitting 2 requests at
a time while the benchmark offers 8 will queue, and the queue will dominate
everything else.

## Step 3 — Monitor

```bash
nimbus monitor
```

Sends no traffic — it re-reads the run you already took, so run it as often as
you like. A total says there is a problem; a breakdown says where. It also lists
what is sitting at its calibrated normal, because ruling a suspect out is half
of a diagnosis.

```
  STEP 3 of 5 — MONITOR

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

| Dominant row | Read it as |
| --- | --- |
| `wait for a slot` | Requests queue before any work starts — capacity or admission |
| `write the answer` | Generation is the cost — output length, model tier, output caps |
| `find the notes` | Retrieval is the cost — how much is being retrieved |
| `network` | Time outside the service, usually a cold container or distant client |

A `✓` means that value is at its calibrated normal — rule it out. A `+422%`
means it moved, and that is a lead.

**This step will not tell you which setting to change.** Naming the lever would
end the exercise. It gives you attribution; the diagnosis is your job.

## Step 4 — Optimize

```bash
nimbus optimize
```

Offers five changes, takes your **prediction before applying anything**, writes
your reasoning into a sentence you can copy into your notes, applies the
setting, clears the cache, and re-measures with **the same traffic**. The
prediction is the point of the step, and it costs one keystroke.

```
  STEP 4 of 5 — OPTIMIZE

  Pick ONE thing to change:

    1  Reuse answers to similar questions
       SEMANTIC_CACHE: off → on
    2  Use the cheaper, faster model
       MODEL_TIER: large → small
    3  Look up fewer notes per question
       RETRIEVE_K: 3 → 1
    4  Write shorter answers
       MAX_TOKENS: 32 → 16
    5  Handle more questions at once
       MAX_CONCURRENT: 2 → 8

  Your pick (1-5) > 5

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

| Verdict | Meaning | What to do |
| --- | --- | --- |
| `CORRECT` | Moved your way, by more than the noise | Keep it, go to step 5 |
| `WRONG` | Moved the other way | **A wrong prediction is a result** — it rules the setting out. Note why you expected otherwise, try another |
| `TOO CLOSE TO CALL` | Moved your way, but inside the ~12% noise | Unresolved. Run it again |
| `it went SAME` | Nothing moved outside the noise | Real information: this setting does not touch what is slow |
| `Still over.` | Latency not yet inside target | Run the step again, restoring the last setting first if it made things worse |

Change **one** thing at a time or you will not know which one did it. Repeat as
often as time allows.

## Step 5 — Guard

```bash
nimbus guard
```

Asks 36 real questions — 24 fact-finding, 12 reasoning — makes real model calls,
and reads the answers. Takes about a minute; let it finish. Then it prints your
scorecard, already filled in from your own runs.

**Fast and cheap is not the same as working.** `RECOVERY PASS` requires all five
conditions, not two of them.

```
  STEP 5 of 5 — GUARD

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
```

| Condition | Passes when |
| --- | --- |
| latency target | p95 is at or under the SLO |
| cost budget | Projected monthly cost is at or under budget |
| every request served | Zero shed and zero failed |
| answer quality | Eval score is at or above the bar |
| config held still | Nothing changed between the measurement and the eval |

- **`RECOVERY NOT PROVEN`** with a `✗` row — that condition failed, and `guard`
  exits non-zero. Say which one, and what you would measure next.
- **`The configuration changed after your last measurement`** — a setting moved
  since your run. Re-run `nimbus benchmark`, then `nimbus guard`.
- **A high score with wrong answers** — expected. The check looks for keywords,
  so a wrong answer can contain the right words and a correct paraphrase can
  miss them.

Read several answers in the browser against the notes shown alongside them. Does
it match the notes? Apply them rather than restate them? Pass on a caution the
notes contain instead of reassuring? Decline what the notes do not cover?

### Write it up

Copy the scorecard into your notes and explain:

> what users experienced → what you measured → what you changed → what happened
> → whether the answers stayed useful → what is still uncertain

If recovery failed, say **which condition** failed and **what you would measure
next**. That is a complete answer.

---

## Driving it directly

The five steps are wrappers. Every measurement underneath is available on its
own:

```
nimbus baseline · bench · diagnose · requests · hypothesis · set · eval · status
```

`nimbus requests --slow` is the most useful. It prints the individual requests
behind your p95 and says whether the slow ones were all slow for the same
reason.

## Settings

Use the setting your evidence points at. These are options to investigate, not a
checklist to work through. Apply one with `nimbus set KEY=VALUE`, then
re-measure with `nimbus bench`. Booleans take `true` or `false`.

| Setting | Values | Effect, and the tradeoff to check |
| --- | --- | --- |
| `SYSTEM_PROMPT` | `LONG`, `TRIMMED`, `VERBOSE` | Selects the instruction block. Check input size *and* whether required answer behaviour survives |
| `RETRIEVE_K` | 0–20 | Chunks entering the prompt. Fewer may cut work but omit needed facts |
| `MAX_TOKENS` | 1–1024 | Caps output. A low cap truncates answers, or leaves no visible text at all on a reasoning model |
| `MODEL_TIER` | `small`, `large` | Default tier. `small` sends every question there, so check the difficult ones |
| `ROUTE_EASY` | boolean | With a large default, routes short pattern-matched questions to the small tier. The rule can misjudge difficulty |
| `RESPONSE_CACHE` | boolean | Reuses an answer for an identical assembled prompt. Retrieval still runs |
| `SEMANTIC_CACHE` | boolean | Reuses an answer to a *similar* question, before retrieval. Similarity can hide a real difference |
| `SEMANTIC_CACHE_THRESHOLD` | 0–1 | Required similarity. Lower accepts more matches, including wrong ones |
| `MAX_CONCURRENT` | 1–64 | Simultaneous work inside Nimbus. Raising it can move the pressure to the provider |
| `SHED_ABOVE_QUEUE` | ≥0; empty clears | Rejects requests past the waiting limit. Check rejection counts alongside latency |
| `PREFIX_CACHE` | boolean | Requests reuse of static prompt computation locally. Cloud reuse is provider-managed, so this guarantees nothing there |

## If something goes wrong

| What you see | What to do |
| --- | --- |
| Setup fails | Use Cloud Shell or a teammate's terminal; ask a facilitator |
| `nimbus: command not found` | `cd` into the repository, repeat the `export PATH=...` line |
| A message asking you to run `nimbus init` | Run `init` here with your team's URL and token |
| Health warning or connection error | Check the service URL with your facilitator |
| `That token was not accepted` | The URL and token belong to different teams |
| `No measurement yet` | Run `nimbus benchmark` — steps 2 to 5 all read that measurement |
| `The configuration changed after your last measurement` | Re-run `nimbus benchmark`, then `nimbus guard` |
| Nimbus says a question is outside what it covers | Expected. Ask about a drink or a build standard |
| Empty answers, or every request fails | Ask a facilitator to check readiness and model access |

Settings, caches, and predictions live in service memory and are lost if the
service restarts. If that happens, have a facilitator check it, inspect
`nimbus status`, and start again from `nimbus benchmark` — **a run taken under
one configuration cannot be compared against a run taken under another.**

---

## Applying the lesson to an agent

Suppose Nimbus could also take an order and send it to the bar. A **tool** is an
operation the application exposes to the model, such as reading a queue or
placing an order. Discuss what that would need:

| Concern | What the agent would need |
| --- | --- |
| Permissions | Access only to authorized operations, enforced outside the model |
| Valid actions | Checked arguments, and human review before an order is placed |
| Bounded work | Limits on steps, elapsed time, retries, and spending |
| Safe retries | A way to identify an already-placed order so a lost reply does not duplicate it |
| Persistent state | Saved progress, so a restart does not lose completed actions |
| Untrusted content | Instructions found in notes or tool results treated as data, never as authority |
| Evaluation | Tests over actual queue state, denied actions, and partial failures — not just the final answer |
| Monitoring and rollout | Traced tool outcomes, problem detection, gradual release, and a way back |

Nimbus does not implement this; its public chat endpoint and in-memory settings
are workshop choices. A wider deployment would also need user authentication,
data and abuse controls, and ongoing monitoring. **A passing lab run is evidence
for the tested workload, not for every future user or task.**

## For facilitators

Setup, deployment, incident injection, and the answer key are in `facilitators/`
— start with `runsheet.md` and `teaching_guide.md`. Participants should not read
that directory.

```bash
make setup     # virtualenv, pinned dependencies, build the note index
make check     # unit tests, compile checks, dependency check
make serve     # run the service locally on :8000
make bench     # benchmark whatever URL is in $URL
```

The recipe notes in `data/recipes/` are an approximation of standard builds
written as a teaching fixture, not official specifications. After any change to
them, rebuild the index (`make setup`) and re-run
`facilitators/calibrate_incidents.py`, because the baselines every "is this
normal?" comparison uses are measured against the corpus and the system prompt.
