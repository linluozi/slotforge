#!/usr/bin/env python3
"""Measure per-instance memory and construction throughput for slotted classes.

Usage:
    python benchmark/bench.py --root /tmp/c-vol --lib voluptuous --n 100000 --out benchmark/raw/voluptuous-baseline-100000.json
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from slotforge.measure import live_bytes, throughput  # noqa: E402

# (module, class, factory).  The factories use only arguments that the
# pristine class accepts; the patched class accepts exactly the same.
SPECS: dict[str, list[tuple[str, str, object]]] = {
    "voluptuous": [
        ("voluptuous.schema_builder", "Schema", lambda: __import__("voluptuous").Schema(int)),
        (
            "voluptuous.schema_builder",
            "Msg",
            lambda: __import__("voluptuous").Msg(int, "must be int"),
        ),
        ("voluptuous.validators", "Range", lambda: __import__("voluptuous").Range(min=1, max=10)),
        ("voluptuous.validators", "Coerce", lambda: __import__("voluptuous").Coerce(int)),
        ("voluptuous.util", "DefaultTo", lambda: __import__("voluptuous").DefaultTo(42)),
        (
            "voluptuous.validators",
            "Replace",
            lambda: __import__("voluptuous").Replace("a", "b"),
        ),
    ],
    "parse": [
        ("parse", "Result", lambda: __import__("parse").Result(("a",), {"x": 1}, [(0, 1)])),
        ("parse", "Match", lambda: __import__("parse").Match(None, None)),
        ("parse", "int_convert", lambda: __import__("parse").int_convert(16)),
        ("parse", "convert_first", lambda: __import__("parse").convert_first(int)),
    ],
    "deepmerge": [
        ("deepmerge.merger", "Merger", lambda: __import__("deepmerge").Merger([], [], [])),
        (
            "deepmerge.strategy.core",
            "StrategyList",
            lambda: __import__("deepmerge.strategy.core", fromlist=["StrategyList"]).StrategyList([]),
        ),
    ],
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="directory that contains the package")
    ap.add_argument("--lib", required=True, choices=sorted(SPECS))
    ap.add_argument("--n", type=int, required=True)
    ap.add_argument("--impl", default="baseline")
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=("memory", "throughput", "both"), default="both")
    ap.add_argument("--memory-repeats", type=int, default=1)
    ap.add_argument("--throughput-n", type=int, default=50000)
    args = ap.parse_args()

    sys.path.insert(0, str(Path(args.root).resolve()))
    # Import once so import-time allocations are not charged to the samples.
    started = time.time()
    for module, _cls, _mk in SPECS[args.lib]:
        importlib.import_module(module)

    result = {
        "impl": args.impl,
        "lib": args.lib,
        "root": str(Path(args.root).resolve()),
        "n": args.n,
        "python": sys.version.split()[0],
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "classes": {},
    }
    for module, cls_name, make in SPECS[args.lib]:
        cls = getattr(importlib.import_module(module), cls_name)
        row = {"module": module, "class": cls_name}
        if args.mode in ("memory", "both"):
            row["memory"] = live_bytes(make, args.n)
        if args.mode in ("throughput", "both"):
            row["throughput"] = throughput(make, args.throughput_n)
        result["classes"][cls_name] = row
        print(
            f"{args.impl:9s} {args.lib:10s} {cls_name:20s} n={args.n:>8d} "
            f"mem={row.get('memory', {}).get('bytes_per_instance', float('nan')):8.2f} B "
            f"tput={row.get('throughput', {}).get('median_ns', float('nan')):8.1f} ns/op",
            flush=True,
        )
    result["elapsed_s"] = round(time.time() - started, 3)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())