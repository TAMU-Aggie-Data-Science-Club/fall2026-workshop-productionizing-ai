# Contributing to Nimbus

The current delivery target is a repeatable Cloud Run incident workshop. Read
[README](README.md), [cloud operations](deploy/README.md), and
[development decisions and evidence](docs/DEVELOPMENT_LOG.md).

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
