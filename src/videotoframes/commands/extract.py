"""`videotoframes extract` — top-level orchestration.

Flow:
    preflight → fps_normalize → detect → curate → manifest.write
                                                 → os.rename(staging → out)

CTRL-C at any point before the final rename leaves `.staging/` but no
`out/` — the consumer sees nothing partial.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _emit(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def run_extract(
    video_path: Path,
    out_dir: Path,
    *,
    fps: int,
    force: bool,
) -> int:
    """Entry point. Returns an exit code."""
    video_path = video_path.expanduser().resolve()
    out_dir = out_dir.expanduser().resolve()

    if out_dir.exists():
        if not force:
            _emit(
                f"output dir already exists: {out_dir} "
                f"(pass --force to overwrite)"
            )
            return 6
        shutil.rmtree(out_dir)

    out_parent = out_dir.parent
    out_parent.mkdir(parents=True, exist_ok=True)

    # Heavy imports are lazy — keeps `videotoframes --help` fast.
    from videotoframes.pipeline import detect as detect_mod
    from videotoframes.pipeline import fps_normalize, manifest
    from videotoframes.pipeline import preflight
    from videotoframes.pipeline.curate import curate

    stats = preflight.validate(video_path, out_parent)
    _emit(
        f"preflight ok: {stats.width}x{stats.height} "
        f"{stats.duration_s:.1f}s codec={stats.codec}"
    )

    staging = out_dir.parent / f".{out_dir.name}.staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    normalized = staging / "_normalized.mp4"
    _emit(f"normalizing to {fps}fps → {normalized.name}")
    fps_normalize.normalize(
        video_path,
        normalized,
        fps=fps,
        duration_s=stats.duration_s,
    )

    _emit("detecting scene cuts + UI-state changes (single-decode)")
    detection = detect_mod.detect(normalized)
    _emit(
        f"detected: {len(detection.scene_cut_timestamps)} scene cuts, "
        f"{len(detection.ui_change_timestamps)} UI changes, "
        f"{detection.frames_sampled} frames sampled"
    )

    _emit("curating frames")
    curated = curate(normalized, detection, staging)
    _emit(f"curated {len(curated)} frames")

    if not curated:
        _emit("error: curation produced zero frames — tune thresholds or check input")
        shutil.rmtree(staging, ignore_errors=True)
        return 1

    # Remove the normalized intermediate BEFORE the commit rename so
    # `out_dir/` only contains PNGs + manifest.yaml.
    try:
        normalized.unlink()
    except FileNotFoundError:
        pass

    manifest_path = staging / "manifest.yaml"
    manifest.write(manifest_path, manifest.frame_entries(curated))
    _emit(f"wrote manifest: {manifest_path.name}")

    # Atomic commit: rename staging → out_dir. Parent dir fsync for
    # durability.
    os.rename(staging, out_dir)
    dir_fd = os.open(out_dir.parent, os.O_DIRECTORY)
    try:
        os.fsync(dir_fd)
    finally:
        os.close(dir_fd)

    _emit(f"wrote {len(curated)} frames → {out_dir}")
    return 0
