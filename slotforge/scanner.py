"""Static scanner: find classes whose instance layout can safely use __slots__.

The scanner is deliberately conservative.  A class is only ``safe`` when every
attribute it stores is a plain ``self.name = ...`` assignment inside
``__init__``, the class has no non-object base, no decorator, no class-level
attribute with the same name as a slot, and never touches ``__dict__`` /
``__weakref__`` / ``setattr``.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

STORE_ATTRS = (ast.Store, ast.Del)


@dataclass
class ClassInfo:
    path: str
    lineno: int
    end_lineno: int
    name: str
    bases: list[str]
    decorators: list[str]
    indent: int
    attrs: list[str] = field(default_factory=list)
    methods: list[str] = field(default_factory=list)
    status: str = "review"
    reasons: list[str] = field(default_factory=list)
    docstring_end: int | None = None

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "lineno": self.lineno,
            "end_lineno": self.end_lineno,
            "name": self.name,
            "bases": self.bases,
            "decorators": self.decorators,
            "attrs": self.attrs,
            "status": self.status,
            "reasons": self.reasons,
        }


def _attr_stores(node: ast.AST) -> set[str]:
    """Return names stored as ``self.<name>`` anywhere under *node*."""
    out: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and isinstance(sub.ctx, STORE_ATTRS):
            if isinstance(sub.value, ast.Name) and sub.value.id == "self":
                out.add(sub.attr)
    return out


def _touches_dynamic_layout(node: ast.AST) -> list[str]:
    reasons: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name):
            if sub.value.id in ("self", "cls") and sub.attr in ("__dict__", "__weakref__"):
                reasons.append(f"touches {sub.value.id}.{sub.attr}")
        elif isinstance(sub, ast.Call):
            fn = sub.func
            if isinstance(fn, ast.Name) and fn.id in ("vars", "setattr", "delattr"):
                if sub.args and isinstance(sub.args[0], ast.Name) and sub.args[0].id in ("self", "cls"):
                    reasons.append(f"calls {fn.id}(self, ...)")
        elif isinstance(sub, ast.FunctionDef) and sub.name in ("__setattr__", "__getattr__", "__delattr__"):
            reasons.append(f"defines {sub.name}")
    return reasons


def _class_body_names(node: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(stmt.name)
        elif isinstance(stmt, ast.Assign):
            for t in stmt.targets:
                if isinstance(t, ast.Name):
                    names.add(t.id)
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            names.add(stmt.target.id)
    return names


def _first_body_line(node: ast.ClassDef) -> int:
    """Line number of the first statement in the class body."""
    return node.body[0].lineno if node.body else node.lineno + 1


def _docstring_end(node: ast.ClassDef) -> int | None:
    if node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant):
        if isinstance(node.body[0].value.value, str):
            return node.body[0].end_lineno
    return None


def classify(node: ast.ClassDef, path: str) -> ClassInfo:
    bases = [ast.unparse(b) for b in node.bases]
    decorators = [ast.unparse(d) for d in node.decorator_list]
    unsafe: list[str] = []
    review: list[str] = []
    info = ClassInfo(
        path=path,
        lineno=node.lineno,
        end_lineno=node.end_lineno or node.lineno,
        name=node.name,
        bases=bases,
        decorators=decorators,
        indent=node.body[0].col_offset if node.body else 4,
        docstring_end=_docstring_end(node),
    )

    body_names = _class_body_names(node)
    if "__slots__" in body_names:
        info.status = "already-slotted"
        info.reasons.append("__slots__ already declared")
        return info

    if bases and bases != ["object"]:
        review.append(f"non-object base(s): {', '.join(bases)}")
    if decorators:
        review.append(f"decorated: {', '.join(decorators)}")
    init = next(
        (s for s in node.body if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) and s.name == "__init__"),
        None,
    )
    if init is None:
        review.append("no __init__")

    attrs = sorted(_attr_stores(init)) if init is not None else []
    attrs = [a for a in attrs if not (a.startswith("__") and a.endswith("__"))]
    outside: set[str] = set()
    for stmt in node.body:
        if stmt is init:
            continue
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            outside |= _attr_stores(stmt)
    outside -= set(attrs)
    if outside:
        unsafe.append("attrs assigned outside __init__: " + ", ".join(sorted(outside)))

    for stmt in node.body:
        unsafe.extend(_touches_dynamic_layout(stmt))
    unsafe = sorted(set(unsafe))

    if not attrs:
        review.append("no instance attrs found in __init__")

    conflicts = sorted(set(attrs) & (body_names - {"__init__"}))
    if conflicts:
        review.append("slot name conflicts with class body: " + ", ".join(conflicts))

    if unsafe:
        info.status = "unsafe"
        info.reasons = unsafe + review
    elif review:
        info.status = "review"
        info.reasons = review
    else:
        info.status = "safe"
    info.attrs = attrs
    info.methods = [s.name for s in node.body if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return info


def scan_tree(root: str | Path) -> list[ClassInfo]:
    root = Path(root)
    out: list[ClassInfo] = []
    for path in sorted(root.rglob("*.py")):
        if any(part in {".git", "__pycache__", ".venv", "node_modules"} for part in path.parts):
            continue
        if path.name.startswith("."):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = str(path.relative_to(root))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                out.append(classify(node, rel))
    return out