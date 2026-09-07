# Contributing to Nimbus

The current delivery target is a repeatable Cloud Run incident workshop. Read
[README](README.md), [cloud operations](deploy/README.md), and
[development decisions and evidence](docs/DEVELOPMENT_LOG.md).

Then read [facilitators/runsheet.md](facilitators/runsheet.md) before writing
code. It is the only document that describes what actually happens in the room:
the four commands an organiser runs, what each one does and why, how team tokens
are generated and handed out, what preflight is protecting against, and the exact
error strings a stuck participant sees. Most of this repository exists to serve
those twenty minutes, and a change that reads as an improvement in isolation is
often a change that breaks them. If you are about to touch the CLI, the
deployment helper or preflight, the run sheet tells you who is standing in front
of a room depending on the current behaviour.

## Setup and checks

Use Python 3.11 to match the cloud image. `make setup` refuses to reuse a virtual
environment built with a different Python minor version. It never deletes an
existing environment. Choose a fresh path if needed:

```bash
make setup
make check
make serve
```

```bash
make setup VENV=.venv-verify PYTHON=python3.11
make check VENV=.venv-verify
make serve VENV=.venv-verify
```

Setup installs pinned packages using that environment's `python -m pip`, builds
the retrieval index, and prefetches the local model tiers. `make check` validates
dependencies, runs unittest (not pytest), compiles Python including the extensionless
CLI, checks deployment shell syntax and checks whitespace. CI performs the same
checks on Python 3.11 after building the retrieval index.

Run a bounded smoke benchmark from a second terminal:

```bash
make bench ARGS="--requests 4 --rate 1 --concurrency 2 --session local-smoke"
```

The local backend's latency and token counts are not comparable with the Google
calibration. Local costs are illustrative. Cloud verification is a separate gate:
[deploy/README.md](deploy/README.md) describes the real two-team rehearsal.

Docker is optional: `make docker-up`, `make docker-bench`, `make docker-down`.
Both Ollama tiers default to the same Llama model; choose distinct models if the
purpose is to compare tiers. The model volume survives `docker-down`.

## Change boundaries

- Service path: `service/app.py`, `config.py`, `levers.py`, `retrieval.py`.
- Model adapters: `model.py`, `ollama_model.py`, `cloud_model.py`.
- Instrument: `benchmark/run.py`, `run_context.py`, `report.py`.
- Participant commands: `cli/nimbus`; facilitator operations: `facilitators/`.
- Deployment: `Dockerfile`, `deploy/deploy.sh`, `facilitators/deploy_incident.py`.

Keep response classification, timing, token usage, run identity and recovery
semantics covered by behavioral tests. Cloud adapter tests mock provider requests;
they do not establish IAM, model access or successful deployment.

Record significant tradeoffs and live validation in DEVELOPMENT_LOG.md. Never
hand-edit measured eval cards, signature matrices or incident panels to fit a
story. Old generated artifacts are historical until regenerated against the
actual backend and workload. Preserve secrets outside source and results.

Runtime levers are in-memory. A process replacement loses them, and changing
semaphores during in-flight traffic can overlap admission pools. Apply changes
between complete runs and keep one instance/worker per team for this version.

`facilitators/eval_all.py` and the old ladder calibrator edit local configuration;
they do not change a remote container's source file. The remote path must apply
and verify controls through the service or deployment settings.

## Keeping the run sheet true

`facilitators/runsheet.md` quotes real command output and real flag names, so
some code changes silently make it wrong. Wrong there is expensive: it is read
under time pressure, on the morning of a session, by someone who cannot check it
against the source. Update it in the same change, not afterwards.

- **User-visible strings in `cli/nimbus`.** The "When a team cannot connect"
  table matches them verbatim. Change a message and the table stops matching what
  a participant reads on screen.
- **Flags or naming in `facilitators/deploy_incident.py`** -- `--all`, `--teams`,
  `--prefix`, `--rounds`, the `-a`/`-b` lettering, or the `<team>-token` secret
  convention. "Deploying the room" and "Team tokens" state all of these.
- **Checks or final output in `facilitators/preflight.py`.** The run sheet lists
  what each check catches and tells facilitators to proceed only on
  `All N service(s) ready to hand out.`
- **Setup steps in `participants/quickstart.md`.** The paste block in the run
  sheet is the same sequence with credentials filled in; the two drift easily.
- **Anything that changes how long a phase takes.** The minute-by-minute table is
  a budget, not a description.

The run sheet is operational only. Design rationale belongs in
[DEV_PLAN.md](docs/DEV_PLAN.md), current state in
[BUILD_STATUS.md](docs/BUILD_STATUS.md), and evidence in
[DEVELOPMENT_LOG.md](docs/DEVELOPMENT_LOG.md). Do not record a fix there that has
not been made, and do not describe a workflow you have not run end to end.
