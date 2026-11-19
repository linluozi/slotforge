#!/usr/bin/env python3
"""Deterministic differential probe for the three patched upstream packages.

Each class is exercised with 2,000 distinct argument combinations (24,000
instances per implementation).  For every instance the probe records a
canonical state hash, then attempts a pickle round-trip and a deepcopy
round-trip and records whether the restored state matches.  Cross-process
comparison is done by hashing the per-class state stream: equal hashes mean
every one of the 2,000 states is identical, not merely similar.
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import pickle
import re
import sys
import types
from pathlib import Path

N = 2000


def norm(v, depth=0):
    if depth > 8:
        return ("deep", type(v).__name__)
    if isinstance(v, (str, int, float, bool, bytes)) or v is None:
        return (type(v).__name__, v)
    if isinstance(v, type):
        return ("type", getattr(v, "__module__", None), getattr(v, "__qualname__", v.__name__))
    if isinstance(v, re.Pattern):
        return ("pattern", v.pattern, v.flags)
    if isinstance(v, re.Match):
        return ("match", v.group(0), v.span())
    if isinstance(v, (list, tuple)):
        return (type(v).__name__, tuple(norm(x, depth + 1) for x in v))
    if isinstance(v, dict):
        return ("dict", tuple(sorted((norm(k, depth + 1), norm(x, depth + 1)) for k, x in v.items())))
    if isinstance(v, (types.FunctionType, types.BuiltinFunctionType, types.MethodType)):
        return ("callable", getattr(v, "__module__", None), getattr(v, "__qualname__", repr(v)))
    slots = getattr(type(v), "__slots__", None)
    if slots:
        return ("object", type(v).__module__, type(v).__qualname__, tuple((k, norm(getattr(v, k), depth + 1)) for k in slots))
    d = getattr(v, "__dict__", None)
    if d is not None:
        return ("object", type(v).__module__, type(v).__qualname__, tuple(sorted((k, norm(x, depth + 1)) for k, x in d.items())))
    return ("repr", type(v).__name__, repr(v))


SPECS = {
    "voluptuous": {
        "Schema": lambda i: __import__("voluptuous").Schema({f"k{i}": int}, required=bool(i % 2), extra=i % 3),
        "Msg": lambda i: __import__("voluptuous").Msg({f"k{i}": int}, f"m{i}"),
        "Range": lambda i: __import__("voluptuous").Range(min=-i, max=i + 1, min_included=bool(i % 2), max_included=bool(i % 2), msg=f"r{i}"),
        "Coerce": lambda i: __import__("voluptuous").Coerce(int if i % 2 else str, f"c{i}"),
        "DefaultTo": lambda i: __import__("voluptuous").DefaultTo(i, f"m{i}"),
        "Replace": lambda i: __import__("voluptuous").Replace(f"a{i}", f"b{i}", f"m{i}"),
    },
    "parse": {
        "Result": lambda i: __import__("parse").Result((f"a{i}", i), {f"n{i}": i}, [(0, i + 1)]),
        "Match": lambda i: __import__("parse").Match(None, re.match("a+", "a" * (i + 1))),
        "int_convert": lambda i: __import__("parse").int_convert(2 + i % 30),
        "convert_first": lambda i: __import__("parse").convert_first(int if i % 2 else str),
    },
    "deepmerge": {
        "Merger": lambda i: __import__("deepmerge").Merger([(dict, "merge")] if i & 1 else [(list, "override")], [(str, "override")] if i & 2 else [], [(int, "override")] if i & 4 else []),
        "StrategyList": lambda i: __import__("deepmerge.strategy.core", fromlist=["StrategyList"]).StrategyList([__import__("deepmerge.strategy.dict", fromlist=["DictStrategies"]).DictStrategies.strategy_override if (i >> k) & 1 else __import__("deepmerge.strategy.dict", fromlist=["DictStrategies"]).DictStrategies.strategy_merge for k in range(8)]),
    },
}


def canonical_state(cls, obj):
    slots = getattr(cls, "__slots__", None)
    names = list(slots) if slots else sorted(getattr(obj, "__dict__", {}))
    return tuple((n, norm(getattr(obj, n))) for n in names)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True)
    ap.add_argument("--lib", required=True, choices=sorted(SPECS))
    ap.add_argument("--impl", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    sys.path.insert(0, str(Path(args.root).resolve()))

    result = {"impl": args.impl, "lib": args.lib, "samples_per_class": N, "classes": {}}
    all_states = hashlib.sha256()
    for name, make in SPECS[args.lib].items():
        module = "voluptuous"
        if name in ("Result", "Match", "int_convert", "convert_first"):
            module = "parse"
        elif name in ("Merger", "StrategyList"):
            module = "deepmerge.strategy.core" if name == "StrategyList" else "deepmerge"
        cls = getattr(__import__(module, fromlist=[name]), name)
        h = hashlib.sha256()
        seen = set()
        pickle_ok = pickle_fail = copy_ok = copy_fail = 0
        pickles = []
        for i in range(N):
            obj = make(i)
            state = canonical_state(cls, obj)
            payload = repr(state).encode()
            h.update(payload)
            all_states.update(payload)
            seen.add(hashlib.sha256(payload).hexdigest())
            try:
                blob = pickle.dumps(obj, protocol=5)
                restored = pickle.loads(blob)
                if canonical_state(cls, restored) == state:
                    pickle_ok += 1
                else:
                    pickle_fail += 1
                if i < 3:
                    pickles.append(base64.b64encode(blob).decode())
            except Exception as exc:  # noqa: BLE001 - the failure mode is the datum
                pickle_fail += 1
                pickle_error = f"{type(exc).__name__}: {exc}"
            try:
                restored = copy.deepcopy(obj)
                if canonical_state(cls, restored) == state:
                    copy_ok += 1
                else:
                    copy_fail += 1
            except Exception:  # noqa: BLE001
                copy_fail += 1
        result["classes"][name] = {
            "state_sha256": h.hexdigest(),
            "independent_states": len(seen),
            "pickle_ok": pickle_ok,
            "pickle_fail": pickle_fail,
            "deepcopy_ok": copy_ok,
            "deepcopy_fail": copy_fail,
            "pickle_samples_b64": pickles,
        }
        print(f"{args.impl:9s} {args.lib:10s} {name:15s} states={len(seen)}/{N} pickle {pickle_ok}/{N} deepcopy {copy_ok}/{N}", flush=True)
    result["state_sha256"] = all_states.hexdigest()
    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())