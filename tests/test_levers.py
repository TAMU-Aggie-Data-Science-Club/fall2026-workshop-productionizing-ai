"""Contract tests for changing a setting on a RUNNING service.

This endpoint exists because /reload re-reads the container's config.py, which
a participant cannot edit, and redeploying to change one value takes minutes
the activity does not have.

Two properties carry the tests. A change must be validated by exactly the same
rules startup uses, or the service accepts at runtime what it would have
refused at boot. And a batch must be all-or-nothing, because a half-applied
change makes the next measurement unattributable to anything.
"""
import os
import pathlib
import sys
import unittest
from unittest.mock import patch

# Select the cloud adapter before importing the app, so the suite does not pay
# to import torch or load local model weights.
os.environ.setdefault("NIMBUS_MODEL_BACKEND", "google")
os.environ.setdefault("NIMBUS_ADMIN_TOKEN", "test-team-token")

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "service"))
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import app as nimbus  # noqa: E402
import config  # noqa: E402
import levers  # noqa: E402

AUTH = {"X-Nimbus-Admin-Token": "test-team-token"}


class LeverEndpointTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(nimbus.app)
        self.saved = {name: getattr(config, name) for name in config.LEVERS}
        nimbus._declarations.clear()

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(config, name, value)
        nimbus._declarations.clear()

    # ── auth ─────────────────────────────────────────────────────────────
    def test_a_change_requires_the_team_token(self):
        r = self.client.post("/levers", json={"RESPONSE_CACHE": True})
        self.assertEqual(r.status_code, 401)

    def test_hypothesis_requires_the_team_token(self):
        r = self.client.post("/hypothesis", json={
            "dominant_slice": "queue", "model_implicated": False,
            "proof_metric": "tokens at baseline"})
        self.assertEqual(r.status_code, 401)

    # ── applying ─────────────────────────────────────────────────────────
    def test_applies_a_change_and_reports_what_moved(self):
        config.RESPONSE_CACHE = False
        r = self.client.post("/levers", json={"RESPONSE_CACHE": True}, headers=AUTH)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["applied"])
        self.assertEqual(body["previous"], {"RESPONSE_CACHE": False})
        self.assertEqual(body["changed"], {"RESPONSE_CACHE": True})
        self.assertTrue(config.RESPONSE_CACHE)

    def test_coerces_strings_the_way_a_form_sends_them(self):
        r = self.client.post("/levers", headers=AUTH, json={
            "RESPONSE_CACHE": "yes", "MAX_TOKENS": "64",
            "SYSTEM_PROMPT": "trimmed"})
        self.assertEqual(r.status_code, 200)
        self.assertIs(config.RESPONSE_CACHE, True)
        self.assertEqual(config.MAX_TOKENS, 64)
        self.assertEqual(config.SYSTEM_PROMPT, "TRIMMED")

    def test_accepts_the_verbose_system_prompt(self):
        r = self.client.post("/levers", headers=AUTH,
                             json={"SYSTEM_PROMPT": "verbose"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(config.SYSTEM_PROMPT, "VERBOSE")

    def test_verbose_mode_changes_the_prompt_instead_of_just_the_label(self):
        config.SYSTEM_PROMPT = "VERBOSE"
        prompt = levers.system_prompt()
        self.assertNotEqual(prompt, levers.SYSTEM_PROMPT_LONG)
        self.assertNotEqual(prompt, levers.SYSTEM_PROMPT_TRIMMED)
        # Asserted as a property, not as a phrase: pinning the wording makes
        # every edit to the instruction a test failure without telling anyone
        # whether the behaviour still holds.
        self.assertIn("depth", prompt.lower())
        self.assertNotIn("concise", prompt.lower())
        # Still carries the grounding and safety rules it inherits.
        self.assertIn("recipe notes", prompt.lower())
        self.assertIn("never guess", prompt.lower())

    def test_verbose_stays_close_to_the_baseline_prompt_in_size(self):
        """The decode incident must move output tokens and nothing else.

        Built from the 1,200-token LONG block, VERBOSE reached 788 tokens and
        gave decode a second anomaly: input tokens rose too, blurring it against
        the prompt-bloat incident and contradicting its own brief, since answers
        cannot "begin instantly" behind that much prefill.
        """
        verbose = len(levers.SYSTEM_PROMPT_VERBOSE)
        trimmed = len(levers.SYSTEM_PROMPT_TRIMMED)
        self.assertLess(verbose, trimmed * 3,
                        "VERBOSE must stay near the baseline prompt size")
        self.assertLess(verbose, len(levers.SYSTEM_PROMPT_LONG) / 2)

    def test_empty_request_is_rejected_with_the_available_settings(self):
        r = self.client.post("/levers", json={}, headers=AUTH)
        self.assertEqual(r.status_code, 400)
        self.assertIn("MAX_TOKENS", r.json()["available"])

    # ── validation ───────────────────────────────────────────────────────
    def test_rejects_a_setting_that_is_not_a_lever(self):
        r = self.client.post("/levers", json={"MODEL_BACKEND": "local"}, headers=AUTH)
        self.assertEqual(r.status_code, 400)
        self.assertIn("MODEL_BACKEND", r.json()["detail"])
        self.assertEqual(config.MODEL_BACKEND, "google")

    def test_rejects_out_of_bounds_values(self):
        for payload in ({"MAX_TOKENS": 0}, {"MAX_TOKENS": 99999},
                        {"SEMANTIC_CACHE_THRESHOLD": 1.5},
                        {"MODEL_TIER": "huge"}, {"SYSTEM_PROMPT": "MEDIUM"},
                        {"MAX_CONCURRENT": 0}):
            r = self.client.post("/levers", json=payload, headers=AUTH)
            self.assertEqual(r.status_code, 400, payload)
            self.assertFalse(r.json()["applied"])

    def test_a_batch_is_all_or_nothing(self):
        """A half-applied change makes the next measurement mean nothing."""
        config.MAX_TOKENS = 32
        config.RETRIEVE_K = 3
        r = self.client.post("/levers", headers=AUTH,
                             json={"MAX_TOKENS": 64, "RETRIEVE_K": 999})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(config.MAX_TOKENS, 32, "the valid half must NOT apply")
        self.assertEqual(config.RETRIEVE_K, 3)

    # ── the diagnose-first gate ──────────────────────────────────────────
    def test_gate_off_by_default(self):
        r = self.client.post("/levers", json={"RESPONSE_CACHE": True}, headers=AUTH)
        self.assertEqual(r.status_code, 200)

    def test_gate_blocks_a_change_until_a_diagnosis_is_on_record(self):
        with patch.dict(os.environ, {"NIMBUS_REQUIRE_HYPOTHESIS": "true"}):
            r = self.client.post("/levers", json={"RESPONSE_CACHE": True}, headers=AUTH)
            self.assertEqual(r.status_code, 409)
            self.assertEqual(r.json()["error"], "diagnose first")
            self.assertIn("/hypothesis", r.json()["how"])

    def test_gate_opens_once_a_hypothesis_is_recorded(self):
        with patch.dict(os.environ, {"NIMBUS_REQUIRE_HYPOTHESIS": "true"}):
            h = self.client.post("/hypothesis", headers=AUTH, json={
                "dominant_slice": "retrieve", "model_implicated": False,
                "proof_metric": "generate p95 at baseline",
                "predicted_lever": "SEMANTIC_CACHE",
                "predicted_direction": "p95 down, generate unchanged"})
            self.assertEqual(h.status_code, 200)
            r = self.client.post("/levers", json={"SEMANTIC_CACHE": True}, headers=AUTH)
            self.assertEqual(r.status_code, 200)

    def test_hypothesis_is_recorded_but_never_graded(self):
        """Confirming a diagnosis when it is offered ends the investigation."""
        r = self.client.post("/hypothesis", headers=AUTH, json={
            "dominant_slice": "generate", "model_implicated": True,
            "proof_metric": "output tokens 8x baseline"})
        body = r.json()
        for tell in ("correct", "right", "wrong", "incorrect", "score"):
            self.assertNotIn(tell, str(body).lower())

    # ── the change log ───────────────────────────────────────────────────
    def test_declarations_record_the_diagnosis_and_the_change(self):
        self.client.post("/hypothesis", headers=AUTH, json={
            "dominant_slice": "queue", "model_implicated": False,
            "proof_metric": "tokens at baseline"})
        self.client.post("/levers", json={"RESPONSE_CACHE": True}, headers=AUTH)
        kinds = [d["kind"] for d in self.client.get(
            "/declarations", headers=AUTH).json()["declarations"]]
        self.assertEqual(kinds, ["hypothesis", "change"])

    def test_the_incident_is_never_exposed(self):
        for path in ("/declarations",):
            body = str(self.client.get(path, headers=AUTH).json()).upper()
            self.assertNotIn("INCIDENT", body)
        body = str(self.client.post("/levers", json={"RESPONSE_CACHE": True},
                                    headers=AUTH).json()).upper()
        self.assertNotIn("INCIDENT", body)


if __name__ == "__main__":
    unittest.main()
