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
    """Importing the CLI module + building the parser must NOT pull cv2 /
    scenedetect / imagehash / PIL into sys.modules — those live behind
    the lazy subcommand import boundary so `--help` stays fast.
    """
    # Build the parser in a subprocess and report which heavy modules
    # ended up imported. A direct `--help` run would sys.exit(0) before
    # we could read sys.modules, hence the explicit `_build_parser()`.
    probe = (
        "import sys; "
        "import videotoframes.cli as c; "
        "c._build_parser(); "
        "heavy = [m for m in ('cv2','scenedetect','imagehash','PIL') if m in sys.modules]; "
        "print(','.join(heavy))"
    )
    out = subprocess.check_output(
        [sys.executable, "-c", probe],
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
