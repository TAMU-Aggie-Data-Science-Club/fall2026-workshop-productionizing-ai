"""Run the groundedness eval across every configuration on the eval card.

Uses /reload rather than restarting, so the whole sweep costs minutes not tens
of minutes. Restores shipping defaults on exit no matter how it ends.
"""
import json, os, pathlib, re, subprocess, sys, urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
CFG = ROOT / "service" / "config.py"
PY = str(ROOT / ".venv" / "bin" / "python")
ORIGINAL = CFG.read_text()
URL = os.environ.get("NIMBUS_URL", "http://127.0.0.1:8000").rstrip("/")
ADMIN_TOKEN = os.environ.get("NIMBUS_ADMIN_TOKEN", "")

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from defaults import DEFAULTS  # noqa: E402  single source of truth


CONFIGS = [
    ("Large model, full context (as shipped)",   {}),
    ("Large model, trimmed system prompt",       {"SYSTEM_PROMPT": '"TRIMMED"'}),
    ("Large model, reduced context (K=2)",       {"RETRIEVE_K": "2"}),
    ("Large model, shorter answers (24 tokens)", {"MAX_TOKENS": "24"}),
    ("Routing: easy -> small, hard -> large",    {"ROUTE_EASY": "True"}),
    ("Small model for EVERYTHING",               {"MODEL_TIER": '"small"'}),
    ("Semantic cache, threshold 0.92",           {"SEMANTIC_CACHE": "True"}),
    ("Semantic cache, threshold 0.80",           {"SEMANTIC_CACHE": "True",
                                                  "SEMANTIC_CACHE_THRESHOLD": "0.80"}),
    ("Everything on (rungs 2-4)",                {"RESPONSE_CACHE": "True",
                                                  "PREFIX_CACHE": "True",
                                                  "SEMANTIC_CACHE": "True",
                                                  "SYSTEM_PROMPT": '"TRIMMED"',
                                                  "MAX_TOKENS": "24", "RETRIEVE_K": "3",
                                                  "ROUTE_EASY": "True"}),
]


def patch(overrides):
    src = ORIGINAL
    for k, v in {**DEFAULTS, **overrides}.items():
        src = re.sub(rf"^{k} = .*$", f"{k} = {v}", src, count=1, flags=re.M)
    CFG.write_text(src)


def reload_server():
    req = urllib.request.Request(
        f"{URL}/reload", method="POST", data=b"",
        headers={"X-Nimbus-Admin-Token": ADMIN_TOKEN} if ADMIN_TOKEN else {})
    urllib.request.urlopen(req, timeout=120).read()


def require_server():
    """Fail loudly and immediately if Nimbus is not up.

    A sweep that keeps going against a dead server produces a file full of
    zeroes that looks like data.
    """
    try:
        urllib.request.urlopen(f"{URL}/health", timeout=5).read()
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"Nimbus is not responding ({exc}). Start `make serve` first.")


rows = []
require_server()
try:
    for label, overrides in CONFIGS:
        require_server()
        patch(overrides)
        reload_server()
        out = subprocess.run([PY, str(ROOT / "facilitators" / "eval.py"), "--label", label],
                             capture_output=True, text=True, timeout=1800)
        stdout = out.stdout.strip().splitlines()
        if not stdout:
            # Surface the child's own error instead of dying on an IndexError
            # three lines later with the real cause discarded.
            print(f"  !! {label}: eval.py produced no output (exit {out.returncode})",
                  flush=True)
            print("     stderr:", (out.stderr or "").strip()[-800:], flush=True)
            continue
        data = json.loads(stdout[0])
        rows.append(data)
        # Persist after EVERY config: one failure at config 3 should not throw
        # away configs 1 and 2.
        (ROOT / "facilitators" / "eval_results.json").write_text(json.dumps(rows, indent=2))
        print(f"{data['score_pct']:5.1f}%  {label}  "
              f"(extraction {data['extraction_pct']:.0f}%, reasoning {data['reasoning_pct']:.0f}%)",
              flush=True)
finally:
    patch({})
    try:
        reload_server()
    except Exception:
        pass

print("\n=== EVAL CARD (measured) ===")
for r in rows:
    print(f"| {r['label']} | {r['score_pct']:.0f}% |")
