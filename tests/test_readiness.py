"""Regression coverage for false readiness and cross-team/run contamination."""
import argparse
import asyncio
import copy
import importlib.machinery
import io
import json
import os
import pathlib
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest.mock import patch

import httpx

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / p) for p in ("facilitators", "benchmark", "service")]
import preflight
import deploy_incident
import run
import report
from run_context import compatible, run_directory
from test_report import _payload, _row, SCENARIO
from test_levers import nimbus, config, AUTH


class ResponseReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_stats_and_done_without_text_is_failure(self):
        for delta in (None, "", "   "):
            body = (f'data: {json.dumps({"delta": delta})}\n\n' if delta is not None else "")
            body += 'data: {"stats":{"tokens_out":0}}\n\ndata: [DONE]\n\n'
            async with httpx.AsyncClient(transport=httpx.MockTransport(
                    lambda req: httpx.Response(200, text=body))) as client:
                rows = []
                await run.one_request(client, "http://test", "question", rows, asyncio.Semaphore(1))
                self.assertFalse(rows[0]["ok"])

    async def test_warmup_does_not_seed_truncated_answers(self):
        bodies = []
        def handle(req):
            bodies.append(json.loads(req.content))
            return httpx.Response(200, text="data: [DONE]\n\n")
        original = httpx.AsyncClient
        with patch.object(run.httpx, "AsyncClient", side_effect=lambda **kwargs:
                          original(transport=httpx.MockTransport(handle))):
            await run.warmup("http://test", 2)
        self.assertTrue(bodies)
        self.assertTrue(all("max_tokens" not in b for b in bodies))


class RunIsolationTests(unittest.TestCase):
    def test_cli_init_starts_new_private_session_and_preserves_old_runs(self):
        import importlib.util
        loader = importlib.machinery.SourceFileLoader("nimbus_cli_test", str(ROOT / "cli" / "nimbus"))
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cli = importlib.util.module_from_spec(spec)
        loader.exec_module(cli)
        with tempfile.TemporaryDirectory() as tmp, patch.object(cli, "_http", return_value=(200, {"ok": True})), redirect_stdout(io.StringIO()):
            cli.CONFIG = pathlib.Path(tmp) / "config.json"
            args = argparse.Namespace(url="https://team", token="secret", session=None)
            cli.cmd_init(args)
            first = json.loads(cli.CONFIG.read_text())
            cli.cmd_init(args)
            second = json.loads(cli.CONFIG.read_text())
            self.assertNotEqual(first["session"], second["session"])
            self.assertEqual(cli.CONFIG.stat().st_mode & 0o777, 0o600)

    def test_history_is_partitioned_by_url_and_session(self):
        self.assertNotEqual(run_directory("runs", "https://a", "one"), run_directory("runs", "https://b", "one"))
        self.assertNotEqual(run_directory("runs", "https://a", "one"), run_directory("runs", "https://a", "two"))

    def test_comparisons_reject_cross_backend_service_session_or_traffic(self):
        a = _payload([_row(1, 1, {"generate": 900})])
        self.assertTrue(compatible(a, copy.deepcopy(a)))
        for key, value in (("url", "https://other"), ("session", "other"), ("traffic", {"rate": 99})):
            b = copy.deepcopy(a); b["context"][key] = value
            self.assertFalse(compatible(a, b))
        b = copy.deepcopy(a); b["server_runtime"]["provider"] = "google"
        self.assertFalse(compatible(a, b))
        b = copy.deepcopy(a); b.pop("context")
        self.assertFalse(compatible(a, b))

    def test_google_baseline_is_not_applied_to_local(self):
        scenario = {**SCENARIO, "baselines": {"_backend": "google", "default": {"tokens_in": 226}}}
        self.assertIsNone(report._baseline(scenario, "tokens_in", "local"))
        self.assertEqual(report._baseline(scenario, "tokens_in", "google"), 226)

    def test_recovery_requires_all_requests_and_matching_quality(self):
        p = _payload([_row(.5, 1, {"generate": 400}, tokens_in=1, tokens_out=1)],
                     configuration_stable=True, config_signature="current")
        self.assertFalse(report.recovery(p, SCENARIO)["recovered"])
        p["quality"] = {"signature": "current", "score_pct": 90}
        self.assertTrue(report.recovery(p, SCENARIO)["recovered"])
        p["results"].append({"ok": False, "shed": True})
        self.assertFalse(report.recovery(p, SCENARIO)["recovered"])
        p["results"].pop(); p["quality"]["signature"] = "old"
        self.assertFalse(report.recovery(p, SCENARIO)["recovered"])


