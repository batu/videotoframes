---
title: dHash returns all-zero on solid-color frames, collapsing them into one curated frame
category: pipeline-tuning
date: 2026-04-16
tags:
  - dhash
  - imagehash
  - pyscenedetect
  - curate
  - test-fixtures
components:
  - src/videotoframes/pipeline/curate.py
  - tests/integration/test_synthetic_extract.py
severity: design-gotcha
origin: videotoframes card KU2DIKXb, 2026-04-16
---

# dHash returns all-zero on solid-color frames, collapsing them into one curated frame

## Symptom

Synthetic test fixture: six solid-color scenes concatenated via
`-filter_complex concat`, each 5s, 30s total. PySceneDetect correctly
reports 5 scene cuts. Curation produces **1** curated frame.

```
detected: 5 scene cuts, 1 UI changes, 180 frames sampled
curated 1 frames
```

Card acceptance criterion wants 5-15 curated frames — test fails.

## Root cause

`imagehash.dhash(image, hash_size=16)` computes its 256-bit hash by
taking the sign of horizontal gradients between adjacent pixels. For a
solid-color frame every gradient is zero, so every bit of the hash is
zero. Red, green, blue, yellow — all six colors produce the **same**
all-zeros hash. Pairwise Hamming distance is 0:

```python
>>> for c in ("red","green","blue","yellow","magenta","cyan"):
...     arr = np.full((720,1280,3), COLOR_BGR[c], dtype=np.uint8)
...     h = imagehash.dhash(Image.fromarray(arr[:,:,::-1]), hash_size=16)
...     print(c, str(h))
red      0000000000000000000000000000000000000000000000000000000000000000
green    0000000000000000000000000000000000000000000000000000000000000000
blue     0000000000000000000000000000000000000000000000000000000000000000
...
```

`curate.py`'s `DEDUPE_HAMMING = 2` check against the list of already-kept
hashes fires on the very first comparison, so every post-opening frame
is dropped as a "near-duplicate".

This is not a bug in the production pipeline — real game footage has
gradients everywhere (UI chrome, textures, anti-aliased edges), so
dHash distinguishes frames just fine. It IS a bug in a naive synthetic
fixture.

## Fix

Two options: (a) change the synthetic fixture to have texture,
(b) loosen `DEDUPE_HAMMING` so adjacent solid colors aren't collapsed.

**Picked (a)** — loosening the production threshold to accommodate a
degenerate test input would make the pipeline dedupe-blind on real
content (the 2-bit threshold was tightened specifically to catch
partial-area UI overlays like a red-X marker or hint tooltip, which
only dirty a small region of the 256-bit hash).

The lavfi fixture now overlays a per-scene text label via `drawtext`:

```
[i]drawtext=text='RED':fontsize=200:fontcolor=black:x=(w-text_w)/2:y=(h-text_h)/2[vi]
```

Each scene's dHash now reflects the distinctive gradient pattern from
the anti-aliased text glyph — Hamming distances between scenes are well
above `DEDUPE_HAMMING=2`. Test produces 6 curated frames and the
pipeline is unchanged.

The test gates on `_has_drawtext_support()` so an ffmpeg built without
`libfreetype` (rare but possible in minimal containers) skips rather
than fails.

## Lesson

When choosing a synthetic test fixture for a perceptual-hash pipeline,
pick content that **exercises the hash's degrees of freedom**. dHash
responds to gradients. A lavfi-color test that produces flat frames
exercises scene detection but not dedupe — which is the pipeline's
other load-bearing algorithm. Add `drawtext` labels, noise filters,
or `testsrc` patterns so the fixture lives on the same manifold as real
content.

The general version of this lesson: **test fixtures must share the
input statistics the production algorithm assumes.** A perceptual
pipeline tested on synthetic uniform data will silently fail on live
data, and vice versa.
