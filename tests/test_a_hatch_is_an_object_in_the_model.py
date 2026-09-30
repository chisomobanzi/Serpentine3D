"""A hatch is an object in the model, not only a mark on a sheet (#33).

Asked for: hatch as an object in the normal model area. Until now a hatch
could only be drawn on a layout, in paper millimetres, and the command
said "Hatches go on layouts" anywhere else.

In the model a hatch fills the closed planar curves you pick, a curve
inside another being a hole, and it stays a hatch: it moves, turns,
scales and copies as one, keeps its pattern, angle and spacing through a
save, and its area is the area it covers. It is its own kind of object,
so the commands that work on loose curves (offset, join, split) do not
take one and quietly turn it into lines.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.hatch import HatchShape
from serpentine3d.core.layers import DEFAULT_LAYER_ID


def _square(size=10.0, corner=(0.0, 0.0), z=0.0):
    x, y = corner
    return g.make_polyline([(x, y, z), (x + size, y, z), (x + size, y + size, z),
                            (x, y + size, z)], closed=True)


def _face(size=10.0, hole=None):
    """A square face, with a round hole of radius `hole` at its middle."""
    curves = [_square(size)]
    if hole:
        curves.append(g.make_circle((size / 2, size / 2, 0), hole))
    (face,) = g.planar_regions(curves)
    return face


def _lines(hatch):
    """The hatch's pattern lines, as (start, end) pairs, boundary left out."""
    return hatch.pattern_segments()


# --- the shape --------------------------------------------------------------

def test_a_hatch_is_its_own_kind_of_object():
    hatch = HatchShape(_face(), "lines", angle=0.0, spacing=1.0)

    assert g.shape_kind(hatch) == "hatch"


def test_lines_fill_the_region_at_the_spacing_and_angle_asked_for():
    hatch = HatchShape(_face(10.0), "lines", angle=0.0, spacing=1.0)

    segs = _lines(hatch)
    assert len(segs) == 10, "one line every unit across a region ten high"
    for a, b in segs:
        assert a[1] == pytest.approx(b[1]), "angle 0 runs along X"
        assert math.dist(a, b) == pytest.approx(10.0, abs=1e-6)


def test_the_angle_turns_the_lines():
    hatch = HatchShape(_face(10.0), "lines", angle=90.0, spacing=1.0)

    for a, b in _lines(hatch):
        assert a[0] == pytest.approx(b[0]), "angle 90 runs along Y"


def test_cross_goes_over_the_region_twice():
    lines = HatchShape(_face(10.0), "lines", angle=0.0, spacing=1.0)
    cross = HatchShape(_face(10.0), "cross", angle=0.0, spacing=1.0)

    assert len(_lines(cross)) == 2 * len(_lines(lines))


def test_a_hole_is_left_empty():
    hatch = HatchShape(_face(10.0, hole=2.0), "lines", angle=0.0, spacing=0.5)

    for a, b in _lines(hatch):
        mid = np.add(a, b) / 2
        assert math.dist(mid[:2], (5.0, 5.0)) > 2.0 - 1e-6, \
            "a line crossed the hole instead of stopping at it"


def test_solid_is_a_filled_region():
    hatch = HatchShape(_face(10.0, hole=2.0), "solid")

    assert _lines(hatch) == []
    assert len(g.faces_of(hatch)) == 1


@pytest.mark.parametrize("pattern", ["lines", "cross", "solid"])
def test_its_area_is_the_area_it_covers(pattern):
    hatch = HatchShape(_face(10.0, hole=2.0), pattern, spacing=1.0)

    assert g.surface_area(hatch) == pytest.approx(100 - math.pi * 4, rel=1e-4)


# --- it moves as one, and stays a hatch -------------------------------------

