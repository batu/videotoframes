---
title: videotoframes — standalone video → curated key frames CLI
date: 2026-04-16
status: active
trello: https://trello.com/c/KU2DIKXb
classification: needs-plan
---

# Plan — videotoframes

## Scope

Ship `videotoframes` v0.0.1 — a standalone CLI that takes an MP4 and emits
curated key frames + a `manifest.yaml` matching
`slab/src/slab/schemas/frame-manifest.md`. Pure utility, no AI. Reusable
outside slab.

The card description and deepened plan (Phase 3) have already settled the
algorithm. This plan fills in the module split, test seam, and the
card-scope-only validation fixture for `find_the_dog.mp4`.

## Module split

All modules live at `src/videotoframes/`. One-feature-per-file, each small
enough that the `fake_subprocess_runner` fixture can inject around a
single boundary.

```
src/videotoframes/
├── __init__.py              — re-exports nothing; thin package marker
├── cli.py                   — argparse dispatch, lazy subcommand imports
├── commands/
│   ├── __init__.py
│   ├── extract.py           — top-level extract orchestration
│   └── manifest.py          — print/read-only manifest command
├── pipeline/
│   ├── __init__.py
│   ├── preflight.py         — ffprobe validate + disk-space check
│   ├── fps_normalize.py     — single ffmpeg -vf fps=60 pass
│   ├── detect.py            — PySceneDetect + dHash single-decode loop
│   ├── curate.py            — scene/UI-change unioning, dedupe
│   └── manifest.py          — render + parse YAML manifest (schema v1)
├── io/
│   ├── __init__.py
│   ├── atomic.py            — atomic_write_bytes/text (tempfile → fsync → replace)
│   └── subproc.py           — run_subprocess thin wrapper; injectable via fixture
└── _version.py              — tool version string, read by manifest frontmatter
```

Test seam: `io/subproc.py` exposes `run(cmd, *, timeout, check=True)` — a
trivial wrapper around `subprocess.run`. `fake_subprocess_runner` in
`tests/conftest.py` monkeypatches `videotoframes.io.subproc.run` to a
callable returning a canned `CompletedProcess` per pattern. This keeps the
production path raw-`subprocess.run` (no runtime indirection cost) and
tests to hit a single monkeypatch.

## CLI surface

```
videotoframes extract <video.mp4> --out <frames_dir> [--fps 60] [--force]
videotoframes manifest <frames_dir>
```

Exit codes:
- 0 — success
- 1 — generic failure (preflight, ffprobe, ffmpeg non-zero, curation produced zero frames)
- 2 — argparse / user error
- 6 — output dir exists and `--force` not given (no silent overwrite)

Cold-start `--help` ≤ 200ms requirement: do **not** `import cv2` / `scenedetect` at
`cli.py` top level. `cli.py` only imports argparse + `commands.<name>`
inside the dispatch function body.

## Extraction algorithm (single-decode)

### Preflight (`pipeline/preflight.py`)

1. `ffprobe -v error -select_streams v:0 -show_entries
   stream=codec_name,width,height,bit_rate,duration -of json <input>` →
   validate:
   - codec is an MP4-compatible codec (h264/hevc/h265/av1)
   - `width × height ≥ 720p` (min long-edge 1280)
   - `duration_s ≥ 30`
2. Tail-black check via `ffprobe -f lavfi -i "movie=<input>,blackdetect=d=0.1:pix_th=0.10"`
   within the last 2s window. If the tail is fully black, abort with a
   truncation error.
3. Disk-space check: `shutil.disk_usage(out_parent).free ≥ max(est * 3, 10 GB)`
   where `est = duration_s * bitrate_bytes_per_s`. Fail before any bytes written.

### FPS normalization (`pipeline/fps_normalize.py`)

- `ffmpeg -y -i <input> -vf fps=60 -c:v libx264 -preset veryfast -crf 23 -an <tmp_out>`
- Timeout `max(duration_s * 3, 60)`.
- Normalized video written to `<out>/.staging/_normalized.mp4`. Deleted
  on success; retained for debugging if `--keep-intermediate` flag set
  (hidden flag, for local use).

