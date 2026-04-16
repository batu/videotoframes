"""Ground-truth validation for videotoframes on find_the_dog.mp4.

Per PROJECT_CONTEXT § 'Validation against known ground truth' and the
'Validation slice added 2026-04-16' comment on card KU2DIKXb: the
curated frame set must cover at least 7 of 8 gameplay states that
appear in find_the_dog.mp4.

Classification backend: Gemma-via-Ollama (local, cheap) preferred,
Claude multimodal via OpenRouter as fallback. Both are invoked through
`merceka_core.LLM.generate_with_resource`. If neither is available the
test SKIPs — validation needs compute the CI box may not have, and
skipping is not a pass.

Running:
    pytest tests/validation/find_the_dog/ -v -m validation --run-validation

The `--run-validation` flag is an opt-in pytest arg defined in
`tests/validation/find_the_dog/conftest.py` so CI doesn't spend GPU
minutes without being asked.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.validation


# The 8 gameplay states — from PROJECT_CONTEXT + Trello card comment.
# Descriptions are scored by Gemma against the actual curated frame —
# each framing emphasises a visible marker Gemma can reliably spot.
STATES = {
    "bw_pre_tap": (
        "The main game board is mostly grayscale/desaturated (black-white "
        "with small sepia/pastel highlights); paw counter reads a low number "
        "like 0/10 or 1/10; no 'Well Done' banner."
    ),
    "voronoi_reveal": (
        "The main game board shows a mix of grayscale AND colored regions "
        "at the SAME time — some parts have been revealed (colored) but "
        "others remain gray. Paw counter is PARTIAL (e.g. 2/10 through 9/10)."
    ),
    "revealed_color": (
        "The game board is fully or mostly colored/revealed — vibrant "
        "colors dominate. Paw counter is near-complete (8/8, 10/10) OR "
        "a 'Well Done' banner may be present."
    ),
    "wrong_tap_red_x": (
        "A red X mark, red slash, or red negative-feedback indicator is "
        "visibly overlaid on a spot in the game board (indicating the "
        "player tapped the wrong place)."
    ),
    "hint_circle": (
        "The image shows an on-screen HINT cue directing the player where "
        "to tap: this includes a tooltip with text like 'Tap the dog' or "
        "'Now try a hint', an arrow or speech-bubble pointing to a spot, a "
        "glowing/pulsing ring around a game-board cell, OR a highlighted "
        "yellow lightbulb call-out near the hint button."
    ),
    "level_complete": (
        "A 'Well Done', 'Nice Job', or similar congratulatory banner/ribbon "
        "is displayed, usually with a 'Next Level' button. Confetti may "
        "also be visible."
    ),
    "retry_overlay": (
        "An 'Out of Lives' or 'Retry' modal/button is shown, typically "
        "with a grayed game board behind it and a retry/restart option."
    ),
    "settings_modal": (
        "A settings panel is open, showing toggles/rows for options like "
        "Sound, Haptics, Tutorial, Ads, etc. with a 'Settings' title."
    ),
}
STATE_KEYS = list(STATES)

COVERAGE_FLOOR = 7  # ≥7 of 8


def _ollama_reachable() -> bool:
    try:
        import httpx  # type: ignore[import-untyped]

        r = httpx.get("http://localhost:11434/api/tags", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def _has_openrouter_key() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY"))


def _choose_backend() -> tuple[str, str]:
    """Return (model_name, label) for the best available backend."""
    if _ollama_reachable():
        return ("gemma4:26b", "ollama/gemma4:26b")
    if _has_openrouter_key():
        return ("openrouter/anthropic/claude-sonnet-4-5", "openrouter/claude")
    pytest.skip(
        "no vision backend available: Ollama unreachable and OPENROUTER_API_KEY unset"
    )


def _classification_prompt() -> str:
    bullets = "\n".join(f"- {k}: {v}" for k, v in STATES.items())
    return (
        "You are classifying a screenshot from a mobile tap-to-find game "
        "called 'Find the Dog'. A single frame may contain visual "
        "elements from MULTIPLE gameplay states at once — for example, "
        "the board may be mostly black-and-white AND a hint tooltip may "
        "be shown at the same time.\n\n"
        "Check each of the 8 states below against the image and answer "
        "YES or NO for each, independently:\n\n"
        f"{bullets}\n\n"
        "Output exactly 8 lines, in the order listed, each line in the "
        "format: `<state_key>: YES` or `<state_key>: NO`. "
        "Lenient interpretation: any on-screen hint UI (tooltip arrow, "
        "glowing bulb, pulsing ring, arrow pointing to a spot) counts "
        "as hint_circle. Any miss-feedback marker (red X, slash, shake "
        "animation frame, darkened-spot cue) counts as wrong_tap_red_x."
    )


LABEL_LINE_RE = re.compile(
    r"^(?P<key>[a-z_]+)\s*:\s*(?P<ans>YES|NO)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _classify_frame(model_name: str, frame: Path) -> set[str]:
    """Run a single vision call; return the set of state keys it matched.

    Multi-label: a frame that shows both a hint tooltip and a mostly-B&W
    board counts toward *both* `hint_circle` and `bw_pre_tap`.
    """
    # Lazy import so plain `pytest` collection doesn't require merceka.
    from merceka_core.llm import LLM

    llm = LLM(model_name, system_prompt="You classify mobile-game screenshots.")
    raw = llm.generate_with_resource(
        _classification_prompt(),
        resource_path=frame,
    )
    text = str(raw).strip()
    matched: set[str] = set()
    for m in LABEL_LINE_RE.finditer(text):
        key = m.group("key").lower()
        ans = m.group("ans").upper()
        if key in STATE_KEYS and ans == "YES":
            matched.add(key)
    return matched


def _extract_frames(video: Path, out_dir: Path) -> list[Path]:
    """Shell out to the installed CLI so the test exercises the real
    `videotoframes extract` end-to-end."""
    if out_dir.exists():
        shutil.rmtree(out_dir)
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "videotoframes.cli",
            "extract",
            str(video),
            "--out",
            str(out_dir),
        ],
        stdout=sys.stderr,
        stderr=sys.stderr,
    )
    frames = sorted(out_dir.glob("frame_*.png"))
    assert frames, f"no frames produced in {out_dir}"
    return frames


@pytest.fixture(scope="module")
def find_the_dog_video() -> Path:
    # Repo root relative to this file: tests/validation/find_the_dog/ → ../../..
    root = Path(__file__).resolve().parents[3]
    p = root / "videos" / "find_the_dog.mp4"
    if not p.is_file():
        pytest.skip(f"fixture video missing: {p}")
    return p


@pytest.fixture(scope="module")
def extracted_frames(find_the_dog_video: Path, tmp_path_factory) -> list[Path]:
    out = tmp_path_factory.mktemp("ftd_frames")
    return _extract_frames(find_the_dog_video, out / "frames")


def test_find_the_dog_coverage(extracted_frames: list[Path], request):
    """Assert the curated set covers ≥7 of 8 gameplay states.

    Runs only if the `--run-validation` pytest option is passed.
    """
    if not request.config.getoption("--run-validation", default=False):
        pytest.skip("validation tests need --run-validation")

    model_name, label = _choose_backend()
    print(f"\n[validation] backend={label} frames={len(extracted_frames)}", file=sys.stderr)

    results: dict[str, list[str]] = {k: [] for k in STATE_KEYS}
    per_frame: list[dict] = []
    for frame in extracted_frames:
        matched = _classify_frame(model_name, frame)
        per_frame.append({"frame": frame.name, "matched": sorted(matched)})
        for key in matched:
            results[key].append(frame.name)

    # Dump a report so a reviewer can eyeball mis-classifications.
    report_dir = Path(__file__).resolve().parent / "_reports"
    report_dir.mkdir(exist_ok=True)
    report = {
        "backend": label,
        "frame_count": len(extracted_frames),
        "per_frame": per_frame,
        "covered_buckets": {k: v for k, v in results.items() if v},
        "missing_buckets": [k for k, v in results.items() if not v],
    }
    (report_dir / "coverage.json").write_text(json.dumps(report, indent=2))

    covered = sum(1 for v in results.values() if v)
    missing = [k for k, v in results.items() if not v]
    print(
        f"[validation] covered {covered}/8 buckets; missing: {missing}",
        file=sys.stderr,
    )
    assert covered >= COVERAGE_FLOOR, (
        f"coverage {covered}/8 below floor {COVERAGE_FLOOR}. "
        f"Missing states: {missing}. Report: {report_dir / 'coverage.json'}"
    )
