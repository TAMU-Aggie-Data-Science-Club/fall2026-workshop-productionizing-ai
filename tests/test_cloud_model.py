"""Contract tests for the Google model adapter.

These tests use httpx's in-process transport, so they do not need Google
credentials, a cloud project, or a live model request. They protect the wire
format and the failure behavior that the participant service depends on.
"""
import json
import os
import pathlib
import sys
import unittest
from unittest.mock import AsyncMock, patch

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))

import cloud_model  # noqa: E402


class CloudModelContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_http = cloud_model._http
        self.old_project = cloud_model._project
        self.old_access_token = cloud_model._access_token
        cloud_model._project = "test-project"
        cloud_model._access_token = AsyncMock(return_value="test-token")

    async def asyncTearDown(self):
        if cloud_model._http is not None and cloud_model._http is not self.old_http:
            await cloud_model._http.aclose()
        cloud_model._http = self.old_http
        cloud_model._project = self.old_project
        cloud_model._access_token = self.old_access_token

    async def _generate(self, handler, **env):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        cloud_model._http = client
        stats = {}
        with patch.dict(os.environ, {
            "NIMBUS_GOOGLE_API_STYLE": "mistral",
            "NIMBUS_GOOGLE_MODEL_ID": "mistral-small-2503",
            "NIMBUS_PROVIDER_RETRIES": "0",
            "NIMBUS_PROVIDER_BACKOFF_SECONDS": "0",
            **env,
        }, clear=False):
            chunks = [chunk async for chunk in cloud_model.generate(
                "large", "test prompt", 8, stats)]
        return chunks, stats

    async def test_parses_sse_text_and_usage(self):
        def handler(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "mistral-small-2503")
            self.assertEqual(payload["temperature"], 0)
            body = (
                'data: {"choices":[{"delta":{"content":"hello"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":" world"}}],'
                '"usage":{"prompt_tokens":11,"completion_tokens":2}}\n\n'
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=body)

        chunks, stats = await self._generate(handler)
        self.assertEqual(chunks, ["hello", " world"])
        self.assertEqual(stats["tokens_in"], 11)
        self.assertEqual(stats["tokens_out"], 2)
        self.assertEqual(stats["usage_source"], "provider")

    async def test_parses_complete_json_response(self):
        def handler(request):
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"choices": [{"message": {"content": "complete"}}],
                      "usage": {"input_tokens": 7, "output_tokens": 1}},
            )

        chunks, stats = await self._generate(handler)
        self.assertEqual(chunks, ["complete"])
        self.assertEqual(stats["tokens_in"], 7)
        self.assertEqual(stats["tokens_out"], 1)

    async def test_retries_transient_provider_failure(self):
        attempts = 0

        def handler(request):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(429, text="busy")
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={"choices": [{"message": {"content": "retry ok"}}]},
            )

        chunks, stats = await self._generate(
            handler, NIMBUS_PROVIDER_RETRIES="1")
        self.assertEqual(attempts, 2)
        self.assertEqual(chunks, ["retry ok"])
        # A retry nobody counts is unexplained latency in the report, and
        # provider degradation is one of the incidents participants must tell
        # apart from a slow model.
        self.assertEqual(stats["upstream_retries"], 1)
        self.assertEqual(stats["provider_status"], 429)

    async def test_successful_request_reports_zero_retries(self):
        def handler(request):
            return httpx.Response(
                200, headers={"content-type": "application/json"},
                json={"choices": [{"message": {"content": "fine"}}]})

        _, stats = await self._generate(handler)
        self.assertEqual(stats["upstream_retries"], 0)
        self.assertIsNone(stats["provider_status"])


if __name__ == "__main__":
    unittest.main()


