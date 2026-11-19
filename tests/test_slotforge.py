from __future__ import annotations

import importlib.util
import json
import pickle
import sys
import textwrap
from pathlib import Path

from slotforge import cli
from slotforge.measure import own_bytes
from slotforge.rewrite import apply, plan, rollback, unified_diff
from slotforge.scanner import scan_tree

SRC = textwrap.dedent(
    """
    class Safe:
        def __init__(self, a, b):
            self.a = a
            self.b = b

    class Unsafe:
        def __init__(self):
            self.a = 0

        def bump(self):
            self.b = 2

    class Review:
        def method(self):
            return 1

    class Already:
        __slots__ = ("a",)

        def __init__(self):
            self.a = 1

    class Weak:
        def __init__(self):
            self.a = 1

        def ref(self):
            return self.__weakref__

    class Conflict:
        a = 0

        def __init__(self):
            self.a = 1

    class Hooked:
        def __init__(self):
            self.a = 1

        def __getattr__(self, name):
            raise AttributeError(name)
    """
)


def write_mod(tmp: Path, name: str = "fixture_mod.py", src: str = SRC) -> Path:
    p = tmp / name
    p.write_text(src)
    return p


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_classifier_statuses(tmp_path):
    write_mod(tmp_path)
    by_name = {i.name: i for i in scan_tree(tmp_path)}
    assert by_name["Safe"].status == "safe"
    assert by_name["Safe"].attrs == ["a", "b"]
    assert by_name["Unsafe"].status == "unsafe"
    assert by_name["Review"].status == "review"
    assert by_name["Already"].status == "already-slotted"
    assert by_name["Weak"].status == "unsafe"
    assert by_name["Conflict"].status == "review"
    assert by_name["Hooked"].status == "unsafe"


def test_patch_and_rollback_byte_identical(tmp_path):
    path = write_mod(tmp_path)
    before = path.read_bytes()
    res = apply(tmp_path, ["Safe"], pickle_shim=True)
    assert res["count"] == 1
    after = path.read_text()
    assert "__slots__ = ('a', 'b',)" in after
    assert "def __getstate__(self):" in after
    rb = rollback(tmp_path)
    assert rb["count"] == 1
    assert path.read_bytes() == before


def test_only_selected_classes_are_patched(tmp_path):
    write_mod(tmp_path)
    apply(tmp_path, ["Safe"])
    text = (tmp_path / "fixture_mod.py").read_text()
    assert text.count("__slots__") == 2  # the new one plus class Already's


def test_unified_diff_is_minimal_and_appliable(tmp_path):
    path = write_mod(tmp_path)
    patch = unified_diff(tmp_path, ["Safe"], pickle_shim=False)
    assert "+    __slots__ = ('a', 'b',)" in patch
    assert "--- a/fixture_mod.py" in patch
    assert path.read_bytes()  # untouched
    # A patch with no removal lines must apply cleanly to the original.
    assert not any(line.startswith("-") and not line.startswith("---") for line in patch.splitlines())


def test_slots_make_instances_smaller(tmp_path):
    write_mod(tmp_path)
    mod0 = load(tmp_path / "fixture_mod.py", "fixture_dict")
    d = own_bytes(lambda: mod0.Safe(1, 2), 500)
    apply(tmp_path, ["Safe"])
    mod1 = load(tmp_path / "fixture_mod.py", "fixture_slots")
    s = own_bytes(lambda: mod1.Safe(1, 2), 500)
    assert d["bytes_per_instance"] > s["bytes_per_instance"]
    assert not hasattr(mod1.Safe(1, 2), "__dict__")


def test_pickle_shim_round_trips_and_accepts_old_dict_state(tmp_path):
    write_mod(tmp_path)
    mod0 = load(tmp_path / "fixture_mod.py", "fixture_pickle_dict")
    old_blob = pickle.dumps(mod0.Safe(1, 2))
    del sys.modules["fixture_pickle_dict"]
    apply(tmp_path, ["Safe"], pickle_shim=True)
    mod1 = load(tmp_path / "fixture_mod.py", "fixture_pickle_dict")
    obj = mod1.Safe(3, 4)
    restored = pickle.loads(pickle.dumps(obj))
    assert (restored.a, restored.b) == (3, 4)
    # A pickle written by the old dict layout loads into the slotted layout.
    legacy = pickle.loads(old_blob)
    assert (legacy.a, legacy.b) == (1, 2)


def test_pickle_shim_is_not_duplicated(tmp_path):
    src = textwrap.dedent("""
    class HasShim:
        __slots__ = ("a",)
        def __init__(self):
            self.a = 1
        def __getstate__(self):
            return {"a": self.a}
        def __setstate__(self, state):
            self.a = state["a"]
    """)
    write_mod(tmp_path, "shim.py", src)
    infos = {i.name: i for i in scan_tree(tmp_path)}
    assert "HasShim" in infos
    patch = unified_diff(tmp_path, ["HasShim"], pickle_shim=True)
    assert patch == ""  # already slotted, so nothing is planned


def test_cli_scan_json(tmp_path):
    write_mod(tmp_path)
    out = tmp_path / "scan.json"
    rc = cli.main(["scan", str(tmp_path), "--json", str(out)])
    assert rc == 0
    data = json.loads(out.read_text())
    assert data["counts"]["safe"] == 1
    assert data["counts"]["unsafe"] == 3
