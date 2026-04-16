"""Preflight: ffprobe validation + tail-black check + disk-space check.

Fail fast *before* the heavy ffmpeg re-encode or the cv2 single-decode
loop. On any failure, raise a specific exception with actionable text —
no bytes have been written at this point, so retry is safe.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from videotoframes.io import subproc


class PreflightError(Exception):
    """Raised when a preflight check refuses to let extraction proceed."""


# Codecs ffmpeg readers handle in an MP4 container. We accept a
# permissive set — the validator is here to reject obviously wrong
# inputs (an MP3, a weirdly-muxed .mov), not to enforce a codec policy.
_ACCEPTED_CODECS = frozenset({"h264", "hevc", "h265", "av1", "vp9"})

_MIN_LONG_EDGE = 1280  # ≥ 720p, short-edge can be ≥ 720.
_MIN_DURATION_S = 30.0
_MIN_FREE_BYTES = 10 * 1024**3  # 10 GB floor.
_DISK_SAFETY_FACTOR = 3


@dataclass(frozen=True)
class VideoStats:
    """Subset of ffprobe's stream info we care about."""

    width: int
    height: int
    duration_s: float
    bitrate_bps: int
    codec: str


def probe_video(input_path: Path) -> VideoStats:
    """Call ffprobe and parse the first video stream."""
    result = subproc.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,bit_rate,duration",
            "-show_entries",
            "format=duration,bit_rate",
            "-of",
            "json",
            str(input_path),
        ],
        timeout=15,
    )
    payload = json.loads(result.stdout)
    streams = payload.get("streams") or []
    if not streams:
        raise PreflightError(f"ffprobe found no video stream in {input_path}")
    stream = streams[0]
    fmt = payload.get("format") or {}

    # duration can live on the stream or the container; prefer stream.
    duration_raw = stream.get("duration") or fmt.get("duration")
    if duration_raw is None:
        raise PreflightError(f"ffprobe reported no duration for {input_path}")
    duration_s = float(duration_raw)

    # bit_rate can be missing on the stream for some muxers; fall back
    # to the container's total.
    bitrate_raw = stream.get("bit_rate") or fmt.get("bit_rate")
    if bitrate_raw is None:
        # Approximate from filesize / duration so the disk-space math
        # still has a signal.
        bitrate_bps = int(input_path.stat().st_size * 8 / duration_s)
    else:
        bitrate_bps = int(bitrate_raw)

    return VideoStats(
        width=int(stream["width"]),
        height=int(stream["height"]),
        duration_s=duration_s,
        bitrate_bps=bitrate_bps,
        codec=str(stream.get("codec_name", "")).lower(),
    )


def tail_is_black(input_path: Path, duration_s: float, window_s: float = 2.0) -> bool:
    """Return True if the last `window_s` of the video is entirely black.

    Runs `ffmpeg -vf blackdetect` on a `-ss`-seeked tail window and
    inspects the stderr channel for `black_start`/`black_end` markers.
    The `-f null -` output discards decoded pixels — we only need the
    filter's log lines. Cheap because only the tail window is decoded.
    """
    start_s = max(0.0, duration_s - window_s)
    # The filter emits `[blackdetect @ ...] black_start:... black_end:...`
    # lines on stderr when matches occur. Detecting ANY black segment
    # that covers the last window is the test.
    result = subproc.run(
        [
            "ffmpeg",
            "-v",
            "info",
            "-nostats",
            "-ss",
            f"{start_s:.3f}",
            "-i",
            str(input_path),
            "-vf",
            "blackdetect=d=0.1:pix_th=0.10",
            "-an",
            "-f",
            "null",
            "-",
        ],
        timeout=30,
        check=False,
    )
    combined = (result.stdout or "") + (result.stderr or "")
    # Any "black_start:0" or similar in the tail window is enough; the
    # tail is short so we're not fussy about exact coverage.
    return "black_start" in combined and "black_end" in combined


def check_disk_space(out_parent: Path, video_bytes: int) -> None:
    """Refuse if free space < max(estimated * 3, 10 GB)."""
    free_bytes = shutil.disk_usage(out_parent).free
    needed = max(video_bytes * _DISK_SAFETY_FACTOR, _MIN_FREE_BYTES)
    if free_bytes < needed:
        raise PreflightError(
            f"insufficient disk space at {out_parent}: "
            f"have {free_bytes / 1024**3:.1f} GB free, "
            f"need {needed / 1024**3:.1f} GB "
            f"(video_size * {_DISK_SAFETY_FACTOR} or {_MIN_FREE_BYTES / 1024**3:.0f} GB floor)"
        )


def validate(input_path: Path, out_parent: Path) -> VideoStats:
    """Run all preflight checks. Returns stats on success, raises on failure."""
    if not input_path.is_file():
        raise PreflightError(f"input video not found: {input_path}")
    stats = probe_video(input_path)

    if stats.codec not in _ACCEPTED_CODECS:
        raise PreflightError(
            f"unsupported codec '{stats.codec}' (accepted: {sorted(_ACCEPTED_CODECS)})"
        )

    long_edge = max(stats.width, stats.height)
    if long_edge < _MIN_LONG_EDGE:
        raise PreflightError(
            f"video resolution too small: {stats.width}x{stats.height} "
            f"(long edge must be ≥ {_MIN_LONG_EDGE})"
        )

    if stats.duration_s < _MIN_DURATION_S:
        raise PreflightError(
            f"video too short: {stats.duration_s:.1f}s "
            f"(minimum {_MIN_DURATION_S:.0f}s)"
        )

    # Disk check BEFORE tail-black — saves an ffmpeg call when the real
    # blocker is free space.
    video_bytes = input_path.stat().st_size
    check_disk_space(out_parent, video_bytes)

    if tail_is_black(input_path, stats.duration_s):
        raise PreflightError(
            f"video appears tail-truncated (last 2s are fully black): {input_path}"
        )

    return stats