class GeminiDialectTests(unittest.IsolatedAsyncioTestCase):
    """Contract tests for the Gemini wire format.

    The bodies below are copied from real Vertex responses, because the two
    failures that matter here are both invisible to a hand-written mock: an
    empty answer when thinking eats the token budget, and a zeroed bill when a
    partial usage object overwrites the real counts.
    """

    async def asyncSetUp(self):
        self.old_http = cloud_model._http
        self.old_project = cloud_model._project
        self.old_token = cloud_model._access_token
        cloud_model._project = "test-project"
        cloud_model._access_token = AsyncMock(return_value="test-token")

    async def asyncTearDown(self):
        if cloud_model._http is not None and cloud_model._http is not self.old_http:
            await cloud_model._http.aclose()
        cloud_model._http = self.old_http
        cloud_model._project = self.old_project
        cloud_model._access_token = self.old_token

    async def _generate(self, handler, tier="large", **env):
        cloud_model._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        stats = {}
        with patch.dict(os.environ, {
            "NIMBUS_GOOGLE_API_STYLE": "gemini",
            "GOOGLE_CLOUD_LOCATION": "us-central1",
            "NIMBUS_PROVIDER_RETRIES": "0",
            "NIMBUS_PROVIDER_BACKOFF_SECONDS": "0",
            **env,
        }, clear=False):
            for key in ("NIMBUS_GOOGLE_MODEL_ID", "NIMBUS_GOOGLE_MODEL_SMALL",
                        "NIMBUS_GOOGLE_MODEL_LARGE"):
                if key not in env:
                    os.environ.pop(key, None)
            chunks = [c async for c in cloud_model.generate(tier, "q", 32, stats)]
        return chunks, stats

    # Real streamed response from gemini-2.5-flash, trimmed to three chunks.
    STREAM = (
        'data: {"candidates":[{"content":{"role":"model","parts":[{"text":"Big"}]}}],'
        '"usageMetadata":{"trafficType":"ON_DEMAND"},"modelVersion":"gemini-2.5-flash"}\n\n'
        'data: {"candidates":[{"content":{"role":"model","parts":[{"text":"-O is"}]}}],'
        '"usageMetadata":{"trafficType":"ON_DEMAND"}}\n\n'
        'data: {"candidates":[{"content":{"role":"model","parts":[{"text":" notation"}]},'
        '"finishReason":"MAX_TOKENS"}],"usageMetadata":{"promptTokenCount":7,'
        '"candidatesTokenCount":32,"totalTokenCount":39,"trafficType":"ON_DEMAND"}}\n\n'
    )

    def _stream_handler(self, seen=None):
        def handler(request):
            if seen is not None:
                seen.append((str(request.url), json.loads(request.content)))
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=self.STREAM)
        return handler

    async def test_streams_text_and_reads_usage(self):
        chunks, stats = await self._generate(self._stream_handler())
        self.assertEqual(chunks, ["Big", "-O is", " notation"])
        self.assertEqual(stats["tokens_in"], 7)
        self.assertEqual(stats["tokens_out"], 32)
        self.assertEqual(stats["usage_source"], "provider")

    async def test_partial_usage_chunks_do_not_zero_the_bill(self):
        """Every chunk carries usageMetadata; only the last carries counts.

        Treating "usageMetadata present" as "counts known" would overwrite the
        real totals with zeros on any chunk after the last, and the run would be
        reported as free.
        """
        _, stats = await self._generate(self._stream_handler())
        self.assertGreater(stats["tokens_in"], 0)
        self.assertGreater(stats["tokens_out"], 0)
        self.assertNotEqual(stats["usage_source"], "unreported")

    async def test_thinking_tokens_are_billed_as_output(self):
        body = ('data: {"candidates":[{"content":{"role":"model",'
                '"parts":[{"text":"hi"}]}}],"usageMetadata":{"promptTokenCount":7,'
                '"candidatesTokenCount":10,"thoughtsTokenCount":29,'
                '"totalTokenCount":46}}\n\n')

        def handler(request):
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=body)

        _, stats = await self._generate(handler)
        # 10 visible + 29 thinking. Charging only the visible ones would
        # understate the bill by 3x and make the cost verdict a fiction.
        self.assertEqual(stats["tokens_out"], 39)
        self.assertEqual(stats["tokens_thinking"], 29)

    async def test_thinking_is_disabled_by_default(self):
        """max_output_tokens=32 with thinking on returns NO text at all."""
        seen = []
        await self._generate(self._stream_handler(seen))
        _, body = seen[0]
        self.assertEqual(body["generationConfig"]["thinkingConfig"]["thinkingBudget"], 0)

    async def test_thinking_config_omitted_when_unset(self):
        seen = []
        await self._generate(self._stream_handler(seen),
                             NIMBUS_GEMINI_THINKING_BUDGET="none")
        _, body = seen[0]
        # gemini-2.5-pro rejects a zero budget outright, so the field has to be
        # omittable rather than merely settable.
        self.assertNotIn("thinkingConfig", body["generationConfig"])

    async def test_pro_omits_zero_budget_instead_of_sending_an_invalid_request(self):
        seen = []
        await self._generate(
            self._stream_handler(seen),
            NIMBUS_GOOGLE_MODEL_LARGE="gemini-2.5-pro",
            NIMBUS_GEMINI_THINKING_BUDGET="0")
        url, body = seen[0]
        self.assertIn("publishers/google/models/gemini-2.5-pro", url)
        self.assertNotIn("thinkingConfig", body["generationConfig"])

    async def test_pro_can_be_given_its_minimum_explicit_thinking_budget(self):
        seen = []
        await self._generate(
            self._stream_handler(seen),
            NIMBUS_GOOGLE_MODEL_LARGE="gemini-2.5-pro",
            NIMBUS_GEMINI_THINKING_BUDGET="128")
        _, body = seen[0]
        self.assertEqual(
            body["generationConfig"]["thinkingConfig"]["thinkingBudget"], 128)

    async def test_uses_the_gemini_endpoint_and_body_shape(self):
        seen = []
        await self._generate(self._stream_handler(seen))
        url, body = seen[0]
        self.assertIn("publishers/google/models/gemini-2.5-flash", url)
        self.assertIn(":streamGenerateContent", url)
        self.assertIn("alt=sse", url)
        self.assertEqual(body["contents"][0]["parts"][0]["text"], "q")
        self.assertEqual(body["generationConfig"]["maxOutputTokens"], 32)

    async def test_tiers_map_to_two_different_models(self):
        seen = []
        await self._generate(self._stream_handler(seen), tier="small")
        self.assertIn("gemini-2.5-flash-lite", seen[0][0])

    async def test_global_location_uses_the_unprefixed_host(self):
        seen = []
        await self._generate(self._stream_handler(seen), GOOGLE_CLOUD_LOCATION="global")
        self.assertIn("https://aiplatform.googleapis.com/", seen[0][0])
        self.assertIn("locations/global/", seen[0][0])


