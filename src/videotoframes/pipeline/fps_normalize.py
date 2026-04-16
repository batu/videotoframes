"""FPS normalization via a single ffmpeg pass.

Variable-FPS inputs (common with mobile screen-recorder captures)
confuse PySceneDetect's scene-length thresholds. Normalizing to 60fps
up front gives all downstream logic a consistent time base.
"""

from __future__ import annotations

from pathlib import Path

from videotoframes.io import subproc


def normalize(input_path: Path, output_path: Path, *, fps: int, duration_s: float) -> None:
    """Re-encode `input_path` to `fps` constant framerate at `output_path`.

    Timeout is `max(duration_s * 3, 60)` — 3x the video duration
    bounds real-world h264 veryfast encodes with substantial headroom,
    with a 60s floor for short fixtures.
    """
    timeout = max(duration_s * 3, 60)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subproc.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vf",
            f"fps={fps}",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-an",
            str(output_path),
        ],
        timeout=timeout,
    )
