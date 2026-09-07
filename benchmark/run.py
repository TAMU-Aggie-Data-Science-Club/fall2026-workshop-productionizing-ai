"""The latency benchmark.

Plain asyncio + httpx on purpose: this file is short enough that you can read it
and know exactly what your numbers mean. That is part of the exercise.

How it works
------------
1. Load the frozen question corpus (deliberate duplicates included).
2. Fire a few warm-up requests and throw them away, so first-call overhead does
   not pollute the measurement.
3. Generate load with POISSON ARRIVALS at --rate, with --concurrency as a
   separate cap on requests in flight. Real traffic arrives at a rate; it does
   not all show up at once. A benchmark that fires everything simultaneously
   reports a TTFT that no user would ever experience.
4. Time every request individually off the streamed response: TTFT from the
   first chunk, end-to-end from the last. The server reports its own
   queue-wait/compute split AND its per-stage durations in the final event;
   both are recorded here. Keeping the stage breakdown is what lets the report
   attribute latency to retrieval, prompt assembly or generation instead of to
   one undifferentiated "compute" blob -- the difference between diagnosing a
   bottleneck and guessing at one.
5. Aggregate into PERCENTILES, not averages. The tail is the whole lesson.
6. Price it from scenario.json and judge it against the SLO and the budget.
"""
import argparse
import asyncio
import json
import os
import pathlib
import random
import time

import httpx
from run_context import context, run_directory, next_run, config_signature

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCENARIO = json.loads((ROOT / "scenario.json").read_text())
PROMPTS = [json.loads(line) for line in
           (ROOT / "benchmark" / "prompts.jsonl").read_text().splitlines() if line.strip()]
RESULTS = ROOT / "results"


async def one_request(client, url, question, results, sem):
    async with sem:
        sent = time.perf_counter()
        ttft = None
        chunk_times = []
        stats = {}
        request_error = None
        saw_done = False
        saw_text = False
        try:
            async with client.stream("POST", f"{url}/ask",
                                     json={"question": question}) as resp:
                if resp.status_code == 429:
                    await resp.aread()
                    results.append({"ok": False, "shed": True})
                    return
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:]
                    if payload == "[DONE]":
                        saw_done = True
                        break
                    event = json.loads(payload)
                    if "delta" in event:
                        saw_text = saw_text or bool(event["delta"].strip())
                        now = time.perf_counter()
                        if ttft is None:
                            ttft = now - sent
                        chunk_times.append(now)
                    elif "stats" in event:
                        stats = event["stats"]
                    elif "error" in event:
                        error = event["error"]
                        request_error = (error if isinstance(error, str)
                                         else error.get("message", "request failed"))
            if request_error:
                results.append({"ok": False, "shed": False,
                                "error": request_error})
                return
            if not saw_done or not stats or not saw_text:
                results.append({"ok": False, "shed": False,
                                "error": "incomplete or empty response from service"})
                return
        except Exception as exc:  # noqa: BLE001
            results.append({"ok": False, "shed": False, "error": repr(exc)})
            return

        end = time.perf_counter()
        itls = [b - a for a, b in zip(chunk_times, chunk_times[1:])]
        results.append({
            "ok": True, "shed": False,
            "latency_s": end - sent,
            "ttft_s": ttft if ttft is not None else end - sent,
            "itl_ms": (sum(itls) / len(itls) * 1000) if itls else 0.0,
            "queue_wait_ms": stats.get("queue_wait_ms", 0.0),
            "compute_ms": stats.get("compute_ms", 0.0),
            "stages_ms": stats.get("stages_ms", {}),
            "upstream_retries": stats.get("upstream_retries", 0),
            "provider_status": stats.get("provider_status"),
            "tokens_in": stats.get("tokens_in", 0),
            "tokens_out": stats.get("tokens_out", 0),
            "tokens_cached": stats.get("tokens_cached", 0),
            "usage_source": stats.get("usage_source", "unknown"),
            "provider": stats.get("provider", ""),
            "model": stats.get("model", ""),
            "cache": stats.get("cache", "miss"),
            "tier": stats.get("tier", "-"),
        })


async def drive(url, questions, rate, concurrency):
    """Poisson arrivals at `rate` req/s, at most `concurrency` in flight."""
    sem = asyncio.Semaphore(concurrency)
    results: list[dict] = []
    rng = random.Random(20260831)
    started = time.perf_counter()
    tasks = []
    async with httpx.AsyncClient(timeout=360.0) as client:
        for q in questions:
            tasks.append(asyncio.create_task(
                one_request(client, url, q, results, sem)))
            await asyncio.sleep(rng.expovariate(rate))
        await asyncio.gather(*tasks)
    return results, time.perf_counter() - started