class ThinkingBudgetRangeTests(unittest.TestCase):
    """One global budget, three models, three different accepted ranges.

    Measured against the live API:
      gemini-2.5-pro         rejects 0; smallest accepted budget is 128
      gemini-2.5-flash-lite  accepts 0, then nothing until 512
      gemini-2.5-flash       accepts 0 and 128

    The decode incident sets 128 for Pro. Sending that to flash-lite is a hard
    400 at request time, which is exactly where a team goes next: MODEL_TIER
    small is the tempting shortcut, and ROUTE_EASY is the correct path. Both
    would have failed every routed request instead of showing a trade-off.
    """

    def test_pro_gets_its_floor_rather_than_an_invalid_small_budget(self):
        self.assertEqual(cloud_model._resolve_budget(1, "gemini-2.5-pro"), 128)
        self.assertEqual(cloud_model._resolve_budget(128, "gemini-2.5-pro"), 128)
        self.assertEqual(cloud_model._resolve_budget(2048, "gemini-2.5-pro"), 2048)

    def test_pro_omits_the_field_entirely_for_zero(self):
        # Pro cannot disable thinking; the field must be absent, not 0.
        self.assertIsNone(cloud_model._resolve_budget(0, "gemini-2.5-pro"))

    def test_flash_lite_clamps_down_to_zero_not_up_to_its_floor(self):
        """Keeping the cheap tier cheap is the whole point of the trap.

        Raising flash-lite to its 512 minimum would make the small model slow
        and expensive too, and "route instead of downgrading" stops being a
        lesson the numbers support.
        """
        self.assertEqual(cloud_model._resolve_budget(128, "gemini-2.5-flash-lite"), 0)
        self.assertEqual(cloud_model._resolve_budget(0, "gemini-2.5-flash-lite"), 0)
        self.assertEqual(cloud_model._resolve_budget(512, "gemini-2.5-flash-lite"), 512)

    def test_flash_lite_is_matched_before_flash(self):
        # "gemini-2.5-flash-lite" also startswith "gemini-2.5-flash".
        self.assertEqual(cloud_model._resolve_budget(128, "gemini-2.5-flash-lite"), 0)
        self.assertEqual(cloud_model._resolve_budget(128, "gemini-2.5-flash"), 128)

    def test_pinned_model_variants_still_match(self):
        self.assertEqual(cloud_model._resolve_budget(1, "gemini-2.5-pro-002"), 128)

    def test_an_unknown_model_is_left_alone(self):
        self.assertEqual(cloud_model._resolve_budget(128, "some-future-model"), 128)


