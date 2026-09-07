"""Per-stage stopwatch.

The point of this file is one number: the split between time a request spent
WAITING and time it spent WORKING. Without it, "diagnose before you fix" is a
slogan you cannot act on -- you cannot tell an overloaded queue from a slow
model, and those two problems have opposite fixes.
"""
import time
from contextlib import contextmanager


class Timer:
    def __init__(self) -> None:
        self.t_arrived = time.perf_counter()
        self.t_admitted: float | None = None
        self.stages: dict[str, float] = {}

    def admitted(self) -> None:
        self.t_admitted = time.perf_counter()

    @contextmanager
    def stage(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.stages[name] = self.stages.get(name, 0.0) + (time.perf_counter() - start)

    @property
    def queue_wait_ms(self) -> float:
        if self.t_admitted is None:
            return 0.0
        return (self.t_admitted - self.t_arrived) * 1000

    @property
    def compute_ms(self) -> float:
        if self.t_admitted is None:
            return 0.0
        return (time.perf_counter() - self.t_admitted) * 1000

    def headers(self) -> dict[str, str]:
        out = {
            "X-Queue-Wait-Ms": f"{self.queue_wait_ms:.1f}",
            "X-Compute-Ms": f"{self.compute_ms:.1f}",
        }
        for name, seconds in self.stages.items():
            out[f"X-Stage-{name.title()}-Ms"] = f"{seconds * 1000:.1f}"
        return out
