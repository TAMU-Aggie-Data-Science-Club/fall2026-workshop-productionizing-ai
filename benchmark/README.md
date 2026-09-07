# Nimbus measurement and recovery

The participant path is [cli/nimbus](../cli/nimbus): brief → baseline → diagnose →
hypothesis → set → bench → eval. It takes the incident's traffic profile from
/brief and records authenticated configuration, runtime, deployment and session
identity with every run. See the [participant quickstart](../participants/quickstart.md).

## Direct engineer benchmark

```bash
make bench URL="$NIMBUS_URL" ARGS="--requests 16 --rate 1 --concurrency 2 --session investigation-a"
```

Use the traffic profile for the actual incident; the example is calm traffic.
The direct command takes NIMBUS_ADMIN_TOKEN for /metrics. If metadata cannot be
read, it can still collect traffic but cannot establish configuration-stable
recovery. The participant CLI requires authenticated metadata before measuring.
Credentials are excluded from saved arguments.

Direct runs live under results/<service-session-hash>/; CLI runs under
.nimbus-runs/<service-session-hash>/. URL and session select the history. Before/
after comparison additionally requires matching provider/API style/region and
traffic. Intentional configuration/model changes are recorded, not hidden.
Legacy records without identity are not offered as comparisons.

## Read the instrument

- p95 req decomposes one p95-ranked successful request and sums to its latency.
- p95 each is a separate percentile per component; those rows do not sum.
- client + network is an uninstrumented remainder. It can include platform queueing,
  startup, transit and client overhead; it does not identify their individual shares.
- The benchmark counts incomplete or empty streams as failures, even under HTTP 200.
- Request outcomes include success, shedding and failure. Latency percentiles cover
  successful requests only; use outcome counts to see the rest of user impact.
- Warm-up uses normal output limits so an enabled answer cache cannot be populated
  with deliberately truncated four-token answers.
- At sixteen requests, percentiles are coarse order statistics. Repeat warm runs
  with the same workload before concluding that a near-threshold change helped.

The report names observed bottlenecks and token anomalies, not the remediation.
Backend-specific reference token counts are omitted on other backends.

## Recovery and cost

The familiar latency/cost 2/2 verdict is accompanied by availability, quality and
RECOVERY status. Recovery needs successful requests, passing latency and modeled
cost, stable observed configuration, and a matching quality score. `nimbus eval`
runs the existing 36-question quality proxy against the latest measured settings.

Monthly cost projects a per-successful-request token estimate to the fixed traffic
scenario plus an infrastructure allowance. It is not a cloud bill, does not fully
account for unsuccessful provider calls, and is not a calibrated local/cloud
performance comparison. Missing provider usage makes cost unknown.

Old eval cards, paper panels and ladder results remain historical artifacts until
regenerated from a validated backend/workload. Do not use their quality claims to
override the current live measurement.
