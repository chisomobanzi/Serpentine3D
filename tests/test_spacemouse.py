"""SpaceMouse navigation: protocol parsing, camera mapping, buttons."""

import socket
import struct
import time

import pytest


def _motion(x=0, y=0, z=0, rx=0, ry=0, rz=0, period=16):
    return struct.pack("iiiiiiii", 0, x, y, z, rx, ry, rz, period)


def _button(num, pressed=True):
    return struct.pack("iiiiiiii", 1 if pressed else 2, num, 0, 0, 0, 0,
                       0, 0)


@pytest.fixture
def win_sm(tmp_path, monkeypatch):
    import json
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({}))
    monkeypatch.setenv("SERP3D_CONFIG", str(cfg))
    monkeypatch.setenv("SERP3D_AUTOSAVE_DIR", str(tmp_path / "as"))
    # keep the navigator off the real daemon in tests
    monkeypatch.setenv("SPNAV_SOCKET", str(tmp_path / "nonexistent.sock"))
    from PySide6.QtWidgets import QApplication
    from serpentine3d.app import MainWindow
    import serpentine3d.ui.spacemouse as sm_mod
    monkeypatch.setattr(sm_mod, "SPNAV_SOCKET",
                        str(tmp_path / "nonexistent.sock"))
    monkeypatch.setattr(sm_mod.SpaceMouseNavigator, "_open_evdev",
                        lambda self: None)
    w = MainWindow()
    a, b = socket.socketpair()      # AF_UNIX on POSIX, AF_INET on Windows
    w.spacemouse.attach_socket(b)
    app = QApplication.instance()
    yield w, w.spacemouse, a, app
    a.close()
    w._saved_revision = w.scene.revision
    w.close()


def _pump(app, ms=80):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()


def test_twist_orbits_and_push_zooms(win_sm):
    w, sm, feed, app = win_sm
    cam = w.viewport.camera
    az0, dist0, target0 = cam.azimuth, cam.distance, cam.target.copy()
    feed.sendall(_motion(ry=350))          # full twist
    _pump(app)
    assert cam.azimuth != az0
    az1 = cam.azimuth
    feed.sendall(_motion(z=350))           # push forward = zoom in
    _pump(app)
    assert cam.distance < dist0
    assert cam.azimuth == az1              # zoom does not orbit
    feed.sendall(_motion(x=350, y=200))    # slide pans the target
    _pump(app)
    assert not (cam.target == target0).all()


def test_events_coalesce_and_disabled_flag(win_sm):
    w, sm, feed, app = win_sm
    cam = w.viewport.camera
    d0 = cam.distance
    feed.sendall(b"".join(_motion(z=350) for _ in range(10)))
    _pump(app)
    d1 = cam.distance
    assert d1 < d0
    w.cfg.set("spacemouse", "enabled", False)
    feed.sendall(_motion(z=350))
    _pump(app)
    assert cam.distance == d1              # disabled: no movement


def test_buttons_run_commands(win_sm):
    w, sm, feed, app = win_sm
    from serpentine3d.core import geometry as g
    w.scene.add(g.make_box((100, 100, 0), 5, 5, 5))
    feed.sendall(_button(0))               # default: zoomextents
    _pump(app)
    assert abs(float(w.viewport.camera.target[0]) - 102.5) < 1.0
    feed.sendall(_button(1))               # default: perspective view
    _pump(app)
    import math
    assert w.viewport.camera.azimuth == pytest.approx(math.radians(-60),
                                                      abs=0.01)


def test_layout_space_pans_sheet(win_sm):
    w, sm, feed, app = win_sm
    from serpentine3d.core.layout import Layout
    lay = Layout(name="Sheet 1")
    w.scene.layouts.append(lay)
    w.viewport.set_space(lay.id)
    lv = w.viewport.layout_view
    pan0 = lv.pan.copy()
    feed.sendall(_motion(x=350))
    _pump(app)
    assert lv.pan[0] != pan0[0]
    w.viewport.set_space("model")


def test_daemon_absent_is_quiet(win_sm):
    # navigator constructed against a nonexistent socket in the fixture:
    # attach_socket switched it on, but a fresh one must just idle
    w, sm, feed, app = win_sm
    import serpentine3d.ui.spacemouse as sm_mod
    nav = sm_mod.SpaceMouseNavigator(w)
    assert nav.source is None
    assert "no SpaceMouse source" in nav.status()
