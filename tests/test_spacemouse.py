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
    """Spin the event loop for a fixed spell, for when nothing should happen."""
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()


def _pump_until(app, done, ms=3000):
    """Spin the event loop until the navigator has acted on what we sent.

    The feed is a socket, and socketpair() is AF_UNIX here but a loopback
    TCP pair on Windows, so bytes that arrive instantly on this machine can
    still be in flight when a fixed 80 ms runs out. That is why these
    passed one at a time and failed in the full run on a loaded box.
    Waiting for the effect rather than for the clock holds either way, and
    costs nothing when the effect is already there.
    """
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        if done():
            return True
    return False


def test_twist_orbits_and_push_zooms(win_sm):
    w, sm, feed, app = win_sm
    cam = w.viewport.camera
    az0, dist0, target0 = cam.azimuth, cam.distance, cam.target.copy()
    feed.sendall(_motion(ry=350))          # full twist
    assert _pump_until(app, lambda: cam.azimuth != az0), "the twist never came"
    az1 = cam.azimuth
    feed.sendall(_motion(z=350))           # push forward = zoom in
    assert _pump_until(app, lambda: cam.distance < dist0), "the push never came"
    assert cam.azimuth == az1              # zoom does not orbit
    feed.sendall(_motion(x=350, y=200))    # slide pans the target
    assert _pump_until(app, lambda: not (cam.target == target0).all()), (
        "the slide never came")


def test_events_coalesce_and_disabled_flag(win_sm):
    w, sm, feed, app = win_sm
    cam = w.viewport.camera
    d0 = cam.distance
    feed.sendall(b"".join(_motion(z=350) for _ in range(10)))
    assert _pump_until(app, lambda: cam.distance < d0), "the burst never came"
    _pump(app)                             # and let the rest of it land
    d1 = cam.distance
    w.cfg.set("spacemouse", "enabled", False)
    feed.sendall(_motion(z=350))
    _pump(app)                             # nothing to wait for: it must sit
    assert cam.distance == d1              # disabled: no movement


def test_buttons_run_commands(win_sm):
    w, sm, feed, app = win_sm
    from serpentine3d.core import geometry as g
    w.scene.add(g.make_box((100, 100, 0), 5, 5, 5))
    cam = w.viewport.camera
    feed.sendall(_button(0))               # default: zoomextents
    assert _pump_until(app, lambda: abs(float(cam.target[0]) - 102.5) < 1.0), (
        f"zoomextents never ran (target x {float(cam.target[0]):.2f})")
    import math
    feed.sendall(_button(1))               # default: perspective view
    assert _pump_until(
        app, lambda: cam.azimuth == pytest.approx(math.radians(-60), abs=0.01)
    ), f"the perspective view never came (azimuth {cam.azimuth:.4f})"


def test_layout_space_pans_sheet(win_sm):
    w, sm, feed, app = win_sm
    from serpentine3d.core.layout import Layout
    lay = Layout(name="Sheet 1")
    w.scene.layouts.append(lay)
    w.viewport.set_space(lay.id)
    lv = w.viewport.layout_view
    pan0 = lv.pan.copy()
    feed.sendall(_motion(x=350))
    assert _pump_until(app, lambda: lv.pan[0] != pan0[0]), "the slide never came"
    w.viewport.set_space("model")


def test_daemon_absent_is_quiet(win_sm):
    # navigator constructed against a nonexistent socket in the fixture:
    # attach_socket switched it on, but a fresh one must just idle
    w, sm, feed, app = win_sm
    import serpentine3d.ui.spacemouse as sm_mod
    nav = sm_mod.SpaceMouseNavigator(w)
    assert nav.source is None
    assert "no SpaceMouse source" in nav.status()
