"""Regression tests for cost reporting and the additive latency ledger."""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmark"))

import report  # noqa: E402


class ReportTests(unittest.TestCase):
    def test_ollama_is_reported_as_zero_direct_cost(self):
        payload = {
            "run": 1,
            "duration_s": 1.0,
            "server_runtime": {"provider": "ollama"},
            "server_config": {},
            "results": [{
                "ok": True,
                "shed": False,
                "latency_s": 1.0,
                "ttft_s": 0.2,
                "queue_wait_ms": 0.0,
                "compute_ms": 1000.0,
                "tokens_in": 100,
                "tokens_out": 20,
                "tokens_cached": 0,
                "usage_source": "provider",
                "provider": "ollama",
                "model": "llama3.1:8b",
                "cache": "miss",
                "tier": "large",
            }],
        }
        scenario = {
            "prices": {"large": {"input": 0.6, "output": 2.4},
                        "replica_usd_per_month": 300},
            "traffic": {"requests_per_day": 1},
            "constraints": {"slo_p95_latency_s": 5.0, "budget_usd_per_month": 1500},
        }

        summary = report.summarise(payload, scenario)

        self.assertEqual(summary["provider"], "ollama")
        self.assertTrue(summary["usage_complete"])
        self.assertEqual(summary["usd_per_month"], 0.0)
        self.assertEqual(summary["usd_infra_per_month"], 0.0)


if __name__ == "__main__":
    unittest.main()


def _row(latency_s, queue_ms, stages, tokens_in=1480, tokens_out=32,
         retries=0, status=None, overhead_ms=20.0):
    """One benchmark result row shaped exactly as benchmark/run.py writes it."""
    return {
        "ok": True, "shed": False,
        "latency_s": latency_s,
        "ttft_s": latency_s * 0.7,
        "queue_wait_ms": queue_ms,
        "compute_ms": sum(stages.values()) + overhead_ms,
        "stages_ms": dict(stages),
        "upstream_retries": retries,
        "provider_status": status,
        "tokens_in": tokens_in, "tokens_out": tokens_out, "tokens_cached": 0,
        "usage_source": "local", "provider": "local", "model": "",
        "cache": "miss", "tier": "large",
    }


def _payload(rows, run=1, **over):
    payload = {"run": run, "label": "", "duration_s": 10.0, "args": {},
               "server_config": {"REPLICAS": 1},
               "server_runtime": {"provider": "local"}, "results": rows,
               "context": {"url": "http://test", "session": "test",
                           "traffic": {"requests": 16, "rate": 4, "concurrency": 8}}}
    payload.update(over)
    return payload


SCENARIO = {
    "prices": {"small": {"input": 0.05, "output": 0.2, "cached_input": 0.005},
               "large": {"input": 0.6, "output": 2.4, "cached_input": 0.06},
               "replica_usd_per_month": 300},
    "traffic": {"requests_per_day": 150000},
    "constraints": {"slo_p95_latency_s": 5.0, "budget_usd_per_month": 1500},
    "baselines": {"default": {"tokens_in": 1480, "tokens_out": 32}},
}


def _queue_dominated():
    rows = []
    for i in range(16):
        queue = 2000 + i * 1100
        stages = {"cache": 2.0, "retrieve": 12.0, "assemble": 1.0,
                  "generate": 7000 + i * 60}
        latency = (queue + sum(stages.values()) + 20.0 + 90.0) / 1000
        rows.append(_row(latency, queue, stages))
    return _payload(rows)