### Single-decode loop (`pipeline/detect.py`)

Opens ONE `cv2.VideoCapture`. For each frame:
1. Feed into PySceneDetect's `SceneManager` with two detectors fused:
   - `AdaptiveDetector(adaptive_threshold=3.0, min_content_val=15.0, min_scene_len=30)`
   - `ContentDetector(threshold=18.0, luma_only=False, min_scene_len=30)`
2. Compute `imagehash.dhash(PIL.Image.fromarray(frame_bgr2rgb), hash_size=16)` → 256-bit.
3. Track last-kept-hash; if current frame's Hamming distance > 8 from
   last-kept, mark this timestamp as a UI-change candidate.

Returns `(scene_cut_timestamps: list[float], ui_change_timestamps: list[float], frame_hashes: dict[float, imagehash.ImageHash])`.

### Curation (`pipeline/curate.py`)

1. Union scene cuts + UI-change timestamps with 0.5s neighborhood dedupe
   (`sorted`; drop any timestamp within 0.5s of the previous kept one).
2. For each kept timestamp, re-seek with `cv2.VideoCapture.set(cv2.CAP_PROP_POS_MSEC)`
   and read one frame at the nearest 60fps grid position.
3. Dedupe near-identical frames across the curated set: drop any frame
   whose dHash is within Hamming distance < 4 of a previously kept one.
4. Assign `scene_id`: monotonically increasing int, reset only on a
   PySceneDetect-identified scene cut (UI changes inside a scene share
   the scene's id).
5. Write frames as PNG (`frames/.staging/frame_NNNN.png`, 4-digit
   zero-padded) with `cv2.imwrite(..., [cv2.IMWRITE_PNG_COMPRESSION, 6])`.

### Manifest (`pipeline/manifest.py`)

Render matches `slab/src/slab/schemas/frame-manifest.md` exactly:

```yaml
schema: frame-manifest
schema_version: 1
generated_by: videotoframes/0.0.1
frames:
  - path: frames/0001.png
    timestamp_s: 0.00
    scene_id: 0
    dhash: 8f3e1c2a5d7b9e01
```

Note: schema says `%016x` (16 hex = 64-bit). Our dHash at `hash_size=16`
is 256-bit = 64 hex chars. **Option A: truncate the high 64 bits.
Option B: bump schema to 256-bit hex.** Per card scope rules, schema
changes are out-of-scope here — we truncate with a documented helper
`dhash_to_hex64(h)` that takes the top 64 bits (first 16 hex chars).
This is safe for de-dupe and evidence-pointer hashing since Hamming
distance at 64 bits and 256 bits correlates; perfect fidelity isn't
needed for the manifest's role (the dedupe thresholding happens on the
full 256-bit hash *before* truncation).

Path is relative to `<out_dir>`, e.g. `frame_0001.png` (not prefixed
with `frames/` because `frames/manifest.yaml` is colocated with them —
see schema example which also uses `frames/0001.png` relative to the
bundle root; when the tool is invoked standalone the path is just the
filename). **Decision:** paths in manifest are the PNG filenames
only (`frame_0001.png`), resolved relative to the manifest's parent
dir. Slab's consumer prefixes with `frames/` when copying to the
bundle — this keeps `videotoframes` tool ignorant of bundle layout.

### Atomic write + staging rename (`io/atomic.py`)

- PNGs written to `<out>/.staging/` directly (safe — staging dir is
  owned by this run).
- On curation complete: write `manifest.yaml` via tempfile → fsync →
  `os.replace` into `<out>/.staging/manifest.yaml`.
- Final step: `os.rename(<out>/.staging, <out>)`. If `<out>` already
  exists and `--force` given, `shutil.rmtree(<out>)` first.
- CTRL-C anywhere before the final rename leaves `.staging/` but
  NO `<out>/` — consumer sees nothing partial.

## Validation fixture — `find_the_dog.mp4`

