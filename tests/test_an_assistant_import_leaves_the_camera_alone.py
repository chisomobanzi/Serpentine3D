"""Importing over RPC or MCP does not move the modeller's camera.

Import zoomed to fit whatever came in. From the window that is what the person
clicking Import expects; from outside it is someone else's view being moved,
every time an assistant adds a part. The bridge's import, and an import
command run headless, now leave the camera where it was. Import from the menu
or the command line still fits the view, and the bridge can ask it to.
"""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.app import MainWindow
from serpentine3d.rpc import RpcServer


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("SERP3D_NO_RPC", "1")
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    monkeypatch.setenv("SERP3D_PLUGIN_DIR", str(tmp_path / "plugins"))
    window = MainWindow()
    yield RpcServer(window).api
    window.processor.cancel()
    window.mark_saved()
    window.close()
    QApplication.processEvents()


@pytest.fixture
def far_away_part(tmp_path):
    path = tmp_path / "part.obj"
    path.write_text("v 500 500 0\nv 520 500 0\nv 500 520 0\nf 1 2 3\n")
    return str(path)


def _pose(api):
    cam = api.viewport.camera
    return np.array([*cam.target, cam.distance, cam.azimuth, cam.elevation])


def _looking_somewhere(api):
    api.command("camera", inputs=["Place", "0,-100,20", "0,0,0"])
    return _pose(api)


def test_the_bridge_import_keeps_the_view(api, far_away_part):
    before = _looking_somewhere(api)
    assert api.import_file(far_away_part)["imported"] == 1
    np.testing.assert_allclose(_pose(api), before)


def test_the_bridge_can_still_ask_to_fit_the_view(api, far_away_part):
    before = _looking_somewhere(api)
    api.import_file(far_away_part, zoom_extents=True)
    assert not np.allclose(_pose(api), before)


def test_a_headless_import_command_keeps_the_view(api, far_away_part):
    before = _looking_somewhere(api)
    api.command("import", inputs=[far_away_part])
    assert len(api.scene.all()) == 1
    np.testing.assert_allclose(_pose(api), before)


def test_import_from_the_window_still_fits_the_view(api, far_away_part):
    before = _looking_somewhere(api)
    api.window._import_path(far_away_part)
    assert len(api.scene.all()) == 1
    assert not np.allclose(_pose(api), before)
