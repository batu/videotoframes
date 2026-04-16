"""Atomic text writes and staging-dir rename semantics."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from videotoframes.io.atomic import atomic_write_text


pytestmark = pytest.mark.unit


def test_atomic_write_happy(tmp_path: Path):
    target = tmp_path / "out" / "file.txt"
    atomic_write_text(target, "hello world")
    assert target.read_text() == "hello world"
    # No leftover tempfiles.
    siblings = list(target.parent.iterdir())
    assert siblings == [target], f"unexpected siblings: {siblings}"


def test_atomic_write_overwrite(tmp_path: Path):
    target = tmp_path / "file.txt"
    target.write_text("old")
    atomic_write_text(target, "new")
    assert target.read_text() == "new"


def test_atomic_write_cleans_up_on_error(tmp_path: Path, monkeypatch):
    """If os.replace raises, the temp file must be cleaned up."""
    target = tmp_path / "file.txt"

    real_replace = os.replace

    def boom(src, dst):
        # Confirm the temp exists at the point of boom.
        assert Path(src).exists()
        raise RuntimeError("simulated failure")

    monkeypatch.setattr("videotoframes.io.atomic.os.replace", boom)
    with pytest.raises(RuntimeError, match="simulated"):
        atomic_write_text(target, "x")

    # Target should NOT exist, no stray temps either.
    assert not target.exists()
    leftover = [p for p in tmp_path.iterdir() if p.name.startswith(".")]
    assert leftover == [], f"leftover temps: {leftover}"

    # Restore and confirm a follow-up write works.
    monkeypatch.setattr("videotoframes.io.atomic.os.replace", real_replace)
    atomic_write_text(target, "ok")
    assert target.read_text() == "ok"
