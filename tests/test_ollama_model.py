"""Contract tests for the Docker-local Ollama model adapter."""
import json
import os
import pathlib
import sys
import unittest
from unittest.mock import patch

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))

import ollama_model  # noqa: E402


class OllamaModelContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.old_http = ollama_model._http

    async def asyncTearDown(self):
        if ollama_model._http is not None and ollama_model._http is not self.old_http:
            await ollama_model._http.aclose()
        ollama_model._http = self.old_http

    async def _generate(self, handler, **env):
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        ollama_model._http = client
        stats = {}
        with patch.dict(os.environ, {
            "NIMBUS_OLLAMA_BASE_URL": "http://ollama.test:11434",
            "NIMBUS_OLLAMA_MODEL_LARGE": "llama3.1:8b",
            "NIMBUS_OLLAMA_RETRIES": "0",
            **env,
        }, clear=False):
            chunks = [chunk async for chunk in ollama_model.generate(
                "large", "test prompt", 8, stats)]
        return chunks, stats

    async def test_parses_ndjson_text_and_usage(self):
        def handler(request):
            payload = json.loads(request.content)
            self.assertEqual(payload["model"], "llama3.1:8b")
            self.assertEqual(payload["options"]["temperature"], 0)
            self.assertEqual(payload["options"]["num_predict"], 8)
            self.assertEqual(payload["keep_alive"], "30m")
            self.assertEqual(payload["messages"][0]["content"], "test prompt")
            body = (
                '{"message":{"role":"assistant","content":"hello"},"done":false}\n'
                '{"message":{"role":"assistant","content":" world"},'
                '"done":true,"prompt_eval_count":11,"eval_count":2}\n'
            )
            return httpx.Response(200, headers={"content-type": "application/x-ndjson"},
                                  content=body)

        chunks, stats = await self._generate(handler)
        self.assertEqual(chunks, ["hello", " world"])
        self.assertEqual(stats["tokens_in"], 11)
        self.assertEqual(stats["tokens_out"], 2)
        self.assertEqual(stats["usage_source"], "provider")
        self.assertEqual(stats["provider"], "ollama")

    async def test_retries_transient_local_failure(self):
        attempts = 0

        def handler(request):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                return httpx.Response(503, text="loading")
            return httpx.Response(
                200,
                headers={"content-type": "application/x-ndjson"},
                content='{"message":{"content":"retry ok"},"done":true}\n',
            )

        chunks, _ = await self._generate(handler, NIMBUS_OLLAMA_RETRIES="1")
        self.assertEqual(attempts, 2)
        self.assertEqual(chunks, ["retry ok"])

    def test_warm_accepts_pulled_models(self):
        response = httpx.Response(
            200,
            json={"models": [{"name": "llama3.1:8b", "model": "llama3.1:8b"}]},
        )
        with patch.dict(os.environ, {
            "NIMBUS_OLLAMA_BASE_URL": "http://ollama.test:11434",
            "NIMBUS_OLLAMA_MODEL_SMALL": "llama3.1:8b",
            "NIMBUS_OLLAMA_MODEL_LARGE": "llama3.1:8b",
        }, clear=False), patch("ollama_model.httpx.get", return_value=response) as get:
            ollama_model.warm()
        get.assert_called_once_with("http://ollama.test:11434/api/tags", timeout=360.0)

    def test_warm_reports_missing_models(self):
        response = httpx.Response(200, json={"models": []})
        with patch.dict(os.environ, {
            "NIMBUS_OLLAMA_BASE_URL": "http://ollama.test:11434",
            "NIMBUS_OLLAMA_MODEL_SMALL": "llama3.1:8b",
            "NIMBUS_OLLAMA_MODEL_LARGE": "llama3.1:8b",
        }, clear=False), patch("ollama_model.httpx.get", return_value=response):
            with self.assertRaisesRegex(ollama_model.ProviderError, "not pulled"):
                ollama_model.warm()


if __name__ == "__main__":
    unittest.main()
