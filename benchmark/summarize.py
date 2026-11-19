#!/usr/bin/env python3
"""Aggregate evidence/raw into committed baseline/optimized summaries."""

from __future__ import annotations

import glob
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "raw"


def main() -> int:
    rows = {}
    for f in sorted(glob.glob(str(RAW / "*.json"))):
        d = json.loads(Path(f).read_text())
        rows[(d["lib"], d["impl"], d["n"])] = d

    libs = sorted({k[0] for k in rows})
    baseline = {"python": rows[libs[0], "baseline", 10000]["python"], "libs": {}}
    optimized = {"python": baseline["python"], "libs": {}}
    summary = {"libs": {}, "all_classes": {}}

    for lib in libs:
        classes = sorted(rows[(lib, "baseline", 1000000)]["classes"])
        b_out = {"scales": {}, "classes": {}}
        o_out = {"scales": {}, "classes": {}}
        for n in (10000, 100000, 1000000):
            b_out["scales"][str(n)] = rows[(lib, "baseline", n)]["classes"]
            o_out["scales"][str(n)] = rows[(lib, "optimized", n)]["classes"]
        for c in classes:
            b1 = rows[(lib, "baseline", 1000000)]["classes"][c]
            o1 = rows[(lib, "optimized", 1000000)]["classes"][c]
            b_out["classes"][c] = {
                "module": b1["module"],
                "bytes_per_instance_1m": b1["memory"]["bytes_per_instance"],
                "throughput_ns": b1["throughput"]["median_ns"],
            }
            o_out["classes"][c] = {
                "module": o1["module"],
                "bytes_per_instance_1m": o1["memory"]["bytes_per_instance"],
                "throughput_ns": o1["throughput"]["median_ns"],
            }
            row = {
                "lib": lib,
                "class": c,
                "baseline_bytes": b1["memory"]["bytes_per_instance"],
                "optimized_bytes": o1["memory"]["bytes_per_instance"],
                "saved_pct": 100.0
                * (1.0 - o1["memory"]["bytes_per_instance"] / b1["memory"]["bytes_per_instance"]),
                "baseline_ns": b1["throughput"]["median_ns"],
                "optimized_ns": o1["throughput"]["median_ns"],
                "throughput_ratio": b1["throughput"]["median_ns"] / o1["throughput"]["median_ns"],
            }
            summary["all_classes"][f"{lib}.{c}"] = row
        baseline["libs"][lib] = b_out
        optimized["libs"][lib] = o_out

    saved = [r["saved_pct"] for r in summary["all_classes"].values()]
    ratios = [r["throughput_ratio"] for r in summary["all_classes"].values()]
    summary["median_saved_pct"] = statistics.median(saved)
    summary["min_saved_pct"] = min(saved)
    summary["max_saved_pct"] = max(saved)
    summary["median_throughput_ratio"] = statistics.median(ratios)
    summary["min_throughput_ratio"] = min(ratios)
    baseline["summary"] = summary
    optimized["summary"] = summary

    (ROOT / "baseline.json").write_text(json.dumps(baseline, indent=2), encoding="utf-8")
    (ROOT / "optimized.json").write_text(json.dumps(optimized, indent=2), encoding="utf-8")
    (ROOT.parent / "evidence" / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        f"classes={len(saved)} median_saved={summary['median_saved_pct']:.2f}% "
        f"min_saved={summary['min_saved_pct']:.2f}% "
        f"median_throughput={summary['median_throughput_ratio']:.3f}x "
        f"min_throughput={summary['min_throughput_ratio']:.3f}x"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())