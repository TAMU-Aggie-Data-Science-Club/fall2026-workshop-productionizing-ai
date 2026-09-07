"""Contract tests for incident injection.

Two properties matter more than the rest.

The injected delay must be LOG-NORMAL, not constant. A constant delay shows up
identically in p50 and p95, which quietly teaches participants that percentiles
are decoration. A fat tail is also what a real degraded dependency looks like.

The injected provider fault must drive the adapter's REAL retry path, so the
retry counter the report prints is counting something that actually happened.
"""
import asyncio
import importlib
import math
import os
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
sys.path.insert(0, str(ROOT / "facilitators"))

import incident  # noqa: E402
from incidents import INCIDENTS  # noqa: E402


def _reload(**env):
    """Reload the module under a given injection configuration."""
    keys = ("NIMBUS_INCIDENT_STAGE_DELAY", "NIMBUS_INCIDENT_PROVIDER_FAULT",
            "NIMBUS_INCIDENT_SEED")
    clean = {k: "" for k in keys}
    with patch.dict(os.environ, {**clean, **env}, clear=False):
        return importlib.reload(incident)


class InjectionShapeTests(unittest.TestCase):
    def tearDown(self):
        _reload()

    def test_delay_matches_the_requested_percentiles(self):
        mod = _reload(NIMBUS_INCIDENT_STAGE_DELAY="retrieve:lognormal:400:1800")
        mu, sigma = mod._DELAYS["retrieve"]
        draws = sorted(math.exp(mod._rng(f"retrieve:q{i}").gauss(mu, sigma))
                       for i in range(8000))
        self.assertAlmostEqual(draws[len(draws) // 2], 400, delta=40)
        self.assertAlmostEqual(draws[int(0.95 * len(draws))], 1800, delta=250)

    def test_delay_has_a_fat_tail_not_a_flat_one(self):
        mod = _reload(NIMBUS_INCIDENT_STAGE_DELAY="retrieve:lognormal:400:1800")
        mu, sigma = mod._DELAYS["retrieve"]
        draws = sorted(math.exp(mod._rng(f"retrieve:q{i}").gauss(mu, sigma))
                       for i in range(8000))
        ratio = draws[int(0.95 * len(draws))] / draws[len(draws) // 2]
        self.assertGreater(ratio, 2.0,
                           "p95 must be materially worse than p50, or the "
                           "incident teaches that percentiles do not matter")

    def test_the_same_question_always_draws_the_same_delay(self):
        mod = _reload(NIMBUS_INCIDENT_STAGE_DELAY="retrieve:lognormal:400:1800")
        first = asyncio.run(mod.delay("retrieve", "What is Big-O notation?"))
        second = asyncio.run(mod.delay("retrieve", "What is Big-O notation?"))
        other = asyncio.run(mod.delay("retrieve", "What is overfitting?"))
        self.assertEqual(first, second, "a team must be able to reproduce a run")
        self.assertNotEqual(first, other)

    def test_untouched_stages_and_a_clean_service_inject_nothing(self):
        mod = _reload(NIMBUS_INCIDENT_STAGE_DELAY="retrieve:lognormal:400:1800")
        self.assertEqual(asyncio.run(mod.delay("generate", "q")), 0.0)
        clean = _reload()
        self.assertFalse(clean.active())
        self.assertEqual(asyncio.run(clean.delay("retrieve", "q")), 0.0)
        self.assertIsNone(clean.provider_fault("q", 0))

    def test_malformed_specs_fail_at_startup(self):
        # Caught as ValueError, not as IncidentConfigError: importlib.reload
        # rebinds the class, so an exception raised by the reloaded module is
        # not an instance of the class object this test captured beforehand.
        # IncidentConfigError subclasses ValueError precisely so this is stable.
        for bad in ("retrieve:weird:400", "retrieve:lognormal:abc",
                    "retrieve:lognormal:0", "retrieve:lognormal:900:100",
                    "retrieve"):
            with self.assertRaises(ValueError, msg=bad):
                _reload(NIMBUS_INCIDENT_STAGE_DELAY=bad)
            _reload()
        with self.assertRaises(ValueError):
            _reload(NIMBUS_INCIDENT_PROVIDER_FAULT="2.0")

    def test_provider_fault_mostly_recovers_on_retry(self):
        mod = _reload(NIMBUS_INCIDENT_PROVIDER_FAULT="0.17:429")
        n = 4000
        needs_retry = sum(1 for i in range(n) if mod.provider_fault(f"q{i}", 0))
        fails_outright = sum(1 for i in range(n)
                             if all(mod.provider_fault(f"q{i}", a) for a in range(3)))
        self.assertAlmostEqual(needs_retry / n, 0.17, delta=0.03)
        # A fat p99 and a few real failures -- not a uniformly broken service.
        self.assertLess(fails_outright / n, 0.02)


class DecodeIncidentCatalogTests(unittest.TestCase):
    def test_decode_is_bound_to_a_thinking_pro_large_tier(self):
        env = INCIDENTS["decode"]["env"]
        self.assertEqual(env["NIMBUS_MAX_TOKENS"], "256")
        self.assertEqual(env["NIMBUS_SYSTEM_PROMPT"], "VERBOSE")
        self.assertEqual(env["NIMBUS_GEMINI_THINKING_BUDGET"], "128")
        self.assertEqual(env["NIMBUS_GOOGLE_MODEL_LARGE"], "gemini-2.5-pro")


class FaultDrivesTheRealRetryPathTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import cloud_model
        self.cloud_model = cloud_model
        self.old_http, self.old_project = cloud_model._http, cloud_model._project
        self.old_token = cloud_model._access_token
        cloud_model._project = "test-project"
        cloud_model._access_token = AsyncMock(return_value="test-token")

    async def asyncTearDown(self):
        if self.cloud_model._http is not None and self.cloud_model._http is not self.old_http:
            await self.cloud_model._http.aclose()
        self.cloud_model._http = self.old_http
        self.cloud_model._project = self.old_project
        self.cloud_model._access_token = self.old_token
        _reload()

    async def test_injected_fault_is_retried_and_counted(self):
        _reload(NIMBUS_INCIDENT_PROVIDER_FAULT="1.0:429")
        # Rate 1.0 faults every attempt, so this must exhaust the retries and
        # surface as a failure -- never as a silent success.
        calls = 0

        def handler(request):
            nonlocal calls
            calls += 1
            return httpx.Response(200, headers={"content-type": "application/json"},
                                  json={"choices": [{"message": {"content": "hi"}}]})

        self.cloud_model._http = httpx.AsyncClient(
            transport=httpx.MockTransport(handler))
        stats = {}
        with patch.dict(os.environ, {"NIMBUS_GOOGLE_API_STYLE": "mistral",
                                     "NIMBUS_GOOGLE_MODEL_ID": "mistral-small-2503",
                                     "NIMBUS_PROVIDER_RETRIES": "2",
                                     "NIMBUS_PROVIDER_BACKOFF_SECONDS": "0"},
                        clear=False):
            with self.assertRaises(self.cloud_model.ProviderError):
                async for _ in self.cloud_model.generate("large", "p", 8, stats):
                    pass
        self.assertEqual(calls, 0, "the fault must short-circuit the real request")
        self.assertEqual(stats["upstream_retries"], 2)
        self.assertEqual(stats["provider_status"], 429)


if __name__ == "__main__":
    unittest.main()
