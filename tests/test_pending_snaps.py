"""Snapping to the curve you are still drawing.

Until a polyline is finished it is not in the scene, so it offered no snap
candidates at all: you could not close it back onto its own start, or land a
later leg on an earlier vertex. Reported twice on the Rhino forum.

The same hole is there in every other multi-pick command — the end of an arc
could not find its start — so the points a command has taken are tracked by
the processor, not left to each command to volunteer.
"""

import json

import numpy as np
import pytest

from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.core.snaps import SnapIndex


def _vp(scene=None):
    from serpentine3d.ui.viewport import Viewport
    scene = scene or Scene()
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(900, 700)
    vp.camera.target = np.zeros(3)
    vp.camera.distance = 40.0
    vp.point_axis = None
    return vp, scene


def _px(vp, world):
    scr = vp.camera.project(np.asarray([world], float),
                            vp.width(), vp.height())[0]
    return float(scr[0]), float(scr[1])


# -- the index --

def test_the_start_of_the_open_polyline_is_a_snap_candidate():
    scene = Scene()
    idx = SnapIndex(scene)
    vp, _ = _vp(scene)
    pending = [(0, 0, 0), (10, 0, 0), (10, 10, 0)]
    px, py = _px(vp, (0, 0, 0))
    hit = idx.find(vp.camera, px, py, vp.width(), vp.height(),
                   pending_points=pending)
    assert hit is not None
    assert hit[1] == "end"
    assert np.allclose(hit[0], (0, 0, 0))


def test_the_leg_you_are_pulling_from_does_not_snap_to_itself():
    """The newest point sits under the cursor the instant you place it —
    offering it would glue every new leg to zero length."""
    scene = Scene()
    idx = SnapIndex(scene)
    vp, _ = _vp(scene)
    pending = [(0, 0, 0), (10, 0, 0)]
    px, py = _px(vp, (10, 0, 0))
    assert idx.find(vp.camera, px, py, vp.width(), vp.height(),
                    pending_points=pending) is None


def test_midpoints_of_the_legs_already_drawn_are_offered():
    scene = Scene()
    idx = SnapIndex(scene)
    vp, _ = _vp(scene)
    pending = [(0, 0, 0), (10, 0, 0), (10, 10, 0)]
    px, py = _px(vp, (5, 0, 0))
    hit = idx.find(vp.camera, px, py, vp.width(), vp.height(),
                   pending_points=pending)
    assert hit is not None and hit[1] == "mid"
    assert np.allclose(hit[0], (5, 0, 0))


def test_a_disabled_snap_type_stays_disabled_for_the_open_curve():
    scene = Scene()
    idx = SnapIndex(scene)
    idx.types["end"] = False
    vp, _ = _vp(scene)
    px, py = _px(vp, (0, 0, 0))
    assert idx.find(vp.camera, px, py, vp.width(), vp.height(),
                   pending_points=[(0, 0, 0), (10, 0, 0), (10, 10, 0)]) is None


def test_a_single_picked_point_offers_nothing():
    """One point in hand is the point you are drawing from."""
    scene = Scene()
    idx = SnapIndex(scene)
    vp, _ = _vp(scene)
    px, py = _px(vp, (0, 0, 0))
    assert idx.find(vp.camera, px, py, vp.width(), vp.height(),
                    pending_points=[(0, 0, 0)]) is None


# -- the viewport --

def test_the_viewport_starts_with_no_pending_points():
    vp, _ = _vp()
    assert vp.pending_points == []


def test_world_point_at_honours_the_pending_points():
    vp, _ = _vp()
    vp.pending_points = [(0, 0, 0), (10, 0, 0), (10, 10, 0)]
    px, py = _px(vp, (0, 0, 0))
    p = vp.world_point_at(px, py)
    assert vp._active_snap is not None and vp._active_snap[1] == "end"
    assert np.allclose(p, (0, 0, 0))


# -- the app wires them up --

