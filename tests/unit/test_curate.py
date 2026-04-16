"""Curation algorithm: timestamp union, neighborhood dedupe.

The cv2/ffmpeg pass is not tested here — those belong in integration.
We test the pure timestamp-union logic.
"""

from __future__ import annotations

import pytest

from videotoframes.pipeline.curate import _union_and_neighborhood_dedupe


pytestmark = pytest.mark.unit


def test_includes_opening_frame():
    events = _union_and_neighborhood_dedupe(scene_cuts=[], ui_changes=[])
    assert events == [(0.0, True)]


def test_neighborhood_drops_close_events():
    # 0.0 (opening), 0.1 (UI close to opening → dropped),
    # 0.6 (UI far enough → kept), 0.7 (UI too close → dropped),
    # 2.0 (scene cut → kept).
    events = _union_and_neighborhood_dedupe(
        scene_cuts=[2.0],
        ui_changes=[0.1, 0.6, 0.7],
    )
    kept_ts = [t for t, _ in events]
    assert kept_ts == [0.0, 0.6, 2.0]


def test_scene_cut_upgrades_recent_ui_change():
    """If a scene cut lands within the neighborhood AFTER a UI change,
    the kept event should be upgraded to a scene cut (stronger signal)."""
    # 0.0 (opening scene-cut), 0.6 (UI kept), 0.75 (scene cut inside
    # the 0.2s neighborhood of 0.6 → upgrades 0.6 to scene cut).
    events = _union_and_neighborhood_dedupe(
        scene_cuts=[0.75],
        ui_changes=[0.6],
    )
    assert [(e[0], e[1]) for e in events] == [(0.0, True), (0.6, True)]


def test_simultaneous_events_prefer_scene_cut():
    """Scene cut and UI change at the same timestamp → the event is a
    scene cut."""
    events = _union_and_neighborhood_dedupe(scene_cuts=[5.0], ui_changes=[5.0])
    assert events[-1] == (5.0, True)


def test_many_close_ui_changes_collapsed():
    """A burst of 10 UI changes within 0.2s collapses to 1 kept frame."""
    events = _union_and_neighborhood_dedupe(
        scene_cuts=[],
        ui_changes=[1.0 + i * 0.02 for i in range(10)],
    )
    assert len(events) == 2  # opening + first of the burst
    assert events[0] == (0.0, True)
    assert events[1][0] == pytest.approx(1.0)