def test_moving_a_hatch_keeps_it_a_hatch():
    hatch = HatchShape(_face(10.0), "cross", angle=30.0, spacing=1.0)

    moved = g.translate(hatch, (5.0, 0.0, 2.0))

    assert isinstance(moved, HatchShape)
    assert (moved.pattern, moved.angle, moved.spacing) == ("cross", 30.0, 1.0)
    lo, hi = g.bbox(moved)
    assert lo == pytest.approx((5.0, 0.0, 2.0), abs=1e-6)
    assert hi == pytest.approx((15.0, 10.0, 2.0), abs=1e-6)


def test_turning_a_hatch_turns_its_lines_with_it():
    hatch = HatchShape(_face(10.0), "lines", angle=0.0, spacing=1.0)

    turned = g.rotate(hatch, (0, 0, 0), (0, 0, 1), 90.0)

    assert turned.angle == pytest.approx(0.0), "the angle is the hatch's own"
    for a, b in _lines(turned):
        assert a[0] == pytest.approx(b[0], abs=1e-6), \
            "lines along X, turned a quarter, run along Y"


def test_scaling_a_hatch_scales_its_spacing():
    hatch = HatchShape(_face(10.0), "lines", angle=0.0, spacing=1.0)

    big = g.scale(hatch, (0, 0, 0), 2.0)

    assert big.spacing == pytest.approx(2.0)
    assert g.surface_area(big) == pytest.approx(400.0, rel=1e-6)
    assert len(_lines(big)) == 10, "the same drawing, twice the size"


def test_a_copy_is_a_hatch_like_the_original():
    hatch = HatchShape(_face(10.0), "cross", angle=15.0, spacing=0.5)

    twin = g.copy_shape(hatch)

    assert isinstance(twin, HatchShape)
    assert (twin.pattern, twin.angle, twin.spacing) == ("cross", 15.0, 0.5)


def test_a_hatch_off_the_world_plane_hatches_its_own_plane():
    face = _face(10.0)
    upright = g.rotate(face, (0, 0, 0), (1, 0, 0), 90.0)     # into XZ

    hatch = HatchShape(upright, "lines", angle=0.0, spacing=1.0)

    for a, b in _lines(hatch):
        assert a[1] == pytest.approx(0.0, abs=1e-9)
        assert b[1] == pytest.approx(0.0, abs=1e-9)


def test_an_edit_keeps_the_region_and_changes_the_look():
    hatch = HatchShape(_face(10.0), "lines", angle=0.0, spacing=1.0)

    solid = hatch.edited(pattern="solid")
    finer = hatch.edited(spacing=0.5)

    assert solid.pattern == "solid" and _lines(solid) == []
    assert len(_lines(finer)) == 20
    assert np.ravel(g.bbox(finer)) == pytest.approx(np.ravel(g.bbox(hatch)))


# --- it survives a file -----------------------------------------------------

def test_a_hatch_survives_its_own_bytes():
    hatch = HatchShape(_face(10.0, hole=2.0), "cross", angle=30.0, spacing=0.75)

    back = g.shape_from_bytes(g.shape_to_bytes(hatch))

    assert isinstance(back, HatchShape)
    assert (back.pattern, back.angle, back.spacing) == ("cross", 30.0, 0.75)
    assert g.surface_area(back) == pytest.approx(g.surface_area(hatch))


def test_a_hatch_survives_a_saved_file(tmp_path):
    from serpentine3d.core.scene import Scene
    from serpentine3d.fileio.native import load_scene, save_scene
    scene = Scene()
    scene.add(HatchShape(_face(10.0), "cross", angle=30.0, spacing=0.75),
              name="Floor")
    path = str(tmp_path / "hatch.serp")
    save_scene(scene, path)

    back = Scene()
    load_scene(back, path)

    (obj,) = back.all()
    assert obj.kind == "hatch" and obj.name == "Floor"
    assert (obj.shape.pattern, obj.shape.angle, obj.shape.spacing) == \
        ("cross", 30.0, 0.75)


