import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.snaps import SnapIndex, _intersections, _static_snap_points
from serpentine3d.utils.config import Config, parse_rhino_aliases


def test_quad_snap_points():
    circle = g.make_circle((10, 5, 0), 4)
    pts = _static_snap_points(circle)
    quads = [p for p, k in pts if k == "quad"]
    assert len(quads) == 4
    assert (14.0, 5.0, 0.0) in [tuple(round(c, 6) for c in q) for q in quads]


def test_intersection_snap():
    scene = Scene()
    scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    scene.add(g.make_line((5, -5, 0), (5, 5, 0)))
    pts = _intersections(scene.all())
    assert len(pts) >= 1
    assert any(abs(p[0] - 5) < 1e-6 and abs(p[1]) < 1e-6 for p in pts)


def test_snapindex_respects_type_toggles():
    scene = Scene()
    scene.add(g.make_line((0, 0, 0), (10, 0, 0)))
    from serpentine3d.ui.camera import Camera
    cam = Camera()
    cam.set_standard_view("top")
    cam.target[:] = (5, 0, 0)
    cam.distance = 30
    idx = SnapIndex(scene)
    # project the endpoint to screen and query at that pixel
    import numpy as np
    scr = cam.project(np.array([[10.0, 0, 0]]), 800, 600)
    hit = idx.find(cam, scr[0][0], scr[0][1], 800, 600)
    assert hit is not None and hit[1] == "end"
    idx.types["end"] = False
    idx.types["mid"] = False
    hit2 = idx.find(cam, scr[0][0], scr[0][1], 800, 600)
    assert hit2 is None or hit2[1] not in ("end", "mid")


def test_config_roundtrip(tmp_path):
    path = str(tmp_path / "settings.json")
    cfg = Config(path)
    assert cfg.get("mouse", "orbit_button") == "middle"
    cfg.set("mouse", "orbit_button", "right")
    cfg.set("aliases", {"zz": "box"})
    cfg2 = Config(path)
    assert cfg2.get("mouse", "orbit_button") == "right"
    assert cfg2.get("aliases") == {"zz": "box"}


def test_alias_runtime_registration():
    import serpentine3d.commands  # noqa: F401
    from serpentine3d.commands.base import add_alias, remove_alias, resolve
    add_alias("qq", "circle")
    assert resolve("qq").name == "circle"
    remove_alias("qq")
    assert resolve("qq") is None
