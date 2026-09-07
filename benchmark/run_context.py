"""Run identity and compatibility shared by the CLI and direct benchmark."""
import hashlib
import json
import pathlib


def run_directory(base, url, session):
    key = hashlib.sha256(f"{url.rstrip('/')}\n{session}".encode()).hexdigest()[:20]
    return pathlib.Path(base) / key


def next_run(directory):
    return max((int(p.stem.split("-")[1]) for p in pathlib.Path(directory).glob("run-*.json")), default=0) + 1


def context(url, session, traffic, metrics):
    return {"url": url.rstrip("/"), "session": session,
            "traffic": {k: traffic[k] for k in ("requests", "rate", "concurrency")},
            "deployment": metrics.get("deployment", {})}


def compatible(a, b):
    """Allow explicit config/model changes, but never mix workloads or services."""
    ac, bc = a.get("context"), b.get("context")
    ar, br = a.get("server_runtime", {}), b.get("server_runtime", {})
    if not ac or not bc or not ar.get("provider") or not br.get("provider"):
        return False
    return (all(ac.get(k) == bc.get(k) for k in ("url", "session", "traffic"))
            and all(ar.get(k) == br.get(k) for k in ("provider", "api_style", "location")))


def config_signature(metrics):
    data = {k: metrics.get(k, {}) for k in ("config", "runtime", "deployment")}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