class ModelVerificationTests(unittest.TestCase):
    def test_gate_and_small_incident_survive_both_model_checks(self):
        from fastapi.testclient import TestClient
        before = {k: getattr(config, k) for k in config.LEVERS}
        previous_sem = nimbus._state["semaphore"]
        previous_declarations = list(nimbus._declarations)
        calls = []
        async def generate(tier, prompt, max_tokens, stats, prefix):
            calls.append(tier)
            stats.update(model=f"actual-{tier}", usage_source="provider")
            yield "real answer"
        try:
            config.MODEL_TIER = "small"
            nimbus._state["semaphore"] = asyncio.Semaphore(1)
            with patch.dict(os.environ, NIMBUS_REQUIRE_HYPOTHESIS="true"), patch.object(nimbus.model, "generate", generate):
                client = TestClient(nimbus.app)
                self.assertEqual(client.post("/verify-models").status_code, 401)
                result = client.post("/verify-models", headers=AUTH)
                self.assertTrue(result.json()["ok"])
                self.assertEqual(calls, ["large", "small"])
                self.assertEqual(config.MODEL_TIER, "small")
                self.assertTrue(nimbus._require_hypothesis())
                self.assertEqual(nimbus._declarations, previous_declarations)
        finally:
            for key, value in before.items(): setattr(config, key, value)
            nimbus._state["semaphore"] = previous_sem


class PreflightTests(unittest.TestCase):
    def test_missing_token_cannot_report_ready(self):
        self.assertTrue(preflight.check("http://test", ""))

    def test_model_identity_mismatch_cannot_report_ready(self):
        def get(url, token=None):
            if url.endswith("/health"):
                return {"ok": True, "status": "ready", "note_chunks": 48, "backend": "google"}
            if not token or token == "preflight-invalid-token":
                raise urllib.error.HTTPError(url, 401, "auth", {}, None)
            if url.endswith("/declarations"): return {"declarations": [], "hypothesis_required": True}
            return {"config": {"MODEL_TIER": "small"}, "runtime": {"provider": "google", "model_large": "large", "model_small": "small"}}
        tiers = {tier: {"ok": True, "text": "answer", "model": "large", "usage_source": "provider"} for tier in ("large", "small")}
        with patch.object(preflight, "_get", side_effect=get), patch.object(preflight, "_post", return_value={"ok": True, "tiers": tiers}), patch.object(preflight, "_ask", return_value=("answer", {"model": "small"}, None)), redirect_stdout(io.StringIO()):
            problems = preflight.check("http://test", "valid")
        self.assertIn("small tier did not confirm its configured model", problems)


class DeploymentIsolationTests(unittest.TestCase):
    def test_two_team_deploys_share_one_digest_and_distinct_secrets(self):
        digest = "us-central1-docker.pkg.dev/test/nimbus/nimbus@sha256:" + "a" * 64
        captured = []
        def execute(cmd, **kwargs):
            captured.append(kwargs["env"])
            return type("Result", (), {"returncode": 0})()
        with patch.object(sys, "argv", ["deploy", "--all", "--teams", "2", "--run"]), patch.object(deploy_incident, "load_environment", return_value={}), patch.object(deploy_incident, "build_image", return_value=digest) as build, patch.object(deploy_incident, "ensure_team_secret"), patch.object(deploy_incident.subprocess, "run", side_effect=execute), redirect_stdout(io.StringIO()):
            deploy_incident.main()
        build.assert_called_once()
        self.assertEqual(len(captured), 2)
        self.assertEqual({e["NIMBUS_IMAGE"] for e in captured}, {digest})
        self.assertEqual(len({e["NIMBUS_ADMIN_SECRET"] for e in captured}), 2)

    def test_rounds_share_only_their_own_team_secret(self):
        a = deploy_incident.env_for("queue", "nimbus-team-a-r1", False)
        b = deploy_incident.env_for("prompt", "nimbus-team-a-r2", True)
        c = deploy_incident.env_for("prompt", "nimbus-team-b-r2", True)
        self.assertEqual(a["NIMBUS_ADMIN_SECRET"], b["NIMBUS_ADMIN_SECRET"])
        self.assertNotEqual(a["NIMBUS_ADMIN_SECRET"], c["NIMBUS_ADMIN_SECRET"])
