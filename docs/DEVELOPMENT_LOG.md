# Cloud workshop delivery log

Authorized 2026-09-06: implement the engineering audit plan, verify Cloud Run,
and record development tradeoffs. Earlier audit results remain historical.

## Acceptance checklist

- [x] Consistent fresh Python setup and contributor checks.
- [x] One immutable image deployed to two services with distinct team tokens.
- [x] Preflight tests both actual models without changing the incident or gate.
- [x] Session-scoped runs capture runtime/configuration/traffic/revision.
- [x] Empty answers fail; availability and quality are explicit recovery gates.
- [x] Every enabled workshop incident has measured baseline and recovery evidence.
- [x] Two different team investigations complete within twenty minutes in a scripted rehearsal.

## Decisions and tradeoffs

1. **Keep one worker and one instance per team.** The current controls and
   declarations are process-local. Shared persistence and scale-out are deferred;
   service/revision/session metadata will make resets and incompatible histories
   visible. This preserves the bounded workshop architecture.
2. **Use a dedicated authenticated model-verification endpoint.** Testing a tier
   by changing participant levers bypasses or pollutes the diagnosis workflow.
   A separate check calls the same adapter for both fixed tiers, without altering
   controls or declarations. It costs a few model calls and does not substitute
   for a normal /ask smoke test or an incident baseline.
3. **Build once and deploy by immutable digest.** Explicit image reuse is allowed
   for a dirty development checkout; digest provenance, rather than a misleading
   commit-only tag, identifies the deployed artifact. New builds get unique tags.
4. **Separate team credentials while retaining the existing role model.** Each
   service receives its own secret. Team tokens still control that team's admin
   endpoints; a separate facilitator role is deferred. Runtime IAM access to
   secrets must be understood separately from HTTP team-token isolation.
5. **Do not invent quality separation.** An incident is eligible for a live room
   only after measurement demonstrates both its failure and a viable recovery.
   Unsupported or unstable cases will be explicitly excluded from the default
   room, with the reason and evidence recorded here.
6. **Keep historical artifacts separate from new evidence.** Old incident panels
   and eval cards remain historical measurements; they are not hand-edited to
   claim successful recovery. The new cloud rehearsal saves raw runs, CLI output,
   deployment identities, and quality results in a distinct results directory.
7. **Use a conservative availability gate.** At this workshop's tiny sample size,
   recovery requires every measured request to succeed, plus latency, cost, and
   the existing 80% quality proxy. The old latency/cost 2-axis verdict remains
   visible for continuity, but cannot by itself declare recovery. This is a
   workshop acceptance rule, not a production availability SLO estimate.
8. **Bind quality to observed configuration.** `nimbus eval` checks current
   configuration/runtime/revision before and after evaluation and attaches the
   score to that benchmark only. It uses the existing 36-case keyword proxy,
   which is limited and explicitly not a general correctness/safety assessment.
9. **Provisional room scope: prompt and retrieval in round 2.** Decode and upstream
   stay experimental until their participant-accessible recovery is measured;
   cheapmodel/staleness remain experimental because their measured quality clears
   the existing failure bar. No threshold is changed to manufacture a failure.
10. **Session history stays local.** New runs are partitioned by URL and session;
    comparisons require matching backend/API style/region and offered traffic.
    Intentional model/config/revision changes within a session remain comparable
    and are recorded. Legacy runs without provenance are not compared.

## Validation evidence

Verified on 2026-09-06. All results below are measured; historical audit results
remain in ENGINEERING_GUIDE.md and the older section of BUILD_STATUS.md.

### Setup and repository checks

- Fresh `make setup VENV=.venv-verify PYTHON=python3.11` completed, including
  dependency installation, a 48 × 384 retrieval index and both local model tiers.
- Requesting Python 3.11 for the old Python 3.13 `.venv` failed clearly without
  replacing it. Pip/uvicorn are invoked through the selected interpreter.
- `make check VENV=.venv-verify`: **100 tests passed**, dependency compatibility,
  Python compilation (including the extensionless CLI), shell syntax and whitespace
  checks passed. The CI workflow is added but has not run on GitHub.

### Build and deployment provenance

- Cloud Build **73f73312-3cdd-4738-a59f-489e01a45ae5** succeeded in **3m02s**.
- Build source archive:
  `gs://adsc-nimbus_cloudbuild/source/1788736877.301514-5837def0ce0c4f77b77e7ec13d628ff4.tgz`.
- Built tag: `nimbus:24b30df-20260906232115` (a dirty development checkout; do not
  interpret the commit prefix as the whole source).
- Immutable image:
  `us-central1-docker.pkg.dev/adsc-nimbus/nimbus/nimbus@sha256:a593c5bd82815aa262258e198bdb61a81d2ffd8fff97411b80a8d9b0b1e25fc5`.
- All three new services deployed that exact digest. The image contains the tested
  serving changes. Rehearsal scripts and current documentation were finalized
  afterward on the facilitator checkout; no serving code changed after this build.
- Project/region: `adsc-nimbus` / `us-central1`; 1 vCPU / 1 GiB, concurrency 80,
  maximum one instance. New secrets contain independently generated tokens with
  runtime-secret access granted per secret. No credential values are in artifacts.

