"""`videotoframes manifest` — print an existing frames directory's
manifest to stdout. Useful for pipelines / sanity checks.
"""

from __future__ import annotations

import sys
from pathlib import Path


def run_manifest(frames_dir: Path) -> int:
    frames_dir = frames_dir.expanduser().resolve()
    manifest_path = frames_dir / "manifest.yaml"
    if not manifest_path.is_file():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 1
    sys.stdout.write(manifest_path.read_text(encoding="utf-8"))
    return 0
