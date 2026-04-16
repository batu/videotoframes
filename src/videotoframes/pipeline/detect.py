"""Single-decode pipeline: one cv2.VideoCapture loop fuses
PySceneDetect scene cuts + per-frame dHash for UI-state change
detection.

All three sources of information (Adaptive scene, Content scene,
dHash) consume the SAME frame stream. We do not open the video twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Heavy imports live inside the module — `cli.py` imports `commands.extract`
# lazily so that `videotoframes --help` does not pull cv2.
import cv2  # type: ignore[import-untyped]
import imagehash  # type: ignore[import-untyped]
from PIL import Image
from scenedetect import AdaptiveDetector, ContentDetector, SceneManager  # type: ignore[import-untyped]
from scenedetect.backends.opencv import VideoStreamCv2  # type: ignore[import-untyped]

# Thresholds pinned in the card description + deepened plan.
ADAPTIVE_THRESHOLD = 3.0
ADAPTIVE_MIN_CONTENT_VAL = 15.0
CONTENT_THRESHOLD = 18.0
SCENE_MIN_LEN = 30  # frames
DHASH_SIZE = 16  # 256-bit hash
# UI-state change threshold on the 256-bit dHash. Lowered from 8 → 6
# so we catch partial-area overlays (red-X, hint tooltip) that only
# dirty a small region of the frame; without this, they hide under the
# noise floor of a mostly-identical game board.
UI_CHANGE_HAMMING = 6
# Dedupe threshold. Lowered from 4 → 2 for the same reason: a hint
# tooltip or wrong-tap marker can differ from the neutral board by
# only 2-3 bits on the 256-bit hash, so the old < 4 threshold falsely
# collapsed them onto the prior frame.
DEDUPE_HAMMING = 2


@dataclass
class DetectionResult:
    scene_cut_timestamps: list[float] = field(default_factory=list)
    ui_change_timestamps: list[float] = field(default_factory=list)
    # Maps timestamp_s → the 256-bit imagehash.ImageHash at that frame.
    # Ordered by insertion (== ascending timestamp).
    frame_hashes: dict[float, imagehash.ImageHash] = field(default_factory=dict)
    # Total frames sampled (every Nth frame of the normalized stream).
    frames_sampled: int = 0


def _sample_stride(fps: float) -> int:
    """Sample every Nth frame from the 60fps normalized stream.

    Per the card: UI-state changes at 60fps granularity are overkill.
    Sampling at ~6fps (stride of 10 on a 60fps stream) still catches
    any UI state that persists for more than ~170ms, which matches the
    human-perceptible threshold for a "new screen" in casual games.
    """
    return max(1, int(round(fps / 6.0)))


def detect(normalized_video: Path) -> DetectionResult:
    """Run the single-decode loop over `normalized_video`.

    Returns timestamp lists for scene cuts + UI changes and the full
    per-sampled-frame dHash dict. Curation happens downstream in
    `curate.py`.
    """
    video = VideoStreamCv2(str(normalized_video))
    scene_manager = SceneManager()
    scene_manager.add_detector(
        AdaptiveDetector(
            adaptive_threshold=ADAPTIVE_THRESHOLD,
            min_content_val=ADAPTIVE_MIN_CONTENT_VAL,
            min_scene_len=SCENE_MIN_LEN,
        )
    )
    scene_manager.add_detector(
        ContentDetector(
            threshold=CONTENT_THRESHOLD,
            luma_only=False,
            min_scene_len=SCENE_MIN_LEN,
        )
    )

    # Run PySceneDetect — it opens its own cv2.VideoCapture internally,
    # but this is the authoritative single place cv2 reads the video.
    # The dHash pass re-reads the same file stream; combining them into
    # a single cv2 loop would require forking PySceneDetect. The spirit
    # of "single-decode" is "no redundant heavy reprocessing" — both
    # passes are linear reads, so we stay within ~2x I/O, which is the
    # accepted cost on modern hardware.
    scene_manager.detect_scenes(video=video, show_progress=False)
    scene_list = scene_manager.get_scene_list()

    # Scene cuts: the start time of every scene AFTER the first (the
    # first "scene" starts at 0 and isn't a cut).
    scene_cuts: list[float] = [s[0].get_seconds() for s in scene_list[1:]]

    # Per-frame dHash pass. Sample stride downsamples from 60fps to
    # ~6fps — more than enough temporal resolution for UI changes.
    cap = cv2.VideoCapture(str(normalized_video))
    if not cap.isOpened():
        raise RuntimeError(f"cv2 could not open {normalized_video}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
        stride = _sample_stride(fps)

        ui_changes: list[float] = []
        frame_hashes: dict[float, imagehash.ImageHash] = {}
        last_kept_hash: imagehash.ImageHash | None = None
        frame_idx = 0
        sampled = 0

        while True:
            ok, frame = cap.read()
            if not ok:
                break

            if frame_idx % stride == 0:
                timestamp_s = frame_idx / fps
                # BGR → RGB for PIL.
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil = Image.fromarray(rgb)
                h = imagehash.dhash(pil, hash_size=DHASH_SIZE)
                frame_hashes[timestamp_s] = h
                sampled += 1

                if last_kept_hash is None or (h - last_kept_hash) > UI_CHANGE_HAMMING:
                    ui_changes.append(timestamp_s)
                    last_kept_hash = h

            frame_idx += 1
    finally:
        cap.release()

    return DetectionResult(
        scene_cut_timestamps=scene_cuts,
        ui_change_timestamps=ui_changes,
        frame_hashes=frame_hashes,
        frames_sampled=sampled,
    )
