# Solutions index — videotoframes

Institutional knowledge. One line per entry, newest at top. Append via `/ce:compound`.

<!-- entries below -->

- 2026-04-16 — [dHash returns all-zero on solid-color frames, collapsing them into one curated frame](pipeline-tuning/dhash-collapses-solid-color-frames.md) — test fixture gotcha: synthetic lavfi color scenes need `drawtext` labels (or other gradient texture) so dHash distinguishes them; picked fixing the fixture over loosening `DEDUPE_HAMMING`.
