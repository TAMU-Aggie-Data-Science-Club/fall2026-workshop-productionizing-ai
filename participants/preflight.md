# Participant preparation

For the Cloud Run workshop, follow [participant-quickstart.md](quickstart.md).
You need a terminal or Cloud Shell, the lightweight CLI dependency, and the team
URL/token supplied by your facilitator. The browser page is useful for inspecting
answers; the investigation runs through the CLI. Keep tokens out of browser code.

For engineer-local Python testing, use Python 3.11:

```bash
make setup
make check
make serve
```

An existing virtual environment with a different Python version is not overwritten.
Use `VENV=.venv-verify` to create a fresh environment. Setup builds the retrieval
index and prefetches both local tiers. See [CONTRIBUTING.md](../CONTRIBUTING.md).

The optional Docker/Ollama path requires a running Docker daemon, Compose v2,
and enough memory/disk for the chosen model. Run `make docker-up`, verify /health,
then `make docker-bench ARGS="--requests 4 --concurrency 1"`. Stop with
`make docker-down`; the model volume remains available.

Prepare before the session. If setup fails, join a teammate or use the
facilitator terminal rather than spending the investigation time downloading models.
