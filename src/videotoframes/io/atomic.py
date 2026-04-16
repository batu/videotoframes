"""Atomic text/bytes writes via tempfile → fsync → os.replace.

Used for the terminal manifest write and any other durable output that
must either fully land or not exist. The staging directory of the frame
PNGs is handled at the caller level (single `os.rename` of the whole
staging dir) — this helper is for single-file atomicity.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, content: str) -> None:
    """Write `content` to `path` atomically.

    Creates `path.parent` if missing. The temp file lives in the same
    directory as the target so `os.replace` is atomic on POSIX.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        # Covers KeyboardInterrupt + SystemExit too — we must not leak
        # the temp. Best-effort unlink; re-raise the original.
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise

    # fsync the parent directory so the rename durability reaches disk.
    dir_fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)
