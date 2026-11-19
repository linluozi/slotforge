"""Small in-repo differential: dict layout vs slotted layout, 200 distinct states."""
from __future__ import annotations

import sys
from pathlib import Path

from slotforge.rewrite import apply
from test_slotforge import SRC, load, write_mod


def states(cls, n=200):
    out = []
    for i in range(n):
        o = cls(i, i * 2)
        # The dict and slotted layouts must expose the same attribute values.
        out.append((o.a, o.b))
    return out


def test_200_distinct_states_are_identical(tmp_path):
    write_mod(tmp_path)
    mod0 = load(tmp_path / "fixture_mod.py", "diff_dict")
    before = states(mod0.Safe)
    assert len(set(before)) == 200  # deduplicated: every sample is distinct
    apply(tmp_path, ["Safe"], pickle_shim=True)
    mod1 = load(tmp_path / "fixture_mod.py", "diff_slots")
    assert states(mod1.Safe) == before
    assert not hasattr(mod1.Safe(1, 2), "__dict__")
