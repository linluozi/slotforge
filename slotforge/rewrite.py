"""Source rewriter and rollback.

The rewriter inserts one ``__slots__ = (...)`` line into a class body.  It
never reformats the rest of the file: edits are pure line insertions, so the
unified diff stays tiny and can be reverted byte-for-byte.
"""

from __future__ import annotations

import difflib
import json
import shutil
from pathlib import Path

from .scanner import ClassInfo, scan_tree

BACKUP_SUFFIX = ".slotforge.bak"


def _slot_line(info: ClassInfo) -> str:
    names = ", ".join(repr(a) for a in info.attrs)
    indent = " " * info.indent
    return f"{indent}__slots__ = ({names},)\n"


def _shim_lines(info: ClassInfo) -> str:
    if "__getstate__" in info.methods or "__setstate__" in info.methods:
        return ""
    i = " " * info.indent
    return (
        f"\n{i}def __getstate__(self):\n"
        f"{i}    return {{name: getattr(self, name) for name in self.__slots__}}\n"
        f"\n{i}def __setstate__(self, state):\n"
        f"{i}    for name, value in state.items():\n"
        f"{i}        setattr(self, name, value)\n"
    )


def plan(root: str | Path, classes: list[str] | None = None, pickle_shim: bool = False) -> list[dict]:
    root = Path(root)
    infos = [i for i in scan_tree(root) if i.status == "safe"]
    if classes is not None:
        keep = set(classes)
        infos = [i for i in infos if i.name in keep]
    plans: list[dict] = []
    for info in infos:
        path = root / info.path
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        insert_at = (info.docstring_end or info.lineno)  # 0-based index of the line after the anchor
        plans.append(
            {
                "path": info.path,
                "lineno": info.lineno,
                "name": info.name,
                "attrs": info.attrs,
                "insert_at": insert_at,
                "line": _slot_line(info) + (_shim_lines(info) if pickle_shim else ""),
            }
        )
    return plans


def apply(root: str | Path, classes: list[str] | None = None, backup: bool = True, pickle_shim: bool = False) -> dict:
    root = Path(root)
    plans = plan(root, classes, pickle_shim=pickle_shim)
    by_file: dict[str, list[dict]] = {}
    for p in plans:
        by_file.setdefault(p["path"], []).append(p)
    applied = []
    for rel, items in sorted(by_file.items()):
        path = root / rel
        original = path.read_text(encoding="utf-8")
        if backup:
            path.with_name(path.name + BACKUP_SUFFIX).write_text(original, encoding="utf-8")
        lines = original.splitlines(keepends=True)
        for item in sorted(items, key=lambda x: x["insert_at"], reverse=True):
            new = item["line"].splitlines(keepends=True)
            lines[item["insert_at"]:item["insert_at"]] = new
        path.write_text("".join(lines), encoding="utf-8")
        applied.append({"path": rel, "classes": [i["name"] for i in items]})
    return {"applied": applied, "count": len(plans)}


def rollback(root: str | Path) -> dict:
    root = Path(root)
    restored = []
    for bak in sorted(root.rglob("*" + BACKUP_SUFFIX)):
        dest = bak.with_name(bak.name[: -len(BACKUP_SUFFIX)])
        shutil.copyfile(bak, dest)
        bak.unlink()
        restored.append(str(dest.relative_to(root)))
    return {"restored": restored, "count": len(restored)}


def unified_diff(root: str | Path, classes: list[str] | None = None, pickle_shim: bool = False) -> str:
    """Return a patch without touching the tree."""
    root = Path(root)
    plans = plan(root, classes, pickle_shim=pickle_shim)
    by_file: dict[str, list[dict]] = {}
    for p in plans:
        by_file.setdefault(p["path"], []).append(p)
    chunks: list[str] = []
    for rel, items in sorted(by_file.items()):
        original = (root / rel).read_text(encoding="utf-8").splitlines(keepends=True)
        patched = list(original)
        for item in sorted(items, key=lambda x: x["insert_at"], reverse=True):
            new = item["line"].splitlines(keepends=True)
            patched[item["insert_at"]:item["insert_at"]] = new
        chunks.extend(
            difflib.unified_diff(
                original,
                patched,
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
                n=3,
            )
        )
    return "".join(chunks)


def dump_scan(root: str | Path, out: str | Path) -> dict:
    infos = scan_tree(root)
    data = {
        "root": str(root),
        "counts": {
            s: sum(1 for i in infos if i.status == s)
            for s in ("safe", "review", "unsafe", "already-slotted")
        },
        "classes": [i.to_dict() for i in infos],
    }
    Path(out).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data