At `tests/validation/find_the_dog/test_coverage.py`:

1. `pytest` marker `@pytest.mark.validation` (skipped unless
   `--run-validation` arg passed to `pytest`).
2. Calls `videotoframes extract <repo>/videos/find_the_dog.mp4 --out
   <tmp>/frames` as a subprocess (integration — real ffmpeg/cv2).
3. For each PNG in `frames/`, calls a **Gemma-via-Ollama vision**
   classifier via `merceka_core.LLM("gemma4:26b").generate_with_resource`
   with a fixed prompt naming the 8 states and asking for the best
   match. Parse the first line of the response as one of 8 labels or
   `none`.
4. Assert `len(unique_buckets) >= 7` out of 8.
5. If Ollama is unreachable (connection refused), fall back to
   Claude multimodal via
   `LLM("openrouter/anthropic/claude-sonnet-4-5").generate_with_resource`.
6. Skip cleanly (not fail) if neither backend available —
   validation needs human VRAM, not a mandatory CI dep.

The 8 gameplay states (from PROJECT_CONTEXT + ground truth):
1. B&W (grayscale) scene before any taps
2. Voronoi cell reveal mid-animation (partial color)
3. Revealed / color scene (multiple dogs found)
4. Wrong-tap red-X marker visible
5. Hint circle pulsing around an unfound dog
6. Level-complete ribbon drop + confetti
7. Retry overlay (after losing all 3 lives)
8. Settings modal open

**Failure path:** if the test fails, re-tune thresholds (adaptive
detector, content detector, dHash hamming bucket) and re-run. Do not
merge on <7/8.

## Unit tests

All under `tests/unit/` with `@pytest.mark.unit`.

- `test_preflight.py` — fake ffprobe JSON outputs cover:
  valid, <720p, <30s duration, fully-black-tail, low-disk.
- `test_manifest.py` — round-trip: render → parse → render is identity
  on a fabricated FrameEntry list; schema discriminator and version
  checks.
- `test_curate.py` — feeds fabricated `(scene_cuts, ui_changes, hashes)`
  through curate, asserts 0.5s neighborhood dedupe and <4 Hamming dedupe.
- `test_cli.py` — `videotoframes --help` exit 0, no heavy imports
  (check `sys.modules` pre/post: `cv2` / `scenedetect` NOT present
  after `--help`).
- `test_atomic.py` — staging rename, CTRL-C simulation, `--force`.

`fake_subprocess_runner` fixture monkeypatches
`videotoframes.io.subproc.run`. Unit tests never invoke real ffmpeg/cv2.

## Dependencies

Already declared in `pyproject.toml`:
- `scenedetect>=0.6`
- `opencv-python-headless>=4.10`
- `imagehash>=4.3`
- `pyyaml>=6.0`

Add to dev dependencies:
- `pytest>=8.0`
- `pytest-asyncio>=0.23` (for validation test which calls async
  merceka methods)
- `pillow>=10.0` (transitive via imagehash but declaring for clarity)

Validation test only imports `merceka_core` — NOT a runtime dep; it's
imported lazily inside the test. The tool itself has zero AI deps.

## Out of scope

- Audio extraction / waveform summary (follow-up card).
- Streaming / live-ingest extraction.
- Schema bump to 256-bit dhash (follow-up if the truncation causes
  evidence-pointer collisions in practice — unlikely).
- Gemini long-context validation backend (Gemma + Claude are enough for
  the 8-bucket task).

## Acceptance criteria (from card)

- [x] `uv tool install --editable /home/batu/Desktop/utolye/videotoframes` succeeds.
- [x] `videotoframes --help` cold-start ≤ 200ms.
- [x] Produces schema-valid manifest on a fixture video.
- [x] CTRL-C mid-run leaves no partial `frames/`.
- [x] Disk-preflight refuses before writes on insufficient free space.
- [x] Unit tests pass without ffmpeg/cv2 via `fake_subprocess_runner`.
- [x] `find_the_dog.mp4` validation: ≥7/8 gameplay-state buckets covered.
