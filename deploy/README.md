# Deploy and verify Nimbus on Cloud Run

The supported room uses one single-instance service per team, a shared immutable
image, and a distinct token per team. Current round-2 assignments are prompt and
retrieval. Decode, upstream, cheapmodel and staleness require
`--include-experimental` because their recovery/quality story is not yet proven.
See [development decisions](../docs/DEVELOPMENT_LOG.md) and the live evidence recorded there.

## Prerequisites

Use Python 3.11, Git, and gcloud authenticated to the workshop project. The project
needs billing and the Cloud Run, Cloud Build, Artifact Registry, Vertex AI and
Secret Manager APIs. The runtime service account needs Vertex AI access. The
operator needs permissions to build/push images, deploy services as that account,
and create team secrets and grant secret access. Check the actual Cloud Build
identity and its storage-read, artifact-write and logging permissions.

Copy `cloudrun.env.example` to the ignored `cloudrun.env` and fill in project,
region and runtime identity. Do not overwrite an existing configured file.
The incident helper loads and exports it automatically. For direct shell commands:

```bash
set -a
source deploy/cloudrun.env
set +a
```

## Preview, then deploy

```bash
.venv/bin/python facilitators/deploy_incident.py --all --teams 2 --prefix nimbus-team
.venv/bin/python facilitators/deploy_incident.py --all --teams 2 --prefix nimbus-team --run
```

Without `--run`, the helper only previews. With `--run`, it builds once, resolves
the digest, creates/reuses `<team>-token` secrets, grants the runtime identity
access, and deploys every target using that same digest. Tokens are generated in
memory and passed to Secret Manager through stdin; they are not printed.
`--rounds` creates separate round-1 queue and round-2 services for each team,
sharing only that team's credential. This doubles the instance count.

To reuse a previously reviewed artifact, export `NIMBUS_IMAGE` as its complete
`.../nimbus@sha256:...` reference before calling the helper. Mutable tags are
rejected for explicit reuse. This intentionally permits deploying an already
reviewed digest while local documentation or development files are dirty.

For a single incident:

```bash
.venv/bin/python facilitators/deploy_incident.py --incident retrieval --service nimbus-team-a --run
```

`--no-gate` is for facilitator calibration/round 1. Round-2 services default to a
required hypothesis. Do not build images during participant investigations.

## Readiness and rehearsal

```bash
.venv/bin/python facilitators/preflight.py --all-services --prefix nimbus-team-
```

Preflight resolves each service's own token through gcloud. It requires the Google
backend, authenticated metrics, nonempty real answers, provider usage, and the
actual model ID for each tier. `POST /verify-models` checks both adapters without
changing levers or declarations; normal `/ask` is checked separately. Missing
credentials or an untested model cannot produce a ready verdict. These calls
consume provider requests. A preflight is a readiness check, not incident recovery.

For the bounded automated rehearsal, deploy two fresh services with prefix
`nimbus-verify`, then run:

```bash
.venv/bin/python facilitators/verify_cloud.py --prefix nimbus-verify
```

This verifies the shared digest, distinct tokens, cross-team rejection, and the
409 hypothesis gate, then executes actual CLI baseline/diagnose/hypothesis/set/
bench/eval commands for prompt and retrieval. It writes sanitized deployment
metadata, CLI transcripts and raw measurements under `results/<session>/`.
It fails unless both recover and the scripted investigation fits twenty minutes.
A scripted rehearsal does not measure how long human participants need to reason.

## Runtime boundaries and operations

- Cloud Run concurrency is 80; application concurrency is independently configured.
  The queue exercise needs platform admission above application admission.
- One worker, minimum one instance and maximum one instance during the workshop.
  Levers, caches, counters and declarations live in process memory and reset on
  replacement. Raising instance count requires a shared-state design first.
- Model generation uses runtime ADC; no service-account key belongs in the image.
  Course-note retrieval and embeddings are local to the container.
- Team HTTP credentials differ, but the shared runtime service account can access
  the secrets granted to it. Separate runtime identities are a future isolation step.
- `/ask` and the browser remain public. The token protects control/readiness
  endpoints; this is a controlled workshop, not a general public service.
- `nimbus eval` binds the existing 36-case keyword quality proxy to the latest
  benchmark configuration. Recovery requires quality, availability, latency and
  modeled cost; green latency/cost alone is insufficient.
- After the session, preserve artifacts and deliberately scale minimum instances
  to zero or remove temporary services. Minimum instances incur idle charges.
  Secret cleanup and image retention are separate operator decisions.

Changing a lever is fast and temporary. Changing an image/provider configuration
creates a revision. `/reload` rereads the container's configuration; it cannot
apply source edits made only on your laptop. Do not use the local `eval_all.py`
config-patching workflow to claim remote configurations changed.