async def warmup(url, n):
    async with httpx.AsyncClient(timeout=360.0) as client:
        for i in range(n):
            try:
                async with client.stream("POST", f"{url}/ask",
                                         json={"question": PROMPTS[i % len(PROMPTS)]["question"]}) as r:
                    async for _ in r.aiter_lines():
                        pass
            except Exception:  # noqa: BLE001, S110
                pass


def main() -> None:
    d = SCENARIO["bench_defaults"]
    p = argparse.ArgumentParser(description="Benchmark your Nimbus deployment.")
    p.add_argument("--url", default=os.environ.get("NIMBUS_URL", "http://127.0.0.1:8000"))
    p.add_argument("--admin-token", default=os.environ.get("NIMBUS_ADMIN_TOKEN", ""),
                   help="token for protected /metrics; never written to results")
    p.add_argument("--session", default="default")
    p.add_argument("--requests", type=int, default=d["requests"])
    p.add_argument("--rate", type=float, default=d["rate"],
                   help="arrivals per second (Poisson)")
    p.add_argument("--concurrency", type=int, default=d["concurrency"])
    p.add_argument("--warmup", type=int, default=d["warmup"])
    p.add_argument("--label", default="", help="note to yourself, e.g. 'cache on'")
    args = p.parse_args()

    if args.requests < 1:
        p.error("--requests must be at least 1")
    if args.rate <= 0:
        p.error("--rate must be greater than 0")
    if args.concurrency < 1:
        p.error("--concurrency must be at least 1")
    if args.warmup < 0:
        p.error("--warmup cannot be negative")

    questions = [PROMPTS[i % len(PROMPTS)]["question"] for i in range(args.requests)]

    args.url = args.url.rstrip("/")

    # Record what the server was actually running. Reading it from /metrics
    # rather than from config.py means the report describes the deployment you
    # measured, not the file you happen to have open in your editor.
    metrics_payload = {}
    server_config = {}
    server_runtime = {}
    try:
        metrics_response = httpx.get(
            f"{args.url}/metrics", timeout=10,
            headers={"X-Nimbus-Admin-Token": args.admin_token} if args.admin_token else {})
        if metrics_response.status_code == 401:
            print("warning: /metrics requires NIMBUS_ADMIN_TOKEN; continuing without server config",
                  flush=True)
        else:
            metrics_response.raise_for_status()
            metrics_payload = metrics_response.json()
            server_config = metrics_payload.get("config", {})
            server_runtime = metrics_payload.get("runtime", {})
    except Exception as exc:  # noqa: BLE001
        print(f"warning: could not read /metrics ({exc}); cost/config data may be incomplete",
              flush=True)

    print(f"warming up ({args.warmup} requests, discarded)...", flush=True)
    asyncio.run(warmup(args.url, args.warmup))

    print(f"benchmarking {args.requests} requests at {args.rate}/s, "
          f"concurrency {args.concurrency}...", flush=True)
    results, duration = asyncio.run(
        drive(args.url, questions, args.rate, args.concurrency))

    directory = run_directory(RESULTS, args.url, args.session)
    directory.mkdir(parents=True, exist_ok=True)
    run_no = next_run(directory)
    recorded_args = {k: v for k, v in vars(args).items() if k != "admin_token"}
    payload = {"run": run_no, "label": args.label, "duration_s": duration,
               "args": recorded_args, "server_config": server_config,
               "server_runtime": server_runtime, "results": results,
               "context": context(args.url, args.session, vars(args), metrics_payload),
               "config_signature": config_signature(metrics_payload),
               "configuration_stable": False}
    try:
        after = httpx.get(f"{args.url}/metrics", timeout=10,
            headers={"X-Nimbus-Admin-Token": args.admin_token} if args.admin_token else {})
        payload["configuration_stable"] = bool(metrics_payload) and after.status_code == 200 and config_signature(after.json()) == payload["config_signature"]
    except httpx.HTTPError:
        pass
    with (directory / f"run-{run_no}.json").open("x") as f:
        json.dump(payload, f, indent=2)

    from report import render          # noqa: PLC0415
    print(render(payload, SCENARIO, directory))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    main()