class LedgerTests(unittest.TestCase):
    """The additive latency ledger is the instrument the activity turns on.

    If the rows stop summing, participants can no longer read the breakdown as
    a budget, and "is the model the bottleneck?" stops having a checkable
    answer.
    """

    def test_ledger_sums_to_end_to_end_latency(self):
        summary = report.summarise(_queue_dominated(), SCENARIO)
        total = sum(summary["ledger"].values())
        self.assertGreater(summary["ledger_latency_ms"], 0)
        drift = abs(total - summary["ledger_latency_ms"]) / summary["ledger_latency_ms"]
        self.assertLessEqual(drift, 0.02, "ledger rows must sum to end-to-end within 2%")

    def test_stage_timings_survive_into_the_summary(self):
        # Regression guard for the bug where the server measured per-stage
        # timings, streamed them, and the benchmark dropped them on the floor --
        # leaving one opaque "compute" number that could not exonerate anything.
        summary = report.summarise(_queue_dominated(), SCENARIO)
        self.assertGreater(summary["ledger"]["generate"], 0.0)
        self.assertGreater(summary["ledger"]["retrieve"], 0.0)
        self.assertGreater(summary["stage_p95"]["generate"], 0.0)

    def test_read_this_first_names_the_dominant_slice(self):
        rendered = report.render(_queue_dominated(), SCENARIO,
                                 pathlib.Path("/nonexistent"))
        self.assertIn("READ THIS FIRST", rendered)
        self.assertIn("APP QUEUE WAIT", rendered)

    def test_report_never_names_a_lever(self):
        """Invariant: the report attributes latency, it does not prescribe.

        The moment this output names the fix, the diagnosis is done for the
        participant and the exercise is over.
        """
        rendered = report.render(_queue_dominated(), SCENARIO,
                                 pathlib.Path("/nonexistent"))
        forbidden = ["RESPONSE_CACHE", "SEMANTIC_CACHE", "PREFIX_CACHE",
                     "MAX_TOKENS", "MODEL_TIER", "MAX_CONCURRENT", "REPLICAS",
                     "ROUTE_EASY", "RETRIEVE_K", "SYSTEM_PROMPT",
                     "not your problem", "enable caching", "rung"]
        for token in forbidden:
            self.assertNotIn(token.lower(), rendered.lower(),
                             f"report must not name a remediation: {token!r}")

    def test_no_per_token_rate_is_reported(self):
        """Per-token RATES inflate with contention.

        A busy queue and a slow model both push ms/token up, so publishing one
        recreates exactly the confusion the ledger exists to remove. Output
        token COUNT is load-independent and does the same job honestly.
        """
        rendered = report.render(_queue_dominated(), SCENARIO,
                                 pathlib.Path("/nonexistent"))
        for token in ("ms/tok", "inter-token", "per token"):
            self.assertNotIn(token, rendered)

    def test_generation_bound_run_points_at_generate(self):
        """The model really can be the bottleneck, and the panel must say so."""
        rows = [_row((30.0 + 5000 + 40 * i + 13.0) / 1000, 30.0,
                     {"cache": 2.0, "retrieve": 10.0, "assemble": 1.0,
                      "generate": 5000 + 40 * i}, tokens_out=256)
                for i in range(16)]
        rendered = report.render(_payload(rows), SCENARIO,
                                 pathlib.Path("/nonexistent"))
        self.assertIn("GENERATE", rendered)
        self.assertNotIn("APP QUEUE WAIT (", rendered)

    def test_provider_retries_are_surfaced(self):
        rows = [_row(3.0, 30.0, {"generate": 2900.0}, retries=2, status=429)
                for _ in range(4)]
        summary = report.summarise(_payload(rows), SCENARIO)
        self.assertEqual(summary["upstream_retries"], 8)
        self.assertEqual(summary["retry_statuses"], [429])
        self.assertIn("429", report.render(_payload(rows), SCENARIO,
                                           pathlib.Path("/nonexistent")))

    def test_baseline_comparison_is_absent_when_uncalibrated(self):
        scenario = dict(SCENARIO,
                        baselines={"default": {"tokens_in": None,
                                               "tokens_out": None}})
        rendered = report.render(_queue_dominated(), scenario,
                                 pathlib.Path("/nonexistent"))
        # Never invent a "normal" this hardware was not measured against.
        self.assertIn("not calibrated", rendered)

    def test_a_run_with_no_successes_never_passes(self):
        payload = _payload([{"ok": False, "shed": False, "error": "boom"}])
        rendered = report.render(payload, SCENARIO, pathlib.Path("/nonexistent"))
        self.assertIn("0/2 constraints met", rendered)
        self.assertIn("every request failed", rendered)

    def test_a_failed_previous_run_is_not_quoted_as_a_comparison(self):
        """A run with zero successes scores p95 0.00s and $0/month.

        Quoting that as "the previous result" presents a completely broken
        deployment as the number to beat -- the same trap the verdict guard
        exists for, one line further down the report.
        """
        with tempfile.TemporaryDirectory() as tmp:
            results = pathlib.Path(tmp)
            broken = _payload([{"ok": False, "shed": False, "error": "boom"}], run=1)
            (results / "run-1.json").write_text(json.dumps(broken))
            rendered = report.render(_payload(_queue_dominated()["results"], run=2),
                                     SCENARIO, results)
            self.assertNotIn("run 1: p95 0.00s", rendered)
            self.assertNotIn("(run 1:", rendered)

    def test_a_healthy_previous_run_is_still_quoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            results = pathlib.Path(tmp)
            good = _payload([_row(1.0, 10.0, {"generate": 900.0})], run=1)
            (results / "run-1.json").write_text(json.dumps(good))
            rendered = report.render(_payload(_queue_dominated()["results"], run=2),
                                     SCENARIO, results)
            self.assertIn("(run 1:", rendered)

    def test_token_averages_exclude_cache_hits(self):
        """A cache hit makes no model call and reports zero tokens.

        Averaging those zeros in makes prompt size appear to fall whenever the
        hit rate rises -- so a prompt regression could hide behind a healthy
        cache. The metric must describe the requests that actually reached the
        model.
        """
        served = [_row(2.0, 10.0, {"generate": 1900.0}, tokens_in=1480) for _ in range(4)]
        hits = []
        for _ in range(4):
            hit = _row(0.05, 5.0, {"cache": 40.0}, tokens_in=0, tokens_out=0)
            hit["cache"] = "semantic-hit"
            hits.append(hit)
        summary = report.summarise(_payload(served + hits), SCENARIO)
        self.assertEqual(summary["cache_hit_rate"], 0.5)
        self.assertEqual(summary["tokens_in_mean"], 1480,
                         "cache hits must not drag the token average down")
        self.assertEqual(summary["generated_requests"], 4)

    def test_an_all_cache_run_still_reports_something(self):
        hits = []
        for _ in range(3):
            hit = _row(0.05, 5.0, {"cache": 40.0}, tokens_in=0, tokens_out=0)
            hit["cache"] = "exact-hit"
            hits.append(hit)
        summary = report.summarise(_payload(hits), SCENARIO)
        self.assertEqual(summary["tokens_in_mean"], 0)

    def test_cloud_run_infra_cost_comes_from_the_scenario(self):
        """Without an infra figure the cost verdict reads UNKNOWN forever.

        On Cloud Run the token cost is only part of the bill, so the report
        refuses to call a run affordable until someone states what the
        infrastructure costs. Keeping that figure in scenario.json puts it
        beside the token prices where it can be audited, rather than in an
        environment variable nobody remembers to set.
        """
        rows = [_row(1.0, 10.0, {"generate": 900.0}) for _ in range(4)]
        for r in rows:
            r["provider"] = "google"
            r["model"] = "gemini-2.5-flash"
            r["usage_source"] = "provider"
        payload = _payload(rows, server_runtime={"provider": "google"})
        scenario = dict(SCENARIO,
                        prices={**SCENARIO["prices"], "cloudrun_usd_per_month": 70},
                        provider_prices={"google:gemini-2.5-flash":
                                         {"input": 0.30, "output": 2.50,
                                          "cached_input": 0.075}})
        summary = report.summarise(payload, scenario)
        self.assertEqual(summary["usd_infra_per_month"], 70.0)
        self.assertIsNotNone(summary["usd_per_month"])
        rendered = report.render(payload, scenario, pathlib.Path("/nonexistent"))
        self.assertNotIn("total / month unknown", rendered)

    def test_missing_infra_figure_still_reports_unknown(self):
        rows = [_row(1.0, 10.0, {"generate": 900.0}) for _ in range(4)]
        for r in rows:
            r["provider"] = "google"
            r["model"] = "gemini-2.5-flash"
            r["usage_source"] = "provider"
        payload = _payload(rows, server_runtime={"provider": "google"})
        scenario = dict(SCENARIO,
                        provider_prices={"google:gemini-2.5-flash":
                                         {"input": 0.30, "output": 2.50,
                                          "cached_input": 0.075}})
        summary = report.summarise(payload, scenario)
        self.assertIsNone(summary["usd_per_month"],
                          "unmeasured infrastructure must never be treated as free")