| Service | Revision | Incident | Secret reference |
| --- | --- | --- | --- |
| nimbus-verify-a | nimbus-verify-a-00001-6nx | prompt | nimbus-verify-a-token |
| nimbus-verify-b | nimbus-verify-b-00001-g4r | retrieval | nimbus-verify-b-token |
| nimbus-verify-queue | nimbus-verify-queue-00001-xk5 | queue / round 1 | nimbus-verify-queue-token |

### Live readiness, authentication and workflow

Both actual Gemini tiers returned nonempty text and provider usage on every new
service. Preflight preserved controls and declarations. Missing/wrong credentials
were rejected, and team A's token could not read team B's metrics or change its
levers (and conversely). Both round-2 services returned **409** before a hypothesis.
The actual participant CLI then performed brief, baseline, diagnose, hypothesis,
setting changes, benchmarks and quality evaluation.

The two-team scripted rehearsal completed in **174.5 seconds**, excluding deployment
and preflight. It is command-path timing, not evidence about human reasoning speed.
A human event dry run is still required before promising a twenty-minute experience.

| Incident | Before | Intervention, measured one change at a time | After | Quality | Final outcomes |
| --- | --- | --- | --- | --- | --- |
| Prompt | $2,092.33/month; 1,180 mean input tokens; p95 0.90s | TRIMMED instructions, then retrieve 3 chunks | $772.84/month; 226 mean input tokens; p95 0.87s | 94.4% (34/36) | 16/16 successful, RECOVERY PASS |
| Retrieval | p95 1.98s, retrieval dominant | Enable semantic answer caching | p95 1.06s; $376.90/month | 97.2% (35/36) | 16/16 successful, RECOVERY PASS |
| Queue | p95 5.76s, queue dominant | Enable exact answer caching; p95 1.56s still failed, then admission 1 → 2 | p95 1.06s | 94.4% (34/36) | 16/16 successful, RECOVERY PASS |

The queue workflow took **55.4 seconds**. Saved baseline measurements were checked
for actual constraint failure and the expected prompt/retrieval discriminators;
readiness alone was not used as evidence of an incident.

A further **concurrent** round-2 check passed in **41.3 seconds**: prompt p95 0.78s,
retrieval p95 0.14s, both 16/16 successful and quality 94.4% / 97.2%. The second
check retained warm caches from the preceding investigation/evaluation; its faster
retrieval result is continuing-traffic evidence, not a new cold-cache comparison.
Shared Vertex AI quotas and provider variance remain shared dependencies.

### Evidence locations (local, gitignored)

- `results/cloud-rehearsal-20260906/`: two-team summary, raw baseline/final runs,
  full CLI transcripts. Historical execution predates the subsequently added
  explicit baseline-discriminator assertions; those saved baselines were separately
  checked and passed the same assertions.
- `results/cloud-queue-20260906/`: queue summary, baseline/final runs and transcript.
- `results/cloud-concurrent-20260906/`: simultaneous final checks, raw runs, quality.
- `.nimbus-runs/`: CLI histories separated by service/session hash, with actual
  configuration/runtime/revision and matching quality signatures.
- `results/cloud-final-state-20260906.json`: final Cloud Run metadata after cleanup.

### Final operating tradeoffs

11. **Reduce idle cost after validation.** The three verification services remain
    deployed but are set to minimum zero / maximum one after recording evidence.
    They can cold-start on demand. Runtime fixes/declarations are temporary and
    can disappear when the process stops; stored incident environment settings
    remain the startup baseline. Warm and remeasure before using them in a session.
    The pre-existing `nimbus-eval` service and its minimum-one setting are unchanged.
12. **Keep secrets and the built image for reproducibility.** Cleanup reduces warm
    instance cost; it does not delete these verification resources. The retained
    image/secret resources can still incur storage costs. Use an explicit lifecycle
    policy when the workshop owner chooses to retire them.
13. **Use fresh service names for a fresh rehearsal.** `verify_cloud.py` deliberately
    requires a clean diagnosis history. Use a new prefix when deploying the same
    digest for another rehearsal; a new CLI session alone does not reset server
    memory. Deploy helpers create new secrets for that prefix automatically.
14. **Preserve teaching scope honestly.** The verified default room comprises prompt
    and retrieval, plus the verified round-1 queue exercise. The four experimental
    cases are not advertised as successful recovery exercises. No quality threshold
    or old generated measurement was altered to manufacture a result.
15. **Keep infrastructure estimates illustrative.** All monthly costs above are
    token-based exercise projections with the scenario's fixed infrastructure
    allowance. They are not the actual charges for these validation requests.

## Reproduce from this checkout

Use the Python 3.11 setup above and configure the ignored deploy/cloudrun.env.
Export the full `NIMBUS_IMAGE` digest recorded above to reuse the serving artifact.
Then deploy with a fresh prefix:

```bash
.venv-verify/bin/python facilitators/deploy_incident.py --all --teams 2 --prefix nimbus-next --run
.venv-verify/bin/python facilitators/verify_cloud.py --prefix nimbus-next --session next-rehearsal
```

For round 1, deploy a fresh queue service with `--incident queue --no-gate`, then
run `facilitators/verify_queue.py --service <name> --session <new-session>`.
New deployments default to minimum one for reliable workshop measurements; reduce
that deliberately afterward. Never point the mutation-based rehearsal at an active
participant session.

