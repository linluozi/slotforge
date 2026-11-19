"""Measurement primitives: per-instance memory and construction throughput."""

from __future__ import annotations

import gc
import statistics
import time
import tracemalloc
from typing import Callable


def _peak_bytes(make: Callable, n: int) -> int:
    gc.collect()
    gc.disable()
    try:
        tracemalloc.start()
        objs = [make() for _ in range(n)]
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        del objs
        return peak
    finally:
        gc.enable()


def _spine_bytes(n: int) -> int:
    gc.collect()
    gc.disable()
    try:
        tracemalloc.start()
        spine = [None] * n
        _current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        del spine
        return peak
    finally:
        gc.enable()


def memory_per_instance(make: Callable, n: int, repeats: int = 3) -> dict:
    spine = _spine_bytes(n)
    samples = []
    for _ in range(repeats):
        peak = _peak_bytes(make, n)
        samples.append(max(0.0, (peak - spine) / n))
    samples.sort()
    return {
        "n": n,
        "spine_bytes": spine,
        "samples": samples,
        "median": statistics.median(samples),
        "p25": statistics.quantiles(samples, n=4)[0] if len(samples) > 1 else samples[0],
        "p75": statistics.quantiles(samples, n=4)[2] if len(samples) > 1 else samples[0],
    }


def live_bytes(make: Callable, n: int) -> dict:
    """Live heap bytes for N objects, measured with tracemalloc's current size.

    The list spine is measured in a separate tracemalloc session and subtracted;
    freed construction temporaries are not counted because we read the current
    size after the list has been built, not the peak.
    """
    gc.collect()
    gc.disable()
    try:
        tracemalloc.start()
        objs = [make() for _ in range(n)]
        current = tracemalloc.get_traced_memory()[0]
        tracemalloc.stop()
        del objs

        tracemalloc.start()
        spine = [None] * n
        spine_bytes = tracemalloc.get_traced_memory()[0]
        tracemalloc.stop()
        del spine
    finally:
        gc.enable()
    per = (current - spine_bytes) / n
    return {"n": n, "total_bytes": current - spine_bytes, "spine_bytes": spine_bytes, "bytes_per_instance": per}


def own_bytes(make: Callable, n: int) -> dict:
    """Own allocation of N live instances: instance object + its instance dict.

    Referenced children (e.g. a compiled schema held by a Schema instance) are
    deliberately excluded; they are identical in both layouts.
    """
    import sys
    objs = [make() for _ in range(n)]
    total = 0
    for obj in objs:
        total += sys.getsizeof(obj)
        d = getattr(obj, "__dict__", None)
        if d is not None:
            total += sys.getsizeof(d)
    return {"n": n, "total_bytes": total, "bytes_per_instance": total / n}


def throughput(make: Callable, n: int, warmup: int = 3, reps: int = 5) -> dict:
    for _ in range(warmup):
        for _ in range(n):
            make()
    samples = []
    for _ in range(reps):
        gc.collect()
        t0 = time.perf_counter()
        for _ in range(n):
            make()
        samples.append((time.perf_counter() - t0) / n * 1e9)
    ordered = sorted(samples)
    return {
        "n": n,
        "samples_ns": samples,
        "median_ns": statistics.median(samples),
        "p25": statistics.quantiles(ordered, n=4)[0] if len(ordered) > 1 else ordered[0],
        "p75": statistics.quantiles(ordered, n=4)[2] if len(ordered) > 1 else ordered[0],
    }