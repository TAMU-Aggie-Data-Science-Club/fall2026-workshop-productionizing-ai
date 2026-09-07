"""Regression tests for benchmark response classification."""
import asyncio
import pathlib
import sys
import unittest

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "benchmark"))

import run  # noqa: E402


class BenchmarkResponseTests(unittest.TestCase):
    def test_stream_error_is_not_counted_as_success(self):
        async def handler(request):
            body = (
                'data: {"error":{"code":"request_failed",'
                '"message":"temporary upstream failure"}}\n\n'
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=body)

        async def exercise():
            results = []
            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            try:
                await run.one_request(client, "http://nimbus.test", "question", results,
                                      asyncio.Semaphore(1))
            finally:
                await client.aclose()
            return results

        results = asyncio.run(exercise())
        self.assertEqual(len(results), 1)
        self.assertFalse(results[0]["ok"])
        self.assertFalse(results[0]["shed"])
        self.assertIn("temporary upstream failure", results[0]["error"])


if __name__ == "__main__":
    unittest.main()
