"""A click selects the thing under the cursor, not one reaching past it.

Reported while clicking between two parts of a shaded assembly: every few
clicks a completely different part was selected, one nowhere near the
cursor. An object counted as hit when any of its edges passed within the
pick radius, seven pixels, and an edge hit was biased slightly nearer so
that a curve drawn on a surface stays clickable. On a solid that rule
reaches seven pixels past its own outline, so a solid whose edge ran near
the cursor and sat nearer the camera took clicks aimed at the surface
plainly visible behind it. On one sample assembly, 21% of the pixels over
a visible surface selected something else.

An object drawn with shaded faces is now picked by its faces. Its edges
are drawn on its own surface, so clicking one still selects it. Curves
have nothing but edges and are unaffected, and so is wireframe, where
there are no faces to hit.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.viewport import Viewport, ray_triangle_hits


@pytest.fixture(scope="session")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def pane(app):
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(900, 700)
    try:
        yield vp, scene
    finally:
        vp.deleteLater()
        QApplication.processEvents()


def _look_at_everything(vp, scene):
    vp.zoom_extents()
    QApplication.processEvents()


def _visible_surface(vp, scene, px, py):
    """The object whose surface a ray through this pixel reaches first."""
    eye = vp._eye()
    origin, direction = eye.ray_through(px, py, vp.width(), vp.height())
    best, who = np.inf, None
    for obj in scene.visible_objects():
        mesh = obj.mesh
        if not mesh.has_faces:
            continue
        tris = mesh.triangles
        t = ray_triangle_hits(origin, direction,
                              mesh.vertices[tris[:, 0]].astype(float),
                              mesh.vertices[tris[:, 1]].astype(float),
                              mesh.vertices[tris[:, 2]].astype(float))
        if len(t) and np.isfinite(t.min()) and t.min() < best:
            best, who = float(t.min()), obj.id
    return who


def _two_slabs(scene):
    """A near slab and, behind and beside it, a wider one. The near slab's
    edges run across the far slab on screen, which is the whole trouble."""
    near = scene.add(g.make_box((0, 0, 6), 10, 10, 1), name="Near")
    far = scene.add(g.make_box((-6, -6, 0), 22, 22, 1), name="Far")
    return near, far


def test_the_pick_agrees_with_what_is_drawn(pane):
    vp, scene = pane
    _two_slabs(scene)
    _look_at_everything(vp, scene)

    W, H = vp.width(), vp.height()
    checked = wrong = 0
    for px in range(40, W - 40, 9):
        for py in range(40, H - 40, 9):
            seen = _visible_surface(vp, scene, float(px), float(py))
            if seen is None:
                continue
            checked += 1
            if vp.pick_object(float(px), float(py)) != seen:
                wrong += 1
    assert checked > 200, "the view has to actually cover both slabs"
    assert wrong == 0, (
        f"{wrong} of {checked} pixels selected something other than the "
        "surface drawn there")


def test_clicking_a_solid_still_works_on_its_own_edges(pane):
    """The fix must not make the outline unclickable: an edge lies on the
    face it bounds, so aiming at one still lands on the object."""
    vp, scene = pane
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10), name="Box")
    _look_at_everything(vp, scene)

    eye = vp._eye()
    pts = box.mesh.edge_segments.reshape(-1, 3).astype(float)
    scr = eye.project(pts, vp.width(), vp.height())
    tried = hit = 0
    for x, y, z in scr[::7]:
        if z <= 0 or not (0 <= x < vp.width() and 0 <= y < vp.height()):
            continue
        tried += 1
        hit += vp.pick_object(float(x), float(y)) == box.id
    assert tried and hit == tried, f"only {hit} of {tried} edge points picked"


def test_a_curve_is_still_picked_by_the_line_itself(pane):
    """A curve has no faces at all, so the reach along its line is the only
    way to click it and must stay."""
    vp, scene = pane
    line = scene.add(g.make_line((0, 0, 0), (10, 10, 0)), name="Line")
    _look_at_everything(vp, scene)

    eye = vp._eye()
    mid = eye.project(np.array([[5.0, 5.0, 0.0]]), vp.width(), vp.height())[0]
    assert vp.pick_object(float(mid[0]), float(mid[1])) == line.id


def test_a_curve_lying_on_a_surface_still_wins(pane):
    """The bias that keeps a drawn-on curve reachable is not what broke."""
    vp, scene = pane
    scene.add(g.planar_face(g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)], closed=True)),
        name="Pad")
    curve = scene.add(g.make_line((1, 5, 0), (9, 5, 0)), name="On top")
    _look_at_everything(vp, scene)

    eye = vp._eye()
    mid = eye.project(np.array([[5.0, 5.0, 0.0]]), vp.width(), vp.height())[0]
    assert vp.pick_object(float(mid[0]), float(mid[1])) == curve.id


def test_wireframe_still_picks_a_solid_by_its_edges(pane):
    """With no faces drawn, edges are all there is to click."""
    vp, scene = pane
    box = scene.add(g.make_box((0, 0, 0), 10, 10, 10), name="Box")
    _look_at_everything(vp, scene)
    vp.display_mode = "wireframe"

    eye = vp._eye()
    pts = box.mesh.edge_segments.reshape(-1, 3).astype(float)
    scr = eye.project(pts, vp.width(), vp.height())
    tried = hit = 0
    for x, y, z in scr[::7]:
        if z <= 0 or not (0 <= x < vp.width() and 0 <= y < vp.height()):
            continue
        tried += 1
        hit += vp.pick_object(float(x), float(y)) == box.id
    assert tried and hit == tried, f"only {hit} of {tried} picked in wireframe"
