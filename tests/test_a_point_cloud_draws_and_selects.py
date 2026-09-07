"""A million scanned points draw, frame, select and thin without a fuss.

A scan is shown as points coloured by the scanner, one buffer on the card
per cloud, culled by its box and anchored far from home like a mesh so it
does not swim. Zoom Extents has to reach it, technical mode has to leave
it alone rather than hand it to the hidden-line kernel, a click on it has
to pick it, and when several scans add up to more points than a frame
should hold, the finer levels go first and the status line says so.

GL under the offscreen platform gives a context but no framebuffer, so the
draw tests paint through paintGL directly and ask whether the pane
survived; where even that is missing they are skipped, and the pure
helpers underneath (the budget, the vertex packing) are tested on their
own.
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.pointcloud import PointCloudShape, cloud_to_display
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vpmod
from serpentine3d.ui.viewport import Viewport

FAR = np.array([300000.0, 200000.0, 0.0], np.float32)


def _cloud(n: int, seed: int = 3, levels: bool = True,
           offset=(0.0, 0.0, 0.0)) -> PointCloudShape:
    rng = np.random.default_rng(seed)
    xyz = rng.random((n, 3), dtype=np.float32) * np.float32([4, 3, 2.5])
    xyz += np.asarray(offset, np.float32)
    rgb = (rng.random((n, 3)) * 255).astype(np.uint8)
    level = rng.integers(0, 3, n).astype(np.uint8) if levels else None
    return PointCloudShape(xyz, rgb, None, level)


def _viewport(scene):
    QApplication.instance() or QApplication([])
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    return vp


@pytest.fixture
def painting():
    """A shown viewport with a live context, or a skip where there is none.

    Closed and deleted at the end of the test, with the event loop run so
    the context really goes: a second widget built while the first one's
    context is still being torn down finds no current context in its
    initializeGL and never draws again.
    """
    made = []

    def make(scene):
        vp = _viewport(scene)
        vp.show()
        QApplication.processEvents()
        made.append(vp)
        if not vp.isValid() or not vp._point_prog:
            pytest.skip("no OpenGL context under this platform")
        return vp

    yield make
    for vp in made:
        vp.close()
        vp.deleteLater()
    QApplication.processEvents()


# --- what does not need a card ---------------------------------------------

def test_zoom_extents_includes_a_point_cloud():
    scene = Scene()
    scene.add(_cloud(2000, offset=(50.0, 60.0, 70.0)), name="Scan")
    vp = _viewport(scene)
    vp.zoom_extents()
    assert np.allclose(vp.camera.target, [52, 61.5, 71.25], atol=0.2)
    assert vp.camera.distance > 4.0


def test_the_display_of_a_cloud_is_its_points_ordered_coarse_to_fine():
    cloud = _cloud(600)
    dm = cloud_to_display(cloud)
    assert dm.is_cloud and not dm.has_faces
    assert len(dm.vertices) == 600
    n0, n01, n012 = dm.cloud_levels
    assert n012 == 600
    assert n0 == int((cloud.level == 0).sum())
    assert n01 == int((cloud.level <= 1).sum())
    # the first n0 rows are level-0 points and carry their own colours
    lvl0 = cloud.xyz[cloud.level == 0]
    assert np.array_equal(np.sort(dm.vertices[:n0], axis=0),
                          np.sort(lvl0, axis=0))
    assert dm.cloud_colors is not None and len(dm.cloud_colors) == 600
    assert dm.bounds() is not None


def test_the_uploaded_points_are_sixteen_bytes_each_with_colour_as_bytes():
    cloud = _cloud(10)
    dm = cloud_to_display(cloud)
    rows = vpmod.cloud_vertex_data(dm, None)
    assert rows.shape == (10, vpmod.CLOUD_STRIDE)
    xyz = rows[:, :12].copy().view(np.float32).reshape(-1, 3)
    assert np.array_equal(xyz, dm.vertices)
    assert np.array_equal(rows[:, 12:15], dm.cloud_colors)


def test_a_cloud_with_no_colour_uploads_white_and_takes_the_layer_colour():
    dm = cloud_to_display(_cloud(5, levels=False))
    dm.cloud_colors = None
    rows = vpmod.cloud_vertex_data(dm, None)
    assert (rows[:, 12:15] == 255).all()
    assert "cloud_colored" in inspect.getsource(Viewport._draw_cloud)


def test_the_point_budget_drops_the_fine_level_first_then_the_middle_one():
    # (cumulative counts per level, total) per cloud
    two = [((400_000, 800_000, 1_000_000), 1_000_000),
           ((400_000, 800_000, 1_000_000), 1_000_000)]
    assert vpmod.cloud_level_budget(two, 2_000_000) == 2
    assert vpmod.cloud_level_budget(two, 1_900_000) == 1
    assert vpmod.cloud_level_budget(two, 900_000) == 0
    # a cloud without levels draws whole and still counts against the budget
    mixed = [((400_000, 800_000, 1_000_000), 1_000_000), (None, 1_500_000)]
    assert vpmod.cloud_level_budget(mixed, 2_000_000) == 0
    assert vpmod.cloud_level_budget(mixed, 2_400_000) == 1


def test_a_far_cloud_is_anchored_like_a_far_mesh():
    dm = cloud_to_display(_cloud(100, offset=FAR))
    anchor = vpmod.mesh_anchor(dm)
    assert anchor is not None
    rows = vpmod.cloud_vertex_data(dm, anchor)
    rel = rows[:, :12].copy().view(np.float32).reshape(-1, 3)
    assert np.abs(rel).max() < 10.0
    assert "anchor" in inspect.getsource(Viewport._draw_cloud)


def test_technical_mode_keeps_point_clouds_away_from_the_hidden_line_kernel():
    src = inspect.getsource(Viewport._paint_technical)
    assert "PointCloudShape" in src
    from serpentine3d.commands import drafting
    assert "PointCloudShape" in inspect.getsource(drafting.cmd_make2d)


def test_a_cloud_is_not_sent_to_the_tessellation_worker():
    scene = Scene()
    vp = _viewport(scene)
    obj = scene.add(_cloud(1_000_000), name="Scan")
    assert vp._schedule_tess(obj) is False
    assert obj.id not in vp._tess_pending


# --- with a context ----------------------------------------------------------

def test_an_offscreen_draw_of_a_million_point_cloud_does_not_raise(painting):
    scene = Scene()
    obj = scene.add(_cloud(1_000_000), name="Scan")
    vp = painting(scene)
    vp.zoom_extents()
    vp.paintGL()
    assert not vp.paint_failed
    gpu = vp._gpu.get(obj.id)
    assert gpu is not None and gpu.cloud_count == 1_000_000
    assert vp.cloud_lod == (2, 1_000_000, 1_000_000)
    assert vp.cloud_lod_note() == ""
    for mode in ("wireframe", "ghosted", "rendered", "technical"):
        vp.set_display_mode(mode)
        vp.paintGL()
        assert not vp.paint_failed, mode


def test_three_million_points_are_thinned_to_the_budget_and_say_so(painting):
    scene = Scene()
    for i in range(3):
        scene.add(_cloud(1_000_000, seed=i, offset=(6.0 * i, 0, 0)),
                  name=f"Scan {i}")
    vp = painting(scene)
    vp.zoom_extents()
    vp.paintGL()
    assert not vp.paint_failed
    level, drawn, total = vp.cloud_lod
    assert total == 3_000_000
    assert level == 1
    assert drawn <= vp.point_budget
    note = vp.cloud_lod_note()
    assert "level 1" in note and "3,000,000" in note


def test_clicking_on_a_point_cloud_selects_it_and_clicking_beside_it_does_not(painting):
    scene = Scene()
    obj = scene.add(_cloud(200_000), name="Scan")
    vp = painting(scene)
    vp.zoom_extents()
    vp.paintGL()
    assert vp.pick_object(400, 300) == obj.id
    assert vp.pick_object(3, 3) is None
    assert vp._box_pick(0, 0, 800, 600, True) == [obj.id]


def test_a_selected_cloud_still_draws(painting):
    scene = Scene()
    obj = scene.add(_cloud(50_000), name="Scan")
    vp = painting(scene)
    vp.selection.set([obj.id])
    vp.zoom_extents()
    vp.paintGL()
    assert not vp.paint_failed


def test_a_far_cloud_draws_with_an_anchor(painting):
    scene = Scene()
    obj = scene.add(_cloud(10_000, offset=FAR), name="Far scan")
    vp = painting(scene)
    vp.zoom_extents()
    vp.paintGL()
    assert not vp.paint_failed
    assert vp._gpu[obj.id].anchor is not None