class DecodeIncidentRoutingTests(unittest.IsolatedAsyncioTestCase):
    """The decode incident sets budget 128. Both tiers must remain callable."""

    async def asyncSetUp(self):
        self.old_http = cloud_model._http
        self.old_project = cloud_model._project
        self.old_token = cloud_model._access_token
        cloud_model._project = "test-project"
        cloud_model._access_token = AsyncMock(return_value="test-token")

    async def asyncTearDown(self):
        if cloud_model._http is not None and cloud_model._http is not self.old_http:
            await cloud_model._http.aclose()
        cloud_model._http = self.old_http
        cloud_model._project = self.old_project
        cloud_model._access_token = self.old_token

    async def _body_for(self, tier, **env):
        seen = []

        def handler(request):
            seen.append(json.loads(request.content))
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"},
                content='data: {"candidates":[{"content":{"role":"model",'
                        '"parts":[{"text":"x"}]}}],"usageMetadata":'
                        '{"promptTokenCount":5,"candidatesTokenCount":3}}\n\n')

        cloud_model._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch.dict(os.environ, {
            "NIMBUS_GOOGLE_API_STYLE": "gemini",
            "GOOGLE_CLOUD_LOCATION": "us-central1",
            "NIMBUS_PROVIDER_RETRIES": "0",
            "NIMBUS_GEMINI_THINKING_BUDGET": "128",
            "NIMBUS_GOOGLE_MODEL_LARGE": "gemini-2.5-pro",
            "NIMBUS_GOOGLE_MODEL_SMALL": "gemini-2.5-flash-lite",
        }, clear=False):
            os.environ.pop("NIMBUS_GOOGLE_MODEL_ID", None)
            async for _ in cloud_model.generate(tier, "q", 256, {}):
                pass
        return seen[0]

    async def test_the_large_tier_keeps_the_budget_that_makes_pro_usable(self):
        body = await self._body_for("large")
        self.assertEqual(
            body["generationConfig"]["thinkingConfig"]["thinkingBudget"], 128)

    async def test_the_small_tier_is_not_sent_an_out_of_range_budget(self):
        """MODEL_TIER=small and ROUTE_EASY=true both land here."""
        body = await self._body_for("small")
        self.assertEqual(
            body["generationConfig"]["thinkingConfig"]["thinkingBudget"], 0,
            "flash-lite rejects 128 with a hard 400")
