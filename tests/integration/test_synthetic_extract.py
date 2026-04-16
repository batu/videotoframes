"""End-to-end extract on a synthetic fixture built via `ffmpeg -f lavfi`.

Per the card's acceptance criterion:

> On a synthetic 30s fixture video (generated via `ffmpeg -f lavfi` with
> color scenes + text overlays), produces 5-15 curated frames + a
> schema-valid `manifest.yaml`.

This runs the real ffmpeg + cv2 + scenedetect stack; it is gated behind
`@pytest.mark.integration` so the default unit-only run stays fast and
doesn't need ffmpeg installed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.integration


# Six color + text-overlay scenes, 5s each = 30s total. Concatenated via
# `-filter_complex concat` because `-f lavfi` accepts one input at a
# time. Solid-color frames give a zero dHash (no gradients), which
# collapses under the 256-bit DEDUPE_HAMMING=2 threshold — so every
# scene carries a large centered text label to guarantee a distinctive
# gradient signature. PySceneDetect's ContentDetector at threshold=18
# picks up every color transition; the text makes each scene's dHash
# hamming-different from its neighbours. Expected curated count: the
# opening frame + 5 scene cuts = 6 frames, comfortably inside the 5-15
# band the card's acceptance criterion asks for.
_LAVFI_COLORS = ("red", "green", "blue", "yellow", "magenta", "cyan")
_SCENE_DURATION_S = 5


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _has_drawtext_support() -> bool:
    """True if ffmpeg was built with --enable-libfreetype (drawtext filter)."""
    probe = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"],
        capture_output=True,
        text=True,
        check=False,
    )
    return "drawtext" in probe.stdout


def _build_lavfi_args(out_path: Path) -> list[str]:
    """Build the ffmpeg argv for the synthetic concat fixture."""
    argv: list[str] = ["ffmpeg", "-y", "-v", "error"]
    for color in _LAVFI_COLORS:
        argv += [
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=1280x720:d={_SCENE_DURATION_S}",
        ]
    # Per-scene drawtext label, then concat. Each scene gets its color
    # name rendered in the middle so the dHash gradient fingerprints
    # differ across scenes even though the backgrounds are solid.
    per_scene_filters = ";".join(
        (
            f"[{i}]drawtext=text='{color.upper()}':"
            f"fontsize=200:fontcolor=black:x=(w-text_w)/2:y=(h-text_h)/2[v{i}]"
        )
        for i, color in enumerate(_LAVFI_COLORS)
    )
    concat_inputs = "".join(f"[v{i}]" for i in range(len(_LAVFI_COLORS)))
    filter_complex = (
        f"{per_scene_filters};{concat_inputs}concat=n={len(_LAVFI_COLORS)}:v=1:a=0[out]"
    )
    argv += [
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-an",
        str(out_path),
    ]
    return argv


@pytest.fixture(scope="module")
def synthetic_video(tmp_path_factory) -> Path:
    """Build a 30s 1280x720 h264 mp4 with 6 color+text scenes."""
    if not _ffmpeg_available():
        pytest.skip("ffmpeg/ffprobe not on PATH")
    if not _has_drawtext_support():
        pytest.skip("this ffmpeg was built without libfreetype (no drawtext filter)")
    out = tmp_path_factory.mktemp("lavfi") / "synthetic.mp4"
    subprocess.check_call(_build_lavfi_args(out), stderr=subprocess.STDOUT)
    assert out.is_file() and out.stat().st_size > 0
    return out


def test_extract_produces_curated_frames(synthetic_video: Path, tmp_path: Path):
    """5-15 curated frames + schema-valid manifest from a 6-scene fixture."""
    out_dir = tmp_path / "frames"
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "videotoframes.cli",
            "extract",
            str(synthetic_video),
            "--out",
            str(out_dir),
        ],
        stdout=sys.stderr,
        stderr=sys.stderr,
    )
    pngs = sorted(out_dir.glob("frame_*.png"))
    manifest = out_dir / "manifest.yaml"

    # Count band from the card's acceptance criterion.
    assert 5 <= len(pngs) <= 15, (
        f"expected 5-15 curated frames on the synthetic 6-scene fixture, got {len(pngs)}"
    )
    assert manifest.is_file(), "manifest.yaml must exist next to the frames"

    # Round-trip parse — the manifest module owns schema validation.
    from videotoframes.pipeline.manifest import read

    entries = read(manifest)
    assert len(entries) == len(pngs)
    # Paths must match the files on disk.
    assert [e.path for e in entries] == [p.name for p in pngs]
    # Timestamps ascend and are all within the 30s duration (with a small
    # slack — ffmpeg's exact end can be a frame off from a round number).
    timestamps = [e.timestamp_s for e in entries]
    assert timestamps == sorted(timestamps), "timestamps must ascend"
    assert all(0.0 <= t < 30.5 for t in timestamps), f"out-of-range: {timestamps}"


def test_force_flag_overwrites(synthetic_video: Path, tmp_path: Path):
    """Second `extract` with `--force` replaces the first run's output."""
    out_dir = tmp_path / "frames"
    # First run — succeeds cleanly.
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "videotoframes.cli",
            "extract",
            str(synthetic_video),
            "--out",
            str(out_dir),
        ],
        stdout=sys.stderr,
        stderr=sys.stderr,
    )
    first_count = len(list(out_dir.glob("frame_*.png")))
    assert first_count > 0

    # Second run without --force must refuse (exit 6).
    rc = subprocess.call(
        [
            sys.executable,
            "-m",
            "videotoframes.cli",
            "extract",
            str(synthetic_video),
            "--out",
            str(out_dir),
        ],
        stdout=sys.stderr,
        stderr=sys.stderr,
    )
    assert rc == 6, f"expected exit 6 on clobber-without-force, got {rc}"

    # Third run WITH --force must succeed.
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "videotoframes.cli",
            "extract",
            str(synthetic_video),
            "--out",
            str(out_dir),
            "--force",
        ],
        stdout=sys.stderr,
        stderr=sys.stderr,
    )
    assert (out_dir / "manifest.yaml").is_file()
