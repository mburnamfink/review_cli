"""Tests for the pick-covers state store (Slice 4)."""
from __future__ import annotations

from review.pickstate import DONE, NEEDS_MANUAL, SKIPPED, PickState


def test_load_missing_file_is_empty(tmp_path):
    state = PickState.load(tmp_path / "covers" / ".pick_state.json")
    assert state.books == {}
    assert state.status("anything") is None
    assert not state.is_done("anything")


def test_record_persists_and_roundtrips(tmp_path):
    p = tmp_path / ".pick_state.json"
    state = PickState.load(p)
    state.record("dune-herbert", DONE, chosen=2, hashes=[1, 2, 3])

    assert p.exists()  # saved immediately
    reloaded = PickState.load(p)
    assert reloaded.status("dune-herbert") == DONE
    assert reloaded.is_done("dune-herbert")
    assert reloaded.books["dune-herbert"]["chosen"] == 2
    assert reloaded.books["dune-herbert"]["hashes"] == [1, 2, 3]


def test_is_done_only_for_done_status(tmp_path):
    state = PickState.load(tmp_path / "s.json")
    state.record("a", SKIPPED)
    state.record("b", NEEDS_MANUAL)
    state.record("c", DONE)
    assert not state.is_done("a")
    assert not state.is_done("b")
    assert state.is_done("c")


def test_needs_manual_lists_rejected_sorted(tmp_path):
    state = PickState.load(tmp_path / "s.json")
    state.record("zeta", NEEDS_MANUAL)
    state.record("alpha", NEEDS_MANUAL)
    state.record("beta", SKIPPED)
    state.record("gamma", DONE)
    assert state.needs_manual() == ["alpha", "zeta"]


def test_record_updates_status_in_place(tmp_path):
    state = PickState.load(tmp_path / "s.json")
    state.record("x", SKIPPED, hashes=[9])
    state.record("x", DONE, chosen=1)
    assert state.status("x") == DONE
    assert state.books["x"]["chosen"] == 1
    assert state.books["x"]["hashes"] == [9]  # preserved across update


def test_corrupt_file_loads_as_empty(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{not valid json", encoding="utf-8")
    state = PickState.load(p)
    assert state.books == {}
