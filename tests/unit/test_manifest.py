"""Manifest render/parse round-trip + schema discriminator checks."""

from __future__ import annotations

import pytest

from videotoframes.pipeline.manifest import (
    FrameEntry,
    SCHEMA_NAME,
    SCHEMA_VERSION,
    parse,
    render,
)


pytestmark = pytest.mark.unit


def _sample_entries() -> list[FrameEntry]:
    return [
        FrameEntry(path="frame_0001.png", timestamp_s=0.0, scene_id=0, dhash="8f3e1c2a5d7b9e01"),
        FrameEntry(path="frame_0002.png", timestamp_s=3.25, scene_id=1, dhash="a1b2c3d4e5f60718"),
        FrameEntry(path="frame_0003.png", timestamp_s=6.50, scene_id=1, dhash="deadbeef00112233"),
    ]


def test_render_then_parse_is_identity():
    entries = _sample_entries()
    text = render(entries)
    parsed = parse(text)
    assert parsed == entries


def test_render_includes_schema_frontmatter():
    text = render(_sample_entries())
    assert f"schema: {SCHEMA_NAME}" in text
    assert f"schema_version: {SCHEMA_VERSION}" in text
    assert "generated_by: videotoframes/" in text


def test_parse_rejects_wrong_schema():
    bad = "schema: specimen\nschema_version: 1\ngenerated_by: x/0.0.1\nframes: []\n"
    with pytest.raises(ValueError, match="expected schema"):
        parse(bad)


def test_parse_rejects_wrong_version():
    bad = f"schema: {SCHEMA_NAME}\nschema_version: 99\ngenerated_by: x/0.0.1\nframes: []\n"
    with pytest.raises(ValueError, match="schema_version"):
        parse(bad)


def test_parse_rejects_non_hex_dhash():
    bad = (
        f"schema: {SCHEMA_NAME}\n"
        f"schema_version: {SCHEMA_VERSION}\n"
        "generated_by: videotoframes/0.0.1\n"
        "frames:\n"
        "  - path: frame_0001.png\n"
        "    timestamp_s: 0.0\n"
        "    scene_id: 0\n"
        "    dhash: zzzzzzzzzzzzzzzz\n"
    )
    with pytest.raises(ValueError, match="hex"):
        parse(bad)


def test_parse_rejects_wrong_length_dhash():
    bad = (
        f"schema: {SCHEMA_NAME}\n"
        f"schema_version: {SCHEMA_VERSION}\n"
        "generated_by: videotoframes/0.0.1\n"
        "frames:\n"
        "  - path: frame_0001.png\n"
        "    timestamp_s: 0.0\n"
        "    scene_id: 0\n"
        "    dhash: abc\n"
    )
    with pytest.raises(ValueError, match="hex"):
        parse(bad)


def test_parse_rejects_missing_key():
    bad = (
        f"schema: {SCHEMA_NAME}\n"
        f"schema_version: {SCHEMA_VERSION}\n"
        "generated_by: videotoframes/0.0.1\n"
        "frames:\n"
        "  - path: frame_0001.png\n"
        "    timestamp_s: 0.0\n"
        # missing scene_id
        "    dhash: 8f3e1c2a5d7b9e01\n"
    )
    with pytest.raises(ValueError, match="missing required key"):
        parse(bad)


def test_example_from_schema_doc_roundtrips():
    """The exact example from slab/src/slab/schemas/frame-manifest.md."""
    example = (
        "schema: frame-manifest\n"
        "schema_version: 1\n"
        "generated_by: videotoframes/0.0.1\n"
        "frames:\n"
        "  - path: frames/0001.png\n"
        "    timestamp_s: 0.00\n"
        "    scene_id: 0\n"
        "    dhash: 8f3e1c2a5d7b9e01\n"
        "  - path: frames/0002.png\n"
        "    timestamp_s: 0.50\n"
        "    scene_id: 0\n"
        "    dhash: 8f3e1c2a5d7b9e01\n"
        "  - path: frames/0003.png\n"
        "    timestamp_s: 3.20\n"
        "    scene_id: 1\n"
        "    dhash: a1b2c3d4e5f60718\n"
    )
    parsed = parse(example)
    assert len(parsed) == 3
    assert parsed[0].dhash == "8f3e1c2a5d7b9e01"
    # Round-trip: render(parse(x)) parses again to the same entries.
    assert parse(render(parsed)) == parsed
