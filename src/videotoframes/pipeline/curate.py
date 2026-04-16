"""Curation: union scene cuts + UI changes, dedupe by time window and
by dHash distance, write one PNG per curated timestamp.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2  # type: ignore[import-untyped]
import imagehash  # type: ignore[import-untyped]
from PIL import Image

from videotoframes.pipeline.detect import (
    DEDUPE_HAMMING,
    DHASH_SIZE,
    DetectionResult,
)


# Neighborhood for time-window dedupe (scene cut + UI change merge).
# Originally 0.5s per the card description; tightened to 0.2s after the
# find_the_dog validation showed sub-second transients (wrong-tap red-X,
# hint-tooltip flash) being swallowed by adjacent scene cuts. 0.2s is
# still comfortably above per-frame sampling granularity (~0.17s at
# 6fps) so we aren't paying spurious cost, and it keeps transient UI
# feedback states that only linger for 300-500ms.
NEIGHBORHOOD_S = 0.2


@dataclass(frozen=True)
class CuratedFrame:
    index: int  # 1-based, zero-padded filename id.
    timestamp_s: float
    scene_id: int
    dhash: imagehash.ImageHash


def _union_and_neighborhood_dedupe(
    scene_cuts: list[float],
    ui_changes: list[float],
) -> list[tuple[float, bool]]:
    """Merge timestamps, drop any within NEIGHBORHOOD_S of a prior kept.

    Returns list of `(timestamp_s, is_scene_cut)` tuples sorted
    ascending. When a scene cut and a UI change collide inside the
    neighborhood, we prefer the scene cut (stronger signal).
    """
    # Always include t=0 as the opening frame so the B&W / pre-tap
    # state is captured.
    events: list[tuple[float, bool]] = [(0.0, True)]
    events.extend((t, True) for t in scene_cuts)
    events.extend((t, False) for t in ui_changes)
    # Stable sort: scene cuts first within a tie.
    events.sort(key=lambda e: (e[0], not e[1]))

    kept: list[tuple[float, bool]] = []
    for ts, is_cut in events:
        if kept and (ts - kept[-1][0]) < NEIGHBORHOOD_S:
            # Upgrade the last-kept to scene-cut if this stronger event
            # falls in the neighborhood.
            if is_cut and not kept[-1][1]:
                kept[-1] = (kept[-1][0], True)
            continue
        kept.append((ts, is_cut))
    return kept


def _seek_and_capture(cap: cv2.VideoCapture, timestamp_s: float):
    """Seek to `timestamp_s` and return the BGR frame, or None on EOF."""
    cap.set(cv2.CAP_PROP_POS_MSEC, timestamp_s * 1000.0)
    ok, frame = cap.read()
    if not ok:
        return None
    return frame


def curate(
    normalized_video: Path,
    detection: DetectionResult,
    staging_dir: Path,
) -> list[CuratedFrame]:
    """Pick, dedupe, and write curated frames.

    Writes `frame_NNNN.png` files to `staging_dir` and returns the
    CuratedFrame list matching the files on disk.
    """
    staging_dir.mkdir(parents=True, exist_ok=True)
    events = _union_and_neighborhood_dedupe(
        detection.scene_cut_timestamps,
        detection.ui_change_timestamps,
    )

    cap = cv2.VideoCapture(str(normalized_video))
    if not cap.isOpened():
        raise RuntimeError(f"cv2 could not open {normalized_video}")

    curated: list[CuratedFrame] = []
    scene_id = 0
    kept_hashes: list[imagehash.ImageHash] = []
    try:
        for ts, is_cut in events:
            if is_cut and curated:
                scene_id += 1

            frame_bgr = _seek_and_capture(cap, ts)
            if frame_bgr is None:
                # End of stream; seeking past the last frame is benign.
                continue

            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            pil = Image.fromarray(rgb)
            h = imagehash.dhash(pil, hash_size=DHASH_SIZE)

            # Dedupe against previously kept frames by dHash distance.
            if any((h - prior) < DEDUPE_HAMMING for prior in kept_hashes):
                continue

            index = len(curated) + 1
            out_path = staging_dir / f"frame_{index:04d}.png"
            cv2.imwrite(str(out_path), frame_bgr, [cv2.IMWRITE_PNG_COMPRESSION, 6])
            kept_hashes.append(h)
            curated.append(
                CuratedFrame(
                    index=index,
                    timestamp_s=ts,
                    scene_id=scene_id,
                    dhash=h,
                )
            )
    finally:
        cap.release()

    return curated
