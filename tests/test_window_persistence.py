"""The window you left is the window you get back (GitHub #5).

Dock sizes, the quad layout and the preferred display mode all reset every
launch: the right panels were re-imposed at 280 px, `4view` had to be typed
again each morning, and a wireframe person got shaded until they said
otherwise. The reporter read that as "no standard configuration".
"""

import json
import os

import pytest

from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.viewport import Viewport
from serpentine3d.utils.config import Config


@pytest.fixture
def cfg(tmp_path):
    return Config(str(tmp_path / "settings.json"))


def test_viewport_starts_in_the_configured_display_mode(cfg):
    cfg.set("display", "default_mode", "wireframe")
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene), config=cfg)
    assert vp.display_mode == "wireframe"


def test_a_junk_display_mode_falls_back_to_shaded(cfg):
    cfg.set("display", "default_mode", "cel-shaded-anime")
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene), config=cfg)
    assert vp.display_mode == "shaded"


def test_no_config_still_means_shaded():
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    assert vp.display_mode == "shaded"


def _window(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    return MainWindow()


def test_quad_layout_survives_a_restart(tmp_path, monkeypatch):
    w = _window(tmp_path, monkeypatch)
    w.set_view_layout("quad")
    # Showing a GL window offscreen would try to paint, so stand in for
    # "somebody saw it" instead — the guard under test is closeEvent's.
    w.isVisible = lambda: True
    w.close()

    stored = json.loads((tmp_path / "settings.json").read_text())
    assert stored["window"]["layout"] == "quad"
    assert stored["window"]["state"]        # dock arrangement went with it

    again = _window(tmp_path, monkeypatch)
    assert len(again.aux_viewports) == 3
    assert all(d.isVisibleTo(again) for d in again.aux_docks)
    again.close()


def test_single_stays_single(tmp_path, monkeypatch):
    """A first launch opens in quad now, so choosing single is a choice —
    and it has to outlast the session that made it, or the new default
    would simply overrule anyone who does not want four panes."""
    w = _window(tmp_path, monkeypatch)
    w.set_view_layout("single")
    w.isVisible = lambda: True
    w.close()
    assert os.path.exists(tmp_path / "settings.json")
    again = _window(tmp_path, monkeypatch)
    assert not any(d.isVisibleTo(again) for d in again.aux_docks)
    again.close()


def test_a_window_nobody_saw_saves_no_layout(tmp_path, monkeypatch):
    """A headless window (tests, a crashed pre-show launch) closing must not
    overwrite the layout the user actually chose with default geometry —
    exactly what a run of this suite used to do to the real settings file."""
    w = _window(tmp_path, monkeypatch)
    w.set_view_layout("quad")
    w.close()
    if os.path.exists(tmp_path / "settings.json"):
        stored = json.loads((tmp_path / "settings.json").read_text())
        assert stored.get("window", {}).get("state", "") == ""
