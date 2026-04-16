"""Preflight checks — all failure modes via the fake subprocess runner.

Never invokes real ffmpeg/ffprobe.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from videotoframes.pipeline import preflight


pytestmark = pytest.mark.unit


def _register_probe(runner, *, width: int, height: int, duration: float, bitrate: int, codec: str):
    payload = json.dumps(
        {
            "streams": [
                {
                    "codec_name": codec,
                    "width": width,
                    "height": height,
                    "duration": str(duration),
                    "bit_rate": str(bitrate),
                }
            ],
            "format": {"duration": str(duration), "bit_rate": str(bitrate)},
        }
    )
    runner.register(lambda argv: argv[0] == "ffprobe", stdout=payload)


def _register_tail_black(runner, *, black: bool):
    # ffmpeg path for tail-black probe; stderr is what our code inspects.
    stderr = (
        "[blackdetect @ 0xabc] black_start:0.1 black_end:0.2 black_duration:0.1"
        if black
        else ""
    )
    runner.register(
        lambda argv: argv[0] == "ffmpeg" and "blackdetect" in " ".join(argv),
        stderr=stderr,
    )


def _fake_video(tmp_path: Path, *, size_bytes: int = 10 * 1024 * 1024) -> Path:
    p = tmp_path / "video.mp4"
    p.write_bytes(b"\x00" * size_bytes)
    return p


def test_happy_path(tmp_path, fake_subprocess_runner):
    video = _fake_video(tmp_path)
    _register_probe(
        fake_subprocess_runner,
        width=1920,
        height=1080,
        duration=60.0,
        bitrate=5_000_000,
        codec="h264",
    )
    _register_tail_black(fake_subprocess_runner, black=False)
    stats = preflight.validate(video, tmp_path)
    assert stats.width == 1920 and stats.height == 1080
    assert stats.duration_s == pytest.approx(60.0)
    assert stats.codec == "h264"


def test_rejects_unsupported_codec(tmp_path, fake_subprocess_runner):
    video = _fake_video(tmp_path)
    _register_probe(
        fake_subprocess_runner,
        width=1920,
        height=1080,
        duration=60.0,
        bitrate=5_000_000,
        codec="mjpeg",
    )
    with pytest.raises(preflight.PreflightError, match="unsupported codec"):
        preflight.validate(video, tmp_path)


def test_rejects_too_small(tmp_path, fake_subprocess_runner):
    video = _fake_video(tmp_path)
    _register_probe(
        fake_subprocess_runner,
        width=640,
        height=480,
        duration=60.0,
        bitrate=500_000,
        codec="h264",
    )
    with pytest.raises(preflight.PreflightError, match="resolution too small"):
        preflight.validate(video, tmp_path)


def test_rejects_too_short(tmp_path, fake_subprocess_runner):
    video = _fake_video(tmp_path)
    _register_probe(
        fake_subprocess_runner,
        width=1920,
        height=1080,
        duration=10.0,
        bitrate=5_000_000,
        codec="h264",
    )
    with pytest.raises(preflight.PreflightError, match="too short"):
        preflight.validate(video, tmp_path)


def test_rejects_tail_black(tmp_path, fake_subprocess_runner):
    video = _fake_video(tmp_path)
    _register_probe(
        fake_subprocess_runner,
        width=1920,
        height=1080,
        duration=60.0,
        bitrate=5_000_000,
        codec="h264",
    )
    _register_tail_black(fake_subprocess_runner, black=True)
    with pytest.raises(preflight.PreflightError, match="tail-truncated"):
        preflight.validate(video, tmp_path)


def test_disk_preflight_refuses_before_write(tmp_path, fake_subprocess_runner, monkeypatch):
    """shutil.disk_usage is swapped in so the preflight sees <10 GB free."""
    import shutil as _shutil

    _real_disk_usage = _shutil.disk_usage
    _du = type("_DU", (), {"total": 0, "used": 0, "free": 1_000_000})()
    monkeypatch.setattr(
        "videotoframes.pipeline.preflight.shutil.disk_usage",
        lambda p: _du,
    )

    video = _fake_video(tmp_path)
    _register_probe(
        fake_subprocess_runner,
        width=1920,
        height=1080,
        duration=60.0,
        bitrate=5_000_000,
        codec="h264",
    )
    with pytest.raises(preflight.PreflightError, match="insufficient disk space"):
        preflight.validate(video, tmp_path)

    # We never reached tail-black — that's the whole point of fail-fast.
    argvs = [" ".join(c) for c in fake_subprocess_runner.calls]
    assert not any("blackdetect" in a for a in argvs), (
        "disk preflight should refuse BEFORE the ffmpeg blackdetect call"
    )
    # Keep the real one referenced so linters don't complain.
    _ = _real_disk_usage


def test_missing_video_file(tmp_path, fake_subprocess_runner):
    missing = tmp_path / "nope.mp4"
    with pytest.raises(preflight.PreflightError, match="not found"):
        preflight.validate(missing, tmp_path)