def test_an_older_release_is_told_it_cannot_read_the_hatch(tmp_path):
    """A release that does not know hatches would fail deep in the load."""
    import json
    import zipfile
    from serpentine3d.core.scene import Scene
    from serpentine3d.fileio.native import save_scene
    scene = Scene()
    scene.add(HatchShape(_face(10.0), "lines", spacing=1.0))
    path = str(tmp_path / "hatch.serp")
    save_scene(scene, path)

    with zipfile.ZipFile(path) as z:
        doc = json.loads(z.read("document.json"))
    assert doc["version"] >= 5
    assert doc["requires"] == "0.10.5"


# --- the command ------------------------------------------------------------

def _pick(proc, *objs):
    for o in objs:
        proc.click_object(o.id)
    proc.finish_selection()


def test_the_command_hatches_picked_curves_in_the_model(env):
    scene, sel, _hist, ctx, proc = env
    outer = scene.add(_square(10.0), name="Outline")
    hole = scene.add(g.make_circle((5, 5, 0), 2.0), name="Hole")

    proc.run("hatch")
    _pick(proc, outer, hole)
    proc.provide_text("Lines")
    proc.provide_text("0.5")          # spacing
    proc.provide_text("45")           # angle

    hatches = [o for o in scene.all() if o.kind == "hatch"]
    assert len(hatches) == 1, "the circle is a hole in the square, not a region"
    h = hatches[0].shape
    assert (h.pattern, h.angle, h.spacing) == ("lines", 45.0, 0.5)
    assert g.surface_area(h) == pytest.approx(100 - math.pi * 4, rel=1e-4)
    assert scene.get(outer.id) is not None and scene.get(hole.id) is not None, \
        "the boundary curves are kept, as Rhino keeps them"
    assert sel.ids == [hatches[0].id], "what it made is left selected"


def test_separate_curves_make_separate_hatches(env):
    scene, _sel, _hist, _ctx, proc = env
    a = scene.add(_square(4.0))
    b = scene.add(_square(4.0, corner=(10.0, 0.0)))

    proc.run("hatch")
    _pick(proc, a, b)
    proc.provide_text("Solid")

    assert sum(1 for o in scene.all() if o.kind == "hatch") == 2


def test_the_pattern_starts_from_the_layer(env):
    scene, _sel, _hist, _ctx, proc = env
    scene.layers.set_hatch(DEFAULT_LAYER_ID, "solid")
    outline = scene.add(_square(10.0))

    proc.run("hatch")
    _pick(proc, outline)

    assert proc.request.default == "Solid"


def test_an_open_curve_is_turned_away_with_a_reason(env):
    scene, _sel, _hist, ctx, proc = env
    said = []
    ctx.add_echo_listener(said.append)
    line = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))

    proc.run("hatch")
    _pick(proc, line)

    assert not any(o.kind == "hatch" for o in scene.all())
    assert any("closed" in m for m in said), said


def test_a_hatch_is_not_offered_to_the_curve_commands(env):
    scene, _sel, _hist, _ctx, proc = env
    hatch = scene.add(HatchShape(_face(10.0), "lines", spacing=1.0))

    proc.run("offset")
    proc.click_object(hatch.id)

    assert hatch.id not in proc._select_buffer, \
        "offset would have turned the hatch into loose lines"
    proc.cancel()


def test_selhatch_selects_the_hatches(env):
    scene, sel, _hist, _ctx, proc = env
    h = scene.add(HatchShape(_face(10.0), "lines", spacing=1.0))
    scene.add(_square(3.0))

    proc.run("selhatch")

    assert sel.ids == [h.id]


# --- it is not lost on the way out ------------------------------------------

def test_a_line_hatch_leaves_a_3dm_as_its_curves(tmp_path):
    """rhino3dm cannot write a hatch; a line hatch must not vanish."""
    import rhino3dm as r3
    from serpentine3d.core.scene import Scene
    from serpentine3d.fileio.rhino import export_3dm
    scene = Scene()
    scene.add(HatchShape(_face(10.0), "lines", angle=0.0, spacing=1.0))
    path = str(tmp_path / "h.3dm")

    export_3dm(scene, path)

    curves = [o for o in r3.File3dm.Read(path).Objects
              if isinstance(o.Geometry, r3.Curve)]
    assert len(curves) >= 10, "its ten lines, and its boundary"


