"""Trim takes the part you click, in one click (#31).

Reported: after picking the cutters, "Select object to trim" is an extra,
unnecessary click. Trim asked three things: the cutters, the object, and
then which piece of it to take away. In Rhino the last two are one click:
where you click says both which object and which part of it goes.

That needs to know where the click landed, which the selection never
recorded, only what it hit. A click in a viewport now carries the point on
the object nearest to it, and trim takes the piece that point is on at
once, then asks again for the next, until Enter.

A pick with no position, typed, scripted over RPC or chosen from the list
a held click offers, has nothing to say which part is meant, so it falls
back to asking which piece, as before.
"""

from __future__ import annotations

import pytest

import serpentine3d.commands  # registers the commands  # noqa: F401
from serpentine3d.commands.base import (CommandContext, CommandProcessor,
                                        SelectReq)
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


@pytest.fixture
def env():
    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene))
    said: list[str] = []
    ctx.add_echo_listener(said.append)
    return scene, ctx, CommandProcessor(ctx), said


def _line_and_cutter(scene):
    line = scene.add(g.make_line((0, 0, 0), (10, 0, 0)), name="Target")
    cutter = scene.add(g.make_line((4, -5, 0), (4, 5, 0)), name="Cutter")
    return line, cutter


def _start(proc, *cutters):
    proc.run("trim")
    for c in cutters:
        proc.click_object(c.id)
    proc.finish_selection()


def _curves(scene, but):
    ids = {o.id for o in but}
    return [o for o in scene.all() if o.id not in ids]


# --- the reported case ------------------------------------------------------

def test_after_the_cutters_it_asks_for_the_part_to_trim_away(env):
    scene, _ctx, proc, _said = env
    _line, cutter = _line_and_cutter(scene)

    _start(proc, cutter)

    assert isinstance(proc.request, SelectReq)
    assert "part to trim away" in proc.request.prompt.lower()
    assert "object to trim" not in proc.request.prompt.lower()


def test_one_click_takes_the_part_it_lands_on(env):
    scene, _ctx, proc, _said = env
    line, cutter = _line_and_cutter(scene)
    _start(proc, cutter)

    proc.click_object(line.id, at=(8.0, 0.0, 0.0))        # right of the cut

    (kept,) = _curves(scene, [cutter])
    assert g.curve_length(kept.shape) == pytest.approx(4.0, abs=1e-6)
    assert g.bbox(kept.shape)[1][0] == pytest.approx(4.0, abs=1e-6), \
        "the left part stays, the clicked right part went"


def test_a_click_on_the_other_side_takes_the_other_part(env):
    scene, _ctx, proc, _said = env
    line, cutter = _line_and_cutter(scene)
    _start(proc, cutter)

    proc.click_object(line.id, at=(1.0, 0.0, 0.0))

    (kept,) = _curves(scene, [cutter])
    assert g.curve_length(kept.shape) == pytest.approx(6.0, abs=1e-6)


def test_it_keeps_asking_until_enter(env):
    """As Rhino does: the same cutters, as many clicks as you like."""
    scene, _ctx, proc, _said = env
    a = scene.add(g.make_line((0, 0, 0), (10, 0, 0)), name="A")
    b = scene.add(g.make_line((0, 2, 0), (10, 2, 0)), name="B")
    cutter = scene.add(g.make_line((4, -5, 0), (4, 5, 0)), name="Cutter")
    _start(proc, cutter)

    proc.click_object(a.id, at=(8.0, 0.0, 0.0))
    assert proc.busy, "still asking for the next part"
    proc.click_object(b.id, at=(8.0, 2.0, 0.0))
    proc.finish_selection()

    assert not proc.busy
    kept = _curves(scene, [cutter])
    assert sorted(round(g.curve_length(o.shape), 6) for o in kept) == [4.0, 4.0]


def test_what_is_left_keeps_its_name_and_layer(env):
    scene, _ctx, proc, _said = env
    line, cutter = _line_and_cutter(scene)
    _start(proc, cutter)

    proc.click_object(line.id, at=(8.0, 0.0, 0.0))

    (kept,) = _curves(scene, [cutter])
    assert kept.name == "Target" and kept.layer_id == line.layer_id


def test_a_part_the_cutters_do_not_cross_says_so_and_carries_on(env):
    scene, _ctx, proc, said = env
    _line, cutter = _line_and_cutter(scene)
    far = scene.add(g.make_line((0, 50, 0), (10, 50, 0)), name="Far")
    _start(proc, cutter)

    proc.click_object(far.id, at=(5.0, 50.0, 0.0))

    assert scene.get(far.id) is not None
    assert any("nothing to trim" in m for m in said), said
    assert proc.busy


