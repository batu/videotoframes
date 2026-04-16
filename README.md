# videotoframes

Video → curated key frames + manifest. Standalone CLI, no AI.

## What it does

Single-decode pipeline over ffmpeg + PySceneDetect + `imagehash.dhash`. Extracts key frames at scene transitions and UI-state changes, writes them plus a `manifest.yaml` describing timestamps and perceptual hashes.

## Install

```bash
uv tool install --editable /home/batu/Desktop/utolye/videotoframes
```

## Usage

```bash
videotoframes extract playthrough.mp4 --out frames/
videotoframes manifest frames/
```

## Project context

This is one of four tools in the **slab** mobile-game-mechanic research project. Read the project-wide context before implementing changes:

→ [`utolye/docs/slab-project.md`](../docs/slab-project.md)

The tool is pure utility and reusable outside slab — meeting-note analysis, mindweaver video ingestion, any "extract the interesting frames from a video" need.
