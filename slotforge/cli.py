"""Command line entry point.

    slotforge scan  <path> [--json OUT]
    slotforge patch <path> [--class NAME ...] [--pickle-shim] [--no-backup]
    slotforge diff  <path> [--class NAME ...] [--pickle-shim]
    slotforge rollback <path>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .rewrite import apply, dump_scan, rollback, unified_diff


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="slotforge", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="classify every class in a source tree")
    p_scan.add_argument("path")
    p_scan.add_argument("--json", dest="json_out")

    for name in ("patch", "diff"):
        p = sub.add_parser(name, help="insert __slots__ (patch) or print the diff")
        p.add_argument("path")
        p.add_argument("--class", dest="classes", action="append", default=None)
        p.add_argument("--pickle-shim", action="store_true", help="also add __getstate__/__setstate__")
        if name == "patch":
            p.add_argument("--no-backup", action="store_true")

    p_rb = sub.add_parser("rollback", help="restore every .slotforge.bak file")
    p_rb.add_argument("path")

    args = ap.parse_args(argv)
    if args.cmd == "scan":
        data = dump_scan(args.path, args.json_out) if args.json_out else None
        if data is None:
            from .scanner import scan_tree

            infos = scan_tree(args.path)
            data = {
                "counts": {
                    s: sum(1 for i in infos if i.status == s)
                    for s in ("safe", "review", "unsafe", "already-slotted")
                },
                "classes": [i.to_dict() for i in infos],
            }
        print(json.dumps(data["counts"], sort_keys=True))
        for c in data["classes"]:
            if c["status"] == "safe":
                print(f"safe  {c['path']}:{c['lineno']} {c['name']} attrs={c['attrs']}")
        return 0
    if args.cmd == "diff":
        sys.stdout.write(unified_diff(args.path, args.classes, pickle_shim=args.pickle_shim))
        return 0
    if args.cmd == "patch":
        res = apply(args.path, args.classes, backup=not args.no_backup, pickle_shim=args.pickle_shim)
        print(json.dumps(res, indent=2))
        return 0
    if args.cmd == "rollback":
        print(json.dumps(rollback(args.path), indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())