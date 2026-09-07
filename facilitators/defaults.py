"""The one canonical definition of Nimbus's shipped configuration.

This existed in duplicate inside calibrate.py and eval_all.py, which is how the
repo ended up shipping with the puzzle already solved: a harness was killed
mid-config, its `finally` never ran, and nothing else knew what "shipped" meant.

`make reset-config` restores from here. Run it before committing, and before any
session.
"""
import pathlib
import re

CONFIG = pathlib.Path(__file__).resolve().parents[1] / "service" / "config.py"

# Everything off or expensive. This IS the incident.
DEFAULTS = {
    "RESPONSE_CACHE": "False",
    "PREFIX_CACHE": "False",
    "SEMANTIC_CACHE": "False",
    "SEMANTIC_CACHE_THRESHOLD": "0.92",
    "MAX_TOKENS": "32",
    "SYSTEM_PROMPT": '"LONG"',
    "RETRIEVE_K": "4",
    "ROUTE_EASY": "False",
    "MODEL_TIER": '"large"',
    "MAX_CONCURRENT": "2",
    "REPLICAS": "1",
    "SHED_ABOVE_QUEUE": "None",
}


def apply(overrides: dict | None = None) -> None:
    """Write DEFAULTS + overrides. Never a delta on current file state."""
    src = CONFIG.read_text()
    for key, val in {**DEFAULTS, **(overrides or {})}.items():
        src = re.sub(rf"^{key} = .*$", f"{key} = {val}", src, count=1, flags=re.M)
    CONFIG.write_text(src)


def current() -> dict:
    src = CONFIG.read_text()
    out = {}
    for key in DEFAULTS:
        m = re.search(rf"^{key} = (.*)$", src, flags=re.M)
        out[key] = m.group(1).strip() if m else "<missing>"
    return out


def drift() -> dict:
    """Which levers differ from shipped. Empty dict means clean."""
    return {k: (v, DEFAULTS[k]) for k, v in current().items() if v != DEFAULTS[k]}


if __name__ == "__main__":
    d = drift()
    if not d:
        print("config.py is at shipped defaults.")
    else:
        print("config.py has DRIFTED from shipped defaults:")
        for k, (is_, should) in d.items():
            print(f"  {k}: is {is_}, should be {should}")
        apply()
        print("\nrestored.")
