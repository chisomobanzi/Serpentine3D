"""Typing a measurement locks the live shape and click to that exact size.

Typed measures ('20', '20mm', '2cm', '2in', etc.) must keep the preview ghost,
rubber-band, and final clicked shape locked to the typed size even as the
cursor moves around the viewport, and radial commands must allow toggling
between Radius and Diameter.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent

from serpentine3d.commands.base import (
    CommandContext,
    CommandProcessor,
    PointReq,
)
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.set_view_layout("single")
    try:
        yield w
    finally:
        w.processor.cancel()
        w.mark_saved()
        w.close()


def _bbox_size(vp):
    tris, segs = vp._ghost_geometry()
    pts = [arr for arr in (tris, segs) if arr is not None and len(arr)]
    assert pts, "expected a ghost geometry"
    all_pts = np.concatenate(pts, axis=0)
    mn = all_pts.min(axis=0)
    mx = all_pts.max(axis=0)
    return tuple(round(float(b - a), 4) for a, b in zip(mn, mx))


def _obj_size(obj):
    lo, hi = obj.bbox()
    return tuple(round(float(b - a), 4) for a, b in zip(lo, hi))


def _type_text(window, text: str):
    window.command_line.input.setText(text)
    window._live_preview(text)


# ------------------------------------------- 1. Unit tests: resolve_typed_constraint

def test_resolve_typed_constraint_radial_and_units():
    from serpentine3d.commands.typed_measure import resolve_typed_constraint

    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene))
    center = (0.0, 0.0, 0.0)
    xdir = (1.0, 0.0, 0.0)
    req = PointReq("Radius", number_from=(center, xdir), rubber_from=center)

    tc = resolve_typed_constraint(req, "20", ctx, cursor=(30.0, 40.0, 0.0))
    assert tc is not None
    assert math.dist(center, tc.commit_value) == pytest.approx(20.0)
    assert math.dist(center, tc.rubber_point) == pytest.approx(20.0)
    # Direction follows cursor
    assert np.allclose(tc.commit_value, (12.0, 16.0, 0.0), atol=1e-6)

    # Unit suffixes in mm document
    tc_cm = resolve_typed_constraint(req, "2cm", ctx, cursor=(0.0, 50.0, 0.0))
    assert tc_cm is not None
    assert np.allclose(tc_cm.commit_value, (0.0, 20.0, 0.0), atol=1e-6)

    tc_in = resolve_typed_constraint(req, "2in", ctx, cursor=(100.0, 0.0, 0.0))
    assert tc_in is not None
    assert np.allclose(tc_in.commit_value, (50.8, 0.0, 0.0), atol=1e-5)

    # Diameter mode halves the typed value for radius
    req_d = PointReq(
        "Diameter",
        number_from=lambda v: (v / 2.0, 0.0, 0.0),
        rubber_from=center,
    )
    tc_d = resolve_typed_constraint(req_d, "20", ctx, cursor=(0.0, 50.0, 0.0))
    assert tc_d is not None
    assert np.allclose(tc_d.commit_value, (0.0, 10.0, 0.0), atol=1e-6)


def test_resolve_typed_constraint_directional_and_axial():
    from serpentine3d.commands.typed_measure import resolve_typed_constraint

    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene))
    base = (1.0, 2.0, 0.0)

    # Directional (no number_from, no axis_lock) even without viewport
    req_dir = PointReq("End of line", rubber_from=base)
    tc_dir = resolve_typed_constraint(req_dir, "20", ctx, cursor=(4.0, 6.0, 0.0))
    assert tc_dir is not None
    assert math.dist(base, tc_dir.commit_value) == pytest.approx(20.0)
    assert np.allclose(tc_dir.commit_value, (13.0, 18.0, 0.0), atol=1e-6)

    # Axial prompt ignores off-axis cursor direction
    up = (0.0, 0.0, 1.0)
    req_ax = PointReq(
        "Height", axis_lock=(base, up), number_from=(base, up), rubber_from=base
    )
    tc_ax = resolve_typed_constraint(req_ax, "20", ctx, cursor=(80.0, 90.0, 5.0))
    assert tc_ax is not None
    assert np.allclose(tc_ax.commit_value, (1.0, 2.0, 20.0), atol=1e-6)


def test_resolve_typed_constraint_ignores_keywords_and_handles_frame():
    from serpentine3d.commands.base import frame_sides
    from serpentine3d.commands.typed_measure import resolve_typed_constraint

    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene))
    c1 = (0.0, 0.0, 0.0)
    req_rad = PointReq(
        "Radius", number_from=(c1, (1.0, 0.0, 0.0)),
        rubber_from=c1, extra_options=("Diameter",),
    )
    assert resolve_typed_constraint(req_rad, "d", ctx) is None
    assert resolve_typed_constraint(req_rad, "Diameter", ctx) is None

    req_frame = PointReq(
        "Opposite corner, or length",
        rubber_from=c1,
        rubber_sides=frame_sides(c1, ctx.cplane),
        allow_number=True,
    )
    tc_frame = resolve_typed_constraint(req_frame, "20", ctx, cursor=(90.0, 50.0, 0.0))
    assert tc_frame is not None
    assert tc_frame.commit_value == pytest.approx(20.0)
    assert np.allclose(tc_frame.preview_value, (20.0, 50.0, 0.0), atol=1e-6)


# ------------------------------------------- 2. Radial commands Diameter <-> Radius

@pytest.mark.parametrize("cmd,extra_inputs,expected_span", [
    ("circle", [], (20.0, 20.0, 0.0)),
    ("sphere", [], (20.0, 20.0, 20.0)),
    ("cylinder", ["10"], (20.0, 20.0, 10.0)),
    ("cone", ["10"], (20.0, 20.0, 10.0)),
])
def test_radial_commands_toggle_diameter_and_radius(cmd, extra_inputs, expected_span):
    import serpentine3d.commands  # noqa: F401
    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene))
    proc = CommandProcessor(ctx)
    proc.run(cmd)
    proc.provide_text("0,0,0")
    proc.provide_text("Diameter")
    # Can toggle back to Radius and back to Diameter
    proc.provide_text("Radius")
    proc.provide_text("Diameter")
    proc.provide_text("20")
    for inp in extra_inputs:
        proc.provide_text(inp)
    assert len(scene.all()) == 1
    assert _obj_size(scene.all()[0]) == pytest.approx(expected_span, abs=1e-3)


def test_torus_helix_pipe_and_arc_support_diameter_toggle():
    import serpentine3d.commands  # noqa: F401
    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene))
    proc = CommandProcessor(ctx)

    # Torus: major diameter 20 (R=10), minor diameter 4 (r=2) -> span 24 x 24 x 4
    proc.run("torus")
    proc.provide_text("0,0,0")
    proc.provide_text("Diameter")
    proc.provide_text("20")
    proc.provide_text("Diameter")
    proc.provide_text("4")
    assert _obj_size(scene.all()[-1]) == pytest.approx((24.0, 24.0, 4.0), abs=1e-2)

    # Arc (Center): diameter 20 (r=10), 180 degrees -> span 20 x 10 x 0
    proc.run("arc")
    proc.provide_text("Center")
    proc.provide_text("0,0,0")
    proc.provide_text("Diameter")
    proc.provide_text("20")
    proc.provide_text("180")
    assert _obj_size(scene.all()[-1]) == pytest.approx((20.0, 10.0, 0.0), abs=1e-2)

    # Helix: diameter 20 (r=10)
    proc.run("helix")
    proc.provide_text("0,0,0")
    proc.provide_text("Diameter")
    proc.provide_text("20")
    proc.provide_text("5")
    proc.provide_text("2")
    assert _obj_size(scene.all()[-1])[:2] == pytest.approx((20.0, 20.0), abs=0.2)

    # Pipe on a straight line: diameter 6 (r=3) -> thickness 6
    line_obj = scene.add(g.make_line((0.0, 0.0, 0.0), (20.0, 0.0, 0.0)))
    proc.run("pipe")
    proc.provide([line_obj])
    proc.provide_text("Diameter")
    proc.provide_text("6")
    assert _obj_size(scene.all()[-1])[1:] == pytest.approx((6.0, 6.0), abs=1e-2)


# ------------------------------------------- 3. Live preview & mouse invariance

def test_circle_radius_and_diameter_stay_locked_on_mouse_move(window):
    window.run_command("circle")
    window._on_point_picked((0.0, 0.0, 0.0))

    _type_text(window, "20")
    window._on_mouse_world((85.0, 40.0, 0.0))

    assert window.viewport._ghost is not None
    assert _bbox_size(window.viewport)[:2] == pytest.approx((40.0, 40.0), abs=1e-2)
    span = window.viewport._draw_span
    assert span is not None
    assert float(np.linalg.norm(span[1] - span[0])) == pytest.approx(20.0, abs=1e-3)

    # Switch to Diameter while 20 is typed (or re-type 20)
    window.processor.provide_text("Diameter")
    _type_text(window, "20")
    window._on_mouse_world((85.0, 40.0, 0.0))
    assert _bbox_size(window.viewport)[:2] == pytest.approx((20.0, 20.0), abs=1e-2)
    span = window.viewport._draw_span
    assert float(np.linalg.norm(span[1] - span[0])) == pytest.approx(10.0, abs=1e-3)

    # Switching back to Radius with 20 still in the input box immediately updates to r=20
    window.command_line.keywordClicked.emit("Radius")
    assert _bbox_size(window.viewport)[:2] == pytest.approx((40.0, 40.0), abs=1e-2)


def test_line_and_rectangle_stay_locked_to_typed_measure_on_mouse_move(window):
    # Line
    window.run_command("line")
    window._on_point_picked((0.0, 0.0, 0.0))
    _type_text(window, "20")
    window._on_mouse_world((60.0, 80.0, 0.0))
    span = window.viewport._draw_span
    assert span is not None
    assert np.allclose(span[1], (12.0, 16.0, 0.0), atol=1e-4)
    window.processor.cancel()

    # Rectangle: first side locked to 20, width tracks cursor (50)
    window.run_command("rectangle")
    window._on_point_picked((0.0, 0.0, 0.0))
    _type_text(window, "20")
    window._on_mouse_world((90.0, 50.0, 0.0))
    assert window.viewport._ghost is not None
    assert _bbox_size(window.viewport)[:2] == pytest.approx((20.0, 50.0), abs=1e-3)


# ------------------------------------------- 4. Viewport click commits typed measure

def test_viewport_click_commits_typed_measure_for_circle_and_line(window):
    # Circle Radius=20 committed by clicking far away at (85, 40, 0)
    window.run_command("circle")
    window._on_point_picked((0.0, 0.0, 0.0))
    _type_text(window, "20")
    window._on_point_picked((85.0, 40.0, 0.0))
    assert window.command_line.input.text() == ""
    assert _obj_size(window.scene.all()[-1])[:2] == pytest.approx((40.0, 40.0), abs=1e-2)

    # Circle Diameter=20 committed by clicking far away at (85, 40, 0)
    window.run_command("circle")
    window._on_point_picked((0.0, 0.0, 0.0))
    window.processor.provide_text("Diameter")
    _type_text(window, "20")
    window._on_point_picked((85.0, 40.0, 0.0))
    assert _obj_size(window.scene.all()[-1])[:2] == pytest.approx((20.0, 20.0), abs=1e-2)

    # Line length=20 committed by clicking at (60, 80, 0) -> end at (12, 16, 0)
    window.run_command("line")
    window._on_point_picked((0.0, 0.0, 0.0))
    _type_text(window, "20")
    window._on_point_picked((60.0, 80.0, 0.0))
    assert _obj_size(window.scene.all()[-1])[:2] == pytest.approx((12.0, 16.0), abs=1e-3)

    # Rectangle length=20 committed by clicking, then width=30 committed by clicking
    window.run_command("rectangle")
    window._on_point_picked((0.0, 0.0, 0.0))
    _type_text(window, "20")
    window._on_point_picked((90.0, 50.0, 0.0))
    _type_text(window, "30")
    window._on_point_picked((20.0, 95.0, 0.0))
    assert _obj_size(window.scene.all()[-1])[:2] == pytest.approx((20.0, 30.0), abs=1e-3)


# ------------------------------------------- 5. Units, viewport focus keystroke & clearing

@pytest.mark.parametrize("doc_units,typed,expected_diam", [
    ("mm", "2cm", 40.0),
    ("mm", "2in", 101.6),
    ("in", "20", 40.0),
    ("cm", "20", 40.0),
])
def test_typed_measure_conforms_to_document_and_suffix_units(window, doc_units, typed, expected_diam):
    window.scene.units = doc_units
    window.run_command("circle")
    window._on_point_picked((0.0, 0.0, 0.0))
    _type_text(window, typed)
    window._on_mouse_world((300.0, 400.0, 0.0))
    assert _bbox_size(window.viewport)[:2] == pytest.approx(
        (expected_diam, expected_diam), abs=1e-2
    )
    window._on_point_picked((300.0, 400.0, 0.0))
    assert _obj_size(window.scene.all()[-1])[:2] == pytest.approx(
        (expected_diam, expected_diam), abs=1e-2
    )


def test_first_keystroke_from_viewport_focus_and_clearing_restores_cursor(window):
    window.run_command("circle")
    window._on_point_picked((0.0, 0.0, 0.0))
    window._on_mouse_world((50.0, 0.0, 0.0))
    assert _bbox_size(window.viewport)[:2] == pytest.approx((100.0, 100.0), abs=1e-2)

    # First digit pressed while viewport (not command_line.input) has focus
    window.viewport.setFocus()
    ev = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_2, Qt.KeyboardModifier.NoModifier, "2")
    window.keyPressEvent(ev)
    assert window.command_line.input.text() == "2"
    assert _bbox_size(window.viewport)[:2] == pytest.approx((4.0, 4.0), abs=1e-2)

    # Clearing the input box restores live cursor preview
    _type_text(window, "")
    assert _bbox_size(window.viewport)[:2] == pytest.approx((100.0, 100.0), abs=1e-2)