def test_a_hatch_snaps_to_its_boundary_not_its_lines():
    from serpentine3d.core.snaps import snap_points_for
    hatch = HatchShape(_face(10.0), "lines", angle=0.0, spacing=0.1)

    points = snap_points_for(hatch)

    assert len(points) < 20, "a hundred lines would bury every other snap"
    kinds = {k for _p, k in points}
    assert {"end", "mid", "center"} <= kinds


# --- it can be changed after it is placed -----------------------------------

@pytest.fixture
def panel():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from serpentine3d.core.history import History
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.properties import PropertiesPanel
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    p = PropertiesPanel(scene, selection, history)
    try:
        yield p, scene, selection, history
    finally:
        p._measure_timer.stop()
        p.deleteLater()
        QApplication.processEvents()


def test_properties_edit_a_hatch_in_place(panel):
    p, scene, sel, history = panel
    h = scene.add(HatchShape(_face(10.0), "lines", angle=0.0, spacing=1.0))
    sel.set([h.id])

    assert p.form.isRowVisible(p.hatch_pattern)
    assert "Area" in p.measure_label.text() or p._measure_timer.isActive()
    p.hatch_spacing.setValue(0.5)
    p.hatch_angle.setValue(30.0)

    shape = scene.get(h.id).shape
    assert (shape.pattern, shape.angle, shape.spacing) == ("lines", 30.0, 0.5)
    assert len(shape.pattern_segments()) > 10


def test_a_solid_hatch_offers_no_spacing(panel):
    p, scene, sel, _history = panel
    h = scene.add(HatchShape(_face(10.0), "lines", angle=0.0, spacing=1.0))
    sel.set([h.id])

    p.hatch_pattern.setCurrentIndex(p.hatch_pattern.findData("solid"))

    assert scene.get(h.id).shape.pattern == "solid"
    assert not p.form.isRowVisible(p.hatch_spacing)
    assert not p.form.isRowVisible(p.hatch_angle)


def test_a_hatch_edit_is_one_undo_step(panel):
    p, scene, sel, history = panel
    h = scene.add(HatchShape(_face(10.0), "lines", angle=0.0, spacing=1.0))
    sel.set([h.id])
    p.hatch_pattern.setCurrentIndex(p.hatch_pattern.findData("cross"))

    history.undo()

    assert scene.get(h.id).shape.pattern == "lines"


def test_the_hatch_rows_are_hidden_for_anything_else(panel):
    p, scene, sel, _history = panel
    box = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    sel.set([box.id])

    assert not p.form.isRowVisible(p.hatch_pattern)


def test_on_a_sheet_the_hatch_still_places_paper_corners():
    """Its points are paper millimetres: were the command to say "any", a
    click over a detail would step into the detail instead."""
    import serpentine3d.commands  # registers the commands  # noqa: F401
    from serpentine3d.commands.base import _REGISTRY
    assert _REGISTRY["hatch"].space == "paper"


def test_in_the_model_the_hatch_asks_for_no_point(env):
    """What lets it stay a paper command: it never asks the model for a
    point, whose meaning is what the space decides."""
    from serpentine3d.commands.base import PointReq
    scene, _sel, _hist, _ctx, proc = env
    outline = scene.add(_square(10.0))
    seen = []
    proc.run("hatch")
    seen.append(proc.request)
    _pick(proc, outline)
    while proc.request is not None:
        seen.append(proc.request)
        proc.provide_text("Lines" if len(seen) == 2 else "1")

    assert not any(isinstance(r, PointReq) for r in seen)
    assert any(o.kind == "hatch" for o in scene.all())
