#!/usr/bin/env python3
"""Peak RSS for 1,000,000 live instances (one class, fresh process)."""
from __future__ import annotations

import argparse
import json
import resource
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--lib", required=True)
    ap.add_argument("--class", dest="cls", required=True)
    ap.add_argument("--n", type=int, default=1_000_000)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    sys.path.insert(0, str(Path(a.root).resolve()))
    import importlib

    specs = {
        "Schema": ("voluptuous", lambda: __import__("voluptuous").Schema(int)),
        "Result": ("parse", lambda: __import__("parse").Result(("a",), {"x": 1}, [(0, 1)])),
        "Merger": ("deepmerge", lambda: __import__("deepmerge").Merger([], [], [])),
        "StrategyList": ("deepmerge.strategy.core", lambda: __import__("deepmerge.strategy.core", fromlist=["StrategyList"]).StrategyList([])),
        "Range": ("voluptuous", lambda: __import__("voluptuous").Range(min=1, max=10)),
        "Coerce": ("voluptuous", lambda: __import__("voluptuous").Coerce(int)),
        "int_convert": ("parse", lambda: __import__("parse").int_convert(16)),
    }
    module, make = specs[a.cls]
    cls = getattr(importlib.import_module(module), a.cls)
    rss0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    objs = [make() for _ in range(a.n)]
    rss1 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    out = {
        "lib": a.lib,
        "class": a.cls,
        "n": a.n,
        "rss_before_kb": rss0,
        "rss_after_kb": rss1,
        "delta_mb": (rss1 - rss0) / 1024.0,
        "live": len(objs),
        "has_dict": hasattr(objs[0], "__dict__"),
    }
    Path(a.out).write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