@pytest.fixture
def window(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({}))
    monkeypatch.setenv("SERP3D_CONFIG", str(cfg))
    monkeypatch.setenv("SERP3D_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    from serpentine3d.app import MainWindow
    w = MainWindow()
    yield w
    w._saved_revision = w.scene.revision
    w.close()


def test_drawing_a_polyline_hands_the_picked_points_to_the_viewport(window):
    window.processor.run("polyline")
    for t in ("0,0", "10,0", "10,10"):
        window.processor.provide_text(t)
    pts = [tuple(round(float(c), 6) for c in p)
           for p in window.viewport.pending_points]
    assert pts == [(0, 0, 0), (10, 0, 0), (10, 10, 0)]


def test_finishing_the_command_clears_them(window):
    window.processor.run("polyline")
    window.processor.provide_text("0,0")
    window.processor.provide_text("10,0")
    assert window.viewport.pending_points
    window.processor.cancel()
    assert window.viewport.pending_points == []


# -- every command's picked points, not just the ones that draw a chain --

def test_loose_picks_offer_their_ends():
    scene = Scene()
    idx = SnapIndex(scene)
    vp, _ = _vp(scene)
    px, py = _px(vp, (0, 0, 0))
    hit = idx.find(vp.camera, px, py, vp.width(), vp.height(),
                   picked_points=[(0, 0, 0), (10, 0, 0), (10, 10, 0)])
    assert hit is not None and hit[1] == "end"
    assert np.allclose(hit[0], (0, 0, 0))


def test_loose_picks_offer_no_midpoints():
    """Two corners of a box are picked in sequence, but the line between
    them is a diagonal — halfway along it is not a feature of anything."""
    scene = Scene()
    idx = SnapIndex(scene)
    vp, _ = _vp(scene)
    px, py = _px(vp, (5, 0, 0))
    assert idx.find(vp.camera, px, py, vp.width(), vp.height(),
                    picked_points=[(0, 0, 0), (10, 0, 0),
                                   (10, 10, 0)]) is None


def test_the_newest_loose_pick_is_left_out_too():
    scene = Scene()
    idx = SnapIndex(scene)
    vp, _ = _vp(scene)
    px, py = _px(vp, (10, 0, 0))
    assert idx.find(vp.camera, px, py, vp.width(), vp.height(),
                    picked_points=[(0, 0, 0), (10, 0, 0)]) is None


def test_the_viewport_starts_with_no_picked_points():
    vp, _ = _vp()
    assert vp.picked_points == []


def test_world_point_at_honours_the_picked_points():
    vp, _ = _vp()
    vp.picked_points = [(0, 0, 0), (10, 0, 0)]
    px, py = _px(vp, (0, 0, 0))
    p = vp.world_point_at(px, py)
    assert vp._active_snap is not None and vp._active_snap[1] == "end"
    assert np.allclose(p, (0, 0, 0))


# -- the processor keeps the tally --

def test_the_processor_remembers_the_points_a_command_has_taken(window):
    window.processor.run("arc")
    window.processor.provide_text("0,0")
    window.processor.provide_text("10,0")
    pts = [tuple(round(float(c), 6) for c in p)
           for p in window.processor.picked_points]
    assert pts == [(0, 0, 0), (10, 0, 0)]


def test_answers_that_are_not_points_are_not_counted(window):
    """scalenu takes a base point and then three scale factors; a factor is
    a ratio, and a ratio is not somewhere you can snap to."""
    from serpentine3d.core import geometry as g
    obj = window.scene.add(g.make_circle((0, 0, 0), 3))
    window.selection.set([obj.id])
    window.processor.run("scalenu")
    window.processor.provide_text("0,0")
    window.processor.provide_text("2")
    pts = [tuple(round(float(c), 6) for c in p)
           for p in window.processor.picked_points]
    assert pts == [(0, 0, 0)]


def test_a_fresh_command_starts_its_own_tally(window):
    window.processor.run("arc")
    window.processor.provide_text("0,0")
    assert window.processor.picked_points
    window.processor.run("line")
    assert window.processor.picked_points == []


def test_the_tally_is_dropped_when_the_command_ends(window):
    window.processor.run("arc")
    window.processor.provide_text("0,0")
    window.processor.cancel()
    assert window.processor.picked_points == []


def test_the_arc_end_can_find_the_arc_start(window):
    """The forum report, in one test: three picks in, the earlier two are
    on offer even though an arc never volunteers a rubber chain."""
    window.processor.run("arc")
    window.processor.provide_text("0,0")
    window.processor.provide_text("10,0")
    pts = [tuple(round(float(c), 6) for c in p)
           for p in window.viewport.picked_points]
    assert pts == [(0, 0, 0), (10, 0, 0)]
