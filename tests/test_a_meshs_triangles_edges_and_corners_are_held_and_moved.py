"""A mesh's parts are held as a solid's are: Ctrl+Shift and a click holds the
triangle or the edge it lands on, PointsOn shows its corners, and whatever is
held moves, turns and scales with the gumball or a command, the rest of the
mesh staying put and in one piece.

A mesh used to answer every Ctrl+Shift click with its one and only "face",
and the gumball then asked OpenCascade for that face's outline, which a mesh
has none of: the error out of the mouse press took the app down."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.mesh import MeshShape, mesh_to_display
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.gumball import CONE1, SHAFT0
from serpentine3d.ui.viewport import Viewport

PART = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier
NONE = Qt.KeyboardModifier.NoModifier


def _sheet():
    """Two triangles side by side, a square 10 across, its corners shared;
    and a third standing up off its right edge, so that edge is a crease."""
    points = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0), (10, 5, 8)]
    return MeshShape(np.array(points, float),
                     [[0, 1, 2], [0, 2, 3], [1, 4, 2]])


def _unwelded():
    """The same two flat triangles stored with corners of their own, as
    Rhino stores a mesh: six corners standing at four places."""
    points = [(0, 0, 0), (10, 0, 0), (10, 10, 0),
              (0, 0, 0), (10, 10, 0), (0, 10, 0)]
    return MeshShape(np.array(points, float), [[0, 1, 2], [3, 4, 5]])


# -- the mesh's own parts ---------------------------------------------------------

def test_a_triangle_is_held_by_its_three_points_an_edge_by_its_two():
    mesh = _unwelded()
    points = mesh.points()
    assert len(points) == 4                       # six corners, four places
    face = mesh.part_points("face", 1)
    assert sorted(map(tuple, points[face])) == [(0, 0, 0), (0, 10, 0),
                                                (10, 10, 0)]
    edges = mesh.edge_pairs()[1]
    for index in range(len(edges)):
        assert len(mesh.part_points("edge", index)) == 2
    with pytest.raises(IndexError):
        mesh.part_points("cv", 9)


def test_moving_a_point_takes_every_corner_standing_on_it():
    mesh = _unwelded()
    corner = [i for i, p in enumerate(mesh.points())
              if tuple(p) == (10, 10, 0)][0]
    moved = mesh.points_moved([corner], lambda p: p + (0, 0, 5))
    # both triangles' copies went up, so the mesh did not tear
    lifted = [tuple(v) for v in moved.vertices if v[2] == 5]
    assert lifted == [(10, 10, 5), (10, 10, 5)]
    assert np.array_equal(moved.triangles, mesh.triangles)


def test_the_display_numbers_each_triangle_and_each_drawn_edge():
    mesh = _sheet()
    shown = mesh_to_display(mesh)
    assert list(shown.face_of_triangle) == [0, 1, 2]
    assert list(shown.edge_of_segment) == list(range(len(shown.edge_segments)))
    points, pairs = mesh.edge_pairs()
    assert np.allclose(shown.edge_segments, points[pairs])


def test_a_mesh_has_its_corners_for_control_points():
    mesh = _sheet()
    assert len(g.get_control_points(mesh)) == 5
    moved = g.move_control_point(mesh, 4, (10, 5, 20))
    assert (10, 5, 20) in [tuple(v) for v in moved.vertices]
    assert g.faces_of(mesh) == [] and g.edges_of(mesh) == []


# -- picked with Ctrl+Shift, in a pane -----------------------------------------------

@pytest.fixture
def pane():
    QApplication.instance() or QApplication([])
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    vp.set_view("top")
    vp.grid_snap = False
    obj = scene.add(_sheet())
    vp.camera.target = np.array([5.0, 5.0, 0.0])
    vp.camera.distance = 40.0
    return vp, obj


def _screen(vp, pt):
    scr = vp.camera.project(np.asarray([pt], float), vp.width(), vp.height())
    return float(scr[0][0]), float(scr[0][1])


def _click(vp, x, y, mods=NONE):
    for kind, held in ((QEvent.Type.MouseButtonPress,
                        Qt.MouseButton.LeftButton),
                       (QEvent.Type.MouseButtonRelease,
                        Qt.MouseButton.NoButton)):
        event = QMouseEvent(kind, QPointF(x, y), QPointF(x, y),
                            Qt.MouseButton.LeftButton, held, mods)
        (vp.mousePressEvent if kind == QEvent.Type.MouseButtonPress
         else vp.mouseReleaseEvent)(event)


def test_ctrl_shift_holds_the_triangle_it_lands_on(pane):
    vp, obj = pane
    _click(vp, *_screen(vp, (2.5, 7.5, 0)), PART)      # in the second
    assert vp.selection.subobjects == [(obj.id, "face", 1)]
    _click(vp, *_screen(vp, (7.5, 2.5, 0)), PART)      # and the first too
    assert sorted(vp.selection.subobjects) == [(obj.id, "face", 0),
                                               (obj.id, "face", 1)]


def test_ctrl_shift_holds_a_drawn_edge(pane):
    vp, obj = pane
    _click(vp, *_screen(vp, (5, 0, 0)), PART)          # the bottom border
    [(oid, kind, index)] = vp.selection.subobjects
    assert (oid, kind) == (obj.id, "edge")
    ends = obj.shape.points()[obj.shape.part_points("edge", index)]
    assert sorted(map(tuple, ends)) == [(0, 0, 0), (10, 0, 0)]


# -- moved by the gumball ---------------------------------------------------------------

def test_the_gumball_stands_on_a_held_triangle_and_moves_only_it(pane):
    vp, obj = pane
    _click(vp, *_screen(vp, (2.5, 7.5, 0)), PART)
    gb = vp.gumball
    assert gb.active()
    anchor, axes = gb.anchor_and_axes()
    assert np.allclose(anchor, [10 / 3, 20 / 3, 0])  # its three corners
    at = anchor + axes[0] * (SHAFT0 + CONE1) / 2 * gb._size_world(anchor)
    px, py = _screen(vp, at)
    assert gb.begin_drag(("move", 0), px, py, NONE)
    to = _screen(vp, at + np.array([3.0, 0, 0]))
    gb.drag_to(*to, NONE)
    gb.end_drag()
    moved = [tuple(np.round(p, 6)) for p in vp.scene.get(obj.id).shape.points()]
    assert (3, 0, 0) in moved and (3, 10, 0) in moved and (13, 10, 0) in moved
    assert (10, 0, 0) in moved                   # the first triangle's own
    assert vp.selection.subobjects == [(obj.id, "face", 1)]   # still held


# -- moved by a command -------------------------------------------------------------------

@pytest.fixture
def env():
    QApplication.instance() or QApplication([])
    scene = Scene()
    sel = SelectionManager(scene)
    ctx = CommandContext(scene, sel, History(scene))
    return scene, sel, CommandProcessor(ctx)


def test_move_moves_the_held_triangle_and_keeps_holding_it(env):
    scene, sel, proc = env
    obj = scene.add(_sheet())
    sel.set_subobjects([(obj.id, "face", 0)])
    proc.run("move")
    proc.provide_text("0,0,0")
    proc.provide_text("0,0,5")
    assert not proc.busy
    points = {tuple(np.round(p, 6)) for p in scene.get(obj.id).shape.points()}
    assert {(0, 0, 5), (10, 0, 5), (10, 10, 5)} <= points
    assert (0, 10, 0) in points and (10, 5, 8) in points
    assert sel.subobjects == [(obj.id, "face", 0)]


def test_a_held_edge_and_triangle_sharing_points_move_them_once(env):
    scene, sel, proc = env
    obj = scene.add(_sheet())
    mesh = obj.shape
    # the edge between the two flat triangles' far corners, if drawn, or
    # any edge of the first triangle
    edges = mesh.edge_pairs()[1]
    shared = next(i for i, pair in enumerate(edges)
                  if set(pair) <= set(mesh.part_points("face", 0)))
    sel.set_subobjects([(obj.id, "face", 0), (obj.id, "edge", shared)])
    proc.run("move")
    proc.provide_text("0,0,0")
    proc.provide_text("0,0,5")
    heights = sorted({round(float(p[2]), 6)
                      for p in scene.get(obj.id).shape.points()})
    assert 10 not in heights                     # nothing went up twice
    assert 5 in heights


def test_scale_scales_the_held_triangle_about_the_point_given(env):
    scene, sel, proc = env
    obj = scene.add(_sheet())
    sel.set_subobjects([(obj.id, "face", 1)])
    proc.run("scale")
    proc.provide_text("0,0,0")
    proc.provide_text("2")
    assert not proc.busy
    points = {tuple(np.round(p, 6)) for p in scene.get(obj.id).shape.points()}
    assert (0, 20, 0) in points and (20, 20, 0) in points
    assert (10, 0, 0) in points                  # not held, not scaled


def test_points_on_shows_a_meshs_corners(env):
    scene, sel, proc = env
    obj = scene.add(_sheet())
    vp = Viewport(scene, sel)
    proc.ctx.viewport = vp
    sel.set([obj.id])
    proc.run("pointson")
    assert obj.id in vp.cv_enabled
    assert len(vp._cv_points(scene.get(obj.id))) == 5


# -- faceted: flat triangles, every edge drawn and offered -------------------------

def _faceted(mesh):
    return MeshShape(mesh.vertices, mesh.triangles, faceted=True)


def test_a_faceted_mesh_draws_and_offers_every_edge():
    flat = _faceted(_unwelded())
    smooth = _unwelded()
    assert len(smooth.edge_pairs()[1]) == 4      # the border only
    assert len(flat.edge_pairs()[1]) == 5        # and the diagonal
    shown = mesh_to_display(flat)
    assert len(shown.edge_segments) == 5
    assert list(shown.edge_of_segment) == [0, 1, 2, 3, 4]
    assert list(shown.face_of_triangle) == [0, 1]
    # flat: each triangle on corners of its own, with its own normal
    assert len(shown.vertices) == 6
    assert np.allclose(shown.normals, [0, 0, 1])


def test_a_faceted_mesh_stays_faceted_moved_copied_saved_and_reshaped():
    from serpentine3d.fileio.native import _mesh_from_json, _mesh_to_json
    flat = _faceted(_sheet())
    assert flat.translated((1, 0, 0)).faceted and flat.copy().faceted
    assert flat.transformed(np.eye(4)).faceted
    assert flat.points_moved([0], lambda p: p + 1).faceted
    assert _mesh_from_json(_mesh_to_json(flat)).faceted
    assert not _mesh_from_json(_mesh_to_json(_sheet())).faceted


def test_ctrl_shift_holds_an_inner_edge_of_a_faceted_mesh(pane):
    vp, obj = pane
    vp.scene.replace_shape(obj.id, _faceted(obj.shape))
    _click(vp, *_screen(vp, (5, 5, 0)), PART)         # the diagonal
    [(oid, kind, index)] = vp.selection.subobjects
    assert kind == "edge"
    shape = vp.scene.get(oid).shape
    ends = shape.points()[shape.part_points("edge", index)]
    assert sorted(map(tuple, ends)) == [(0, 0, 0), (10, 10, 0)]


def test_properties_switch_a_mesh_between_faceted_and_smooth(tmp_path,
                                                             monkeypatch):
    from serpentine3d.app import MainWindow
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        obj = win.scene.add(_sheet())
        win.selection.set([obj.id])
        QApplication.processEvents()
        box = win.properties.faceted_box
        assert not box.isChecked()
        box.setChecked(True)
        assert win.scene.get(obj.id).shape.faceted
        win.history.undo()
        assert not win.scene.get(obj.id).shape.faceted
        box_row_shown = win.properties.form.isRowVisible(box)
        assert box_row_shown
        line = win.scene.add(g.make_line((0, 0, 0), (1, 0, 0)))
        win.selection.set([line.id])
        QApplication.processEvents()
        assert not win.properties.form.isRowVisible(box)
    finally:
        win.processor.cancel()
        win.mark_saved()
        win.close()


# -- a preview while it moves, and snapping to corners ------------------------------

def test_a_mesh_snaps_at_its_corners_and_its_edges_middles():
    from serpentine3d.core.snaps import _static_snap_points
    points = _static_snap_points(_sheet())
    ends = {tuple(np.round(p, 6)) for p, kind in points if kind == "end"}
    mids = {tuple(np.round(p, 6)) for p, kind in points if kind == "mid"}
    assert ends == {(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0),
                    (10, 5, 8)}
    assert (5, 0, 0) in mids                     # the bottom border's middle


def test_move_shows_the_held_triangle_moving_before_it_is_placed(env):
    from serpentine3d.commands.transform import _preview_of
    scene, sel, proc = env
    obj = scene.add(_sheet())
    sel.set_subobjects([(obj.id, "face", 0)])
    held = proc.ctx.held_parts()
    ghost = _preview_of(proc.ctx, held, [], lambda s: g.translate(
        s, (0, 0, 5)))
    assert isinstance(ghost, MeshShape)
    tops = {tuple(np.round(p, 6)) for p in ghost.points() if p[2] == 5}
    assert tops == {(0, 0, 5), (10, 0, 5), (10, 10, 5)}
    # and the scene itself is not touched by the preview
    assert max(p[2] for p in scene.get(obj.id).shape.points()) == 8


def test_move_snaps_a_held_corner_onto_another(env):
    scene, sel, proc = env
    obj = scene.add(_sheet())
    vp = Viewport(scene, sel)
    vp.resize(800, 600)
    vp.set_view("top")
    vp.camera.target = np.array([5.0, 5.0, 0.0])
    vp.camera.distance = 40.0
    sel.set_subobjects([(obj.id, "cv", 0)])        # the corner at the origin
    # the snap the pane finds over the corner at 10, 10 is that corner
    px, py = _screen(vp, (10.2, 9.8, 0))
    snap = vp.snaps.find(vp._eye(), px, py, vp.width(), vp.height())
    assert snap is not None and snap[1] == "end"
    assert np.allclose(snap[0], (10, 10, 0))


def test_the_gumball_snaps_a_dragged_triangle_to_a_corner(pane):
    vp, obj = pane
    _click(vp, *_screen(vp, (2.5, 7.5, 0)), PART)  # the second triangle
    gb = vp.gumball
    anchor, axes = gb.anchor_and_axes()
    at = anchor + axes[0] * (SHAFT0 + CONE1) / 2 * gb._size_world(anchor)
    assert gb.begin_drag(("move", 0), *_screen(vp, at), NONE)
    # drag along X to just short of the far corner's X, 10: it snaps there
    gb.drag_to(*_screen(vp, (10.3, 5, 8)), NONE)
    assert vp._active_snap is not None
    assert np.allclose(vp._active_snap[0], (10, 5, 8))
    gb.end_drag()
    assert vp._active_snap is None
    xs = sorted({round(float(p[0]), 6)
                 for p in vp.scene.get(obj.id).shape.points()})
    # its centre moved along X onto 10: by 10 - 10/3
    assert any(abs(x - (10 + 10 - 10 / 3)) < 1e-6 for x in xs)


def test_a_dragged_corner_does_not_snap_to_itself(pane):
    vp, obj = pane
    vp.cv_enabled.add(obj.id)
    vp.selection.set_subobjects([(obj.id, "cv", 0)])
    gb = vp.gumball
    assert gb.begin_drag(("move", 0), *_screen(vp, (2, 0, 0)), NONE)
    ids, extra = gb.drag["snap"]
    assert obj.id in ids
    start = tuple(np.round(obj.shape.points()[0], 6))
    assert start not in {tuple(np.round(p, 6)) for p, _k in extra}
    gb.cancel_drag()
