"""Render + parse `manifest.yaml` — the frame-manifest schema v1.

Schema canonical source: `utolye/slab/src/slab/schemas/frame-manifest.md`.
Keep this module in lock-step with the schema doc; any drift is a
contract bug.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import imagehash  # type: ignore[import-untyped]
import yaml

from videotoframes._version import __version__
from videotoframes.pipeline.curate import CuratedFrame

SCHEMA_NAME = "frame-manifest"
SCHEMA_VERSION = 1


@dataclass(frozen=True)
class FrameEntry:
    path: str
    timestamp_s: float
    scene_id: int
    dhash: str  # 16 hex chars, %016x per schema v1


def dhash_to_hex64(h: imagehash.ImageHash) -> str:
    """Truncate a 256-bit imagehash to the top 64 bits as `%016x`.

    Rationale: `imagehash.dhash(..., hash_size=16)` gives 256 bits.
    Schema v1 dhash is 64 bits. Dedupe runs on the full 256-bit hash
    inside curate.py; this projection is only for the on-disk manifest.
    Collision risk is acceptable because the manifest's dhash is an
    evidence pointer, not a dedupe key.
    """
    # imagehash stores bits in a boolean ndarray; convert to int via hex
    # (a stable, library-endorsed path), take the top 16 hex chars.
    full_hex = str(h)  # imagehash.__str__ emits hex_length = bits // 4
    return full_hex[:16]


def frame_entries(curated: list[CuratedFrame]) -> list[FrameEntry]:
    """Convert curated frames into schema-shaped entries."""
    return [
        FrameEntry(
            path=f"frame_{c.index:04d}.png",
            timestamp_s=round(c.timestamp_s, 2),
            scene_id=c.scene_id,
            dhash=dhash_to_hex64(c.dhash),
        )
        for c in curated
    ]


def render(entries: list[FrameEntry]) -> str:
    """Render the manifest YAML. Deterministic key order."""
    body: dict[str, Any] = {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "generated_by": f"videotoframes/{__version__}",
        "frames": [
            {
                "path": e.path,
                "timestamp_s": e.timestamp_s,
                "scene_id": e.scene_id,
                "dhash": e.dhash,
            }
            for e in entries
        ],
    }
    return yaml.safe_dump(body, sort_keys=False, default_flow_style=False)


def parse(content: str) -> list[FrameEntry]:
    """Parse a manifest YAML string into FrameEntry list.

    Validates schema name + version. Raises `ValueError` on mismatch.
    """
    payload = yaml.safe_load(content)
    if not isinstance(payload, dict):
        raise ValueError(f"manifest must be a mapping, got {type(payload).__name__}")
    schema = payload.get("schema")
    if schema != SCHEMA_NAME:
        raise ValueError(f"expected schema '{SCHEMA_NAME}', got '{schema!r}'")
    version = payload.get("schema_version")
    if version != SCHEMA_VERSION:
        raise ValueError(f"expected schema_version {SCHEMA_VERSION}, got {version!r}")

    frames_raw = payload.get("frames") or []
    if not isinstance(frames_raw, list):
        raise ValueError("'frames' must be a list")

    entries: list[FrameEntry] = []
    for i, entry in enumerate(frames_raw):
        if not isinstance(entry, dict):
            raise ValueError(f"frame[{i}] must be a mapping")
        try:
            entries.append(
                FrameEntry(
                    path=str(entry["path"]),
                    timestamp_s=float(entry["timestamp_s"]),
                    scene_id=int(entry["scene_id"]),
                    dhash=str(entry["dhash"]),
                )
            )
        except KeyError as exc:
            raise ValueError(f"frame[{i}] missing required key: {exc}") from exc

    # Lightweight well-formedness: dhash is 16 hex chars.
    for i, e in enumerate(entries):
        if len(e.dhash) != 16 or any(c not in "0123456789abcdef" for c in e.dhash.lower()):
            raise ValueError(f"frame[{i}].dhash must be 16 hex chars, got {e.dhash!r}")

    return entries


def write(manifest_path: Path, entries: list[FrameEntry]) -> None:
    """Render and atomically write the manifest to disk."""
    # Local import keeps pipeline/* free of io/* import coupling at the
    # module-top level.
    from videotoframes.io.atomic import atomic_write_text

    atomic_write_text(manifest_path, render(entries))


def read(manifest_path: Path) -> list[FrameEntry]:
    """Read and parse a manifest from disk."""
    return parse(manifest_path.read_text(encoding="utf-8"))