def test_the_whole_trim_is_one_undo_step(env):
    scene, ctx, proc, _said = env
    a = scene.add(g.make_line((0, 0, 0), (10, 0, 0)), name="A")
    b = scene.add(g.make_line((0, 2, 0), (10, 2, 0)), name="B")
    cutter = scene.add(g.make_line((4, -5, 0), (4, 5, 0)), name="Cutter")
    _start(proc, cutter)
    proc.click_object(a.id, at=(8.0, 0.0, 0.0))
    proc.click_object(b.id, at=(8.0, 2.0, 0.0))
    proc.finish_selection()

    ctx.history.undo()

    lengths = sorted(round(g.curve_length(o.shape), 6)
                     for o in _curves(scene, [cutter]))
    assert lengths == [10.0, 10.0]


def test_a_surface_loses_the_part_clicked(env):
    scene, _ctx, proc, _said = env
    square = scene.add(g.planar_face(g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], closed=True)),
        name="Sheet")
    cutter = scene.add(g.make_line((3, -5, 0), (3, 15, 0)), name="Cutter")
    _start(proc, cutter)

    proc.click_object(square.id, at=(1.0, 5.0, 0.0))

    (kept,) = _curves(scene, [cutter])
    assert g.surface_area(kept.shape) == pytest.approx(70.0, rel=1e-6)


# --- no position: the old way, unchanged ------------------------------------

def test_a_pick_with_no_position_still_asks_which_piece(env):
    scene, _ctx, proc, _said = env
    line, cutter = _line_and_cutter(scene)
    _start(proc, cutter)

    proc.click_object(line.id)

    assert isinstance(proc.request, SelectReq)
    assert "piece" in proc.request.prompt.lower()
    pieces = _curves(scene, [cutter])
    assert len(pieces) == 2
    right = next(p for p in pieces if g.bbox(p.shape)[0][0] > 3.9)
    proc.click_object(right.id)
    proc.finish_selection()

    assert not proc.busy
    (kept,) = _curves(scene, [cutter])
    assert g.curve_length(kept.shape) == pytest.approx(4.0, abs=1e-6)


# --- the viewport says where the click landed -------------------------------

def test_the_viewport_reports_the_point_under_a_click():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import numpy as np
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    view = Viewport(scene, SelectionManager(scene))
    view.resize(800, 600)
    view.camera.set_standard_view("top")
    line = scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    view.zoom_extents()
    px, py, _z = view.camera.project(np.array([[8.0, 0.0, 0.0]]), 800, 600)[0]

    at = view.point_on(line.id, float(px), float(py) + 2.0)   # a near miss

    assert at is not None
    assert at == pytest.approx((8.0, 0.0, 0.0), abs=0.2)
    view.deleteLater()


def test_a_click_in_the_window_trims_in_one_go(tmp_path, monkeypatch):
    """The path a mouse click takes: pane, window, processor, command."""
    import numpy as np
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("SERP3D_AUTOSAVE_DIR", str(tmp_path / "as"))
    QApplication.instance() or QApplication([])
    from serpentine3d.app import MainWindow
    w = MainWindow()
    try:
        pane = w.viewport
        pane.resize(640, 480)
        pane.camera.set_standard_view("top")
        line = w.scene.add(g.make_line((0, 0, 0), (10, 0, 0)), name="Target")
        cutter = w.scene.add(g.make_line((4, -5, 0), (4, 5, 0)), name="Cutter")
        pane.zoom_extents()
        w.processor.run("trim")
        w.processor.click_object(cutter.id)
        w.processor.finish_selection()
        px, py, _z = pane.camera.project(np.array([[8.0, 0.0, 0.0]]),
                                         pane.width(), pane.height())[0]
        pane.last_click_px = (float(px), float(py))

        w._on_object_clicked(line.id, Qt.KeyboardModifier.NoModifier, pane)

        kept = [o for o in w.scene.all() if o.id != cutter.id]
        assert len(kept) == 1
        assert g.curve_length(kept[0].shape) == pytest.approx(4.0, abs=1e-6)
    finally:
        w.processor.cancel()
        w.mark_saved()
        w.close()


def test_a_pick_with_no_position_that_nothing_crosses_ends_as_before(env):
    """Scripted callers were promised trim ends there; only a real click,
    which can try again, carries on."""
    scene, _ctx, proc, said = env
    _line, cutter = _line_and_cutter(scene)
    far = scene.add(g.make_line((0, 50, 0), (10, 50, 0)), name="Far")
    _start(proc, cutter)

    proc.click_object(far.id)

    assert not proc.busy
    assert any("nothing to trim" in m for m in said), said


def test_on_a_solid_the_point_is_on_the_face_you_see():
    """A ray through a box crosses it twice; the click means the near side."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import numpy as np
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    view = Viewport(scene, SelectionManager(scene))
    view.resize(800, 600)
    view.camera.set_standard_view("top")
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    view.zoom_extents()
    px, py, _z = view.camera.project(np.array([[5.0, 5.0, 10.0]]), 800, 600)[0]

    at = view.point_on(box.id, float(px), float(py))

    assert at is not None
    assert at[2] == pytest.approx(10.0, abs=1e-6), "the top, not the bottom"
    view.deleteLater()
