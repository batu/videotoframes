"""CLI surface: argument parsing, cold-start import discipline."""

from __future__ import annotations

import subprocess
import sys
import time

import pytest


pytestmark = pytest.mark.unit


def test_help_exits_zero():
    """`videotoframes --help` returns 0 (argparse convention)."""
    rc = subprocess.call(
        [sys.executable, "-m", "videotoframes.cli", "--help"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert rc == 0


def test_help_is_fast():
    """Cold-start help ≤ 500ms (relaxed from 200ms for CI)."""
    start = time.perf_counter()
    subprocess.check_call(
        [sys.executable, "-m", "videotoframes.cli", "--help"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    assert elapsed_ms < 500, f"--help took {elapsed_ms:.0f}ms, budget is 500ms"


def test_help_does_not_import_cv2():
    """Running --help must NOT import cv2 / scenedetect (lazy imports)."""
    # Run a subprocess that imports cli, parses --help, then reports
    # which heavy modules got imported. We use sys.exit before argparse
    # aborts so we can read sys.modules.
    probe = (
        "import sys; "
        "import videotoframes.cli as c; "
        "p = c._build_parser(); p.parse_known_args(['--help']); "
    )
    # argparse --help calls sys.exit(0) — instead of --help, we invoke
    # a partial probe that builds the parser but doesn't parse. Then
    # dump sys.modules.
    probe2 = (
        "import sys; "
        "import videotoframes.cli as c; "
        "c._build_parser(); "
        "heavy = [m for m in ('cv2','scenedetect','imagehash','PIL') if m in sys.modules]; "
        "print(','.join(heavy))"
    )
    _ = probe  # kept for context
    out = subprocess.check_output(
        [sys.executable, "-c", probe2],
        text=True,
    ).strip()
    assert out == "", f"cli module pulled heavy imports: {out!r}"


def test_extract_missing_video_argparse_error():
    """No `video` positional → argparse exit 2."""
    rc = subprocess.call(
        [sys.executable, "-m", "videotoframes.cli", "extract", "--out", "/tmp/x"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert rc == 2
