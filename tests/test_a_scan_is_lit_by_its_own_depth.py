"""A scan reads as a building, not a lattice of dots.

Three things make that so, none of which estimates a normal or touches
the points: a point is sized in perspective, so a scan closes into a
surface as you approach it; a point is round, so a lattice reads as
material rather than pixels; and the frame is lit by eye-dome lighting,
which darkens every pixel by how far it stands in front of its neighbours,
so folds and edges carry a contact shadow. The lighting is a screen pass
over a texture of the scene and its depth, taken only on frames that show
a scan, so a model with no scan in it draws exactly as before.

GL under the offscreen platform gives a context but no framebuffer, so the
paint tests ask whether the pane survived and whether the pass ran; when
even that is missing they are skipped.
"""
from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.pointcloud import PointCloudShape
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vpmod
from serpentine3d.ui.viewport import Viewport


def _cloud(n: int, seed: int = 3) -> PointCloudShape:
    rng = np.random.default_rng(seed)
    xyz = rng.random((n, 3), dtype=np.float32) * np.float32([4, 3, 2.5])
    rgb = (rng.random((n, 3)) * 255).astype(np.uint8)
    return PointCloudShape(xyz, rgb)


def _viewport(scene):
    QApplication.instance() or QApplication([])
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    return vp


@pytest.fixture
def painting():
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


# ------------------------------------------------- the shaders, as text

def test_points_are_sized_in_perspective_and_drawn_round():
    assert "uWorldSize * uPixelsPerUnit / w" in vpmod.POINT_VERT
    assert "clamp(" in vpmod.POINT_VERT          # never below a pixel
    assert "gl_PointCoord" in vpmod.POINT_FRAG and "discard" in vpmod.POINT_FRAG


def test_the_lighting_pass_writes_depth_back_for_the_overlays():
    assert "gl_FragDepth = z" in vpmod.EDL_FRAG
    assert "log2(" in vpmod.EDL_FRAG           # log depth, as in CloudCompare


def test_the_lighting_pass_never_shades_from_the_background():
    # A background pixel has depth 1 and must neither be shaded nor cast
    # onto the edge of the scan beside it.
    assert "if (z >= 1.0) return 0.0" in vpmod.EDL_FRAG
    assert "if (z >= 1.0) { frag = color; return; }" in vpmod.EDL_FRAG


# ------------------------------------------------------- the frame

def test_a_frame_with_a_scan_takes_the_lighting_pass(painting, monkeypatch):
    scene = Scene()
    scene.add(_cloud(50_000), name="Scan")
    vp = painting(scene)
    vp.zoom_extents()
    ran = []
    real = vp._edl_end
    monkeypatch.setattr(vp, "_edl_end", lambda: (ran.append(1), real()))
    vp.paintGL()
    assert not vp._paint_failed
    assert vp.cloud_shading == "edl"           # the card could make the target
    assert ran == [1]
    assert vp._edl_size == vp._edl_px()


def test_a_frame_without_a_scan_draws_as_it_always_did(painting, monkeypatch):
    scene = Scene()
    scene.add(g.make_box((0.0, 0.0, 0.0), 1.0, 1.0, 1.0), name="Box")
    vp = painting(scene)
    ran = []
    monkeypatch.setattr(vp, "_edl_begin", lambda: ran.append(1))
    vp.paintGL()
    assert not vp._paint_failed
    assert ran == []


def test_flat_shading_is_a_display_choice(painting, monkeypatch):
    scene = Scene()
    scene.add(_cloud(10_000), name="Scan")
    vp = painting(scene)
    vp.cloud_shading = "flat"
    ran = []
    monkeypatch.setattr(vp, "_edl_begin", lambda: ran.append(1))
    vp.paintGL()
    assert not vp._paint_failed
    assert ran == []


def test_technical_mode_leaves_the_scan_to_the_hidden_line_kernel(painting, monkeypatch):
    scene = Scene()
    scene.add(_cloud(10_000), name="Scan")
    vp = painting(scene)
    vp.display_mode = "technical"
    ran = []
    monkeypatch.setattr(vp, "_edl_begin", lambda: ran.append(1))
    vp.paintGL()
    assert ran == []


def test_the_target_follows_the_pane_size(painting):
    scene = Scene()
    scene.add(_cloud(10_000), name="Scan")
    vp = painting(scene)
    vp.paintGL()
    first = vp._edl_size
    vp.resize(400, 300)
    QApplication.processEvents()
    vp.paintGL()
    assert not vp._paint_failed
    assert vp._edl_size == vp._edl_px() != first


# ------------------------------------------- the size a point draws at

def test_a_scan_knows_how_far_apart_its_points_are():
    from serpentine3d.core.pointcloud import estimate_spacing
    # a wall sampled on a 1 cm grid, jittered a little as a scanner would
    rng = np.random.default_rng(1)
    u, v = np.meshgrid(np.arange(0, 3, 0.01), np.arange(0, 2, 0.01))
    wall = np.stack([u.ravel(), np.zeros(u.size), v.ravel()], 1)
    wall += rng.normal(0, 0.001, wall.shape)
    spacing = estimate_spacing(wall.astype(np.float32))
    assert 0.008 < spacing < 0.014


def test_the_spacing_is_carried_to_the_card_and_sizes_the_splat(painting):
    from serpentine3d.core.pointcloud import cloud_to_display
    dm = cloud_to_display(_cloud(50_000))
    assert dm.cloud_spacing > 0
    assert "uWorldSize * uPixelsPerUnit / w" in vpmod.POINT_VERT
    assert "uMinPx, uMaxPx" in vpmod.POINT_VERT
    scene = Scene()
    obj = scene.add(_cloud(50_000), name="Scan")
    vp = painting(scene)
    vp.zoom_extents()
    vp.paintGL()
    assert vp._gpu[obj.id].cloud_spacing > 0
    assert vp._frame_ppu > 0


def test_a_cloud_of_unknown_spacing_draws_at_the_pixel_size():
    from serpentine3d.core.pointcloud import estimate_spacing
    assert estimate_spacing(np.zeros((1, 3), np.float32)) == 0.0
    assert estimate_spacing(np.zeros((0, 3), np.float32)) == 0.0
