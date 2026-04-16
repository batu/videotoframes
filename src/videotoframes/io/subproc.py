"""Single subprocess boundary — the test seam.

Production path calls `subprocess.run` directly; there is no runtime
indirection cost. Tests monkeypatch `videotoframes.io.subproc.run` to a
fake in the `fake_subprocess_runner` fixture so unit tests never invoke
real ffmpeg or cv2.
"""

from __future__ import annotations

import subprocess
from collections.abc import Sequence


def run(
    cmd: Sequence[str],
    *,
    timeout: float,
    check: bool = True,
    capture_output: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """Thin wrapper around `subprocess.run` with mandatory timeout.

    `check=True` is the default and intentional — per utolye root AGENTS.md,
    subprocess failures propagate via `CalledProcessError`. Callers that
    want to inspect a non-zero exit pass `check=False` explicitly.
    """
    return subprocess.run(
        list(cmd),
        timeout=timeout,
        check=check,
        capture_output=capture_output,
        text=text,
    )
