"""Ctrl + the orbit button zooms, as in Rhino.

Rhino's chords on the orbit button are plain drag = orbit, Shift = pan and
Ctrl = zoom: drag up and the camera comes closer, drag down and it backs
away. A user with that in their hands held Ctrl and dragged expecting to
zoom in on a detail, and the view swung round instead. Orbit and Shift-pan
already match Rhino; this makes the third chord match too, and has the
Preferences Mouse page say so.
"""

import re

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod
from serpentine3d.ui.settings_dialog import SettingsDialog
from serpentine3d.utils.config import Config

RMB = Qt.MouseButton.RightButton
NONE = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


def _press(widget, button, at, mods=NONE):
    QApplication.sendEvent(widget, QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(*at), button, button, mods))


def _release(widget, button, at, mods=NONE):
    QApplication.sendEvent(widget, QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(*at), button,
        Qt.MouseButton.NoButton, mods))


def _drag(widget, button, start=(300.0, 200.0), end=(360.0, 240.0),
          mods=NONE):
    """Press, move, release — delivered the way Qt delivers them, with the
    modifier held throughout."""
    _press(widget, button, start, mods)
    QApplication.sendEvent(widget, QMouseEvent(
        QEvent.Type.MouseMove, QPointF(*end), Qt.MouseButton.NoButton,
        button, mods))
    _release(widget, button, end, mods)


def _orientation(view):
    return view.camera.azimuth, view.camera.elevation


def _target(view):
    return np.array(view.camera.target, dtype=float).copy()


@pytest.fixture
def view(tmp_path):
    """A perspective viewport on factory settings: nothing configured."""
    scene = Scene()
    cfg = Config(path=str(tmp_path / "settings.json"))
    v = vp_mod.Viewport(scene, SelectionManager(scene), config=cfg)
    v.resize(800, 600)
    v.camera.set_standard_view("perspective")
    assert v.camera.projection == "perspective"
    return v, cfg


# --- Ctrl + orbit button zooms --------------------------------------------

def test_ctrl_and_a_vertical_right_drag_changes_only_the_distance(view):
    v, _ = view
    orientation = _orientation(v)
    target = _target(v)
    distance = v.camera.distance

    _drag(v, RMB, start=(300.0, 300.0), end=(300.0, 200.0), mods=CTRL)

    assert v.camera.distance != distance, \
        "Ctrl + a right-button drag did not move the camera closer or further"
    assert _orientation(v) == orientation, \
        "Ctrl + a right-button drag orbited instead of zooming"
    assert np.allclose(_target(v), target), \
        "Ctrl + a right-button drag panned instead of zooming"


def test_dragging_up_with_ctrl_zooms_in_and_down_zooms_out(view):
    """Rhino's convention: push the mouse away from you to come closer."""
    v, _ = view
    start = v.camera.distance

    _drag(v, RMB, start=(300.0, 300.0), end=(300.0, 200.0), mods=CTRL)
    after_up = v.camera.distance
    assert after_up < start, \
        f"dragging up did not zoom in: {start} -> {after_up}"

    _drag(v, RMB, start=(300.0, 200.0), end=(300.0, 300.0), mods=CTRL)
    after_down = v.camera.distance
    assert after_down > after_up, \
        f"dragging down did not zoom out: {after_up} -> {after_down}"


# --- the other two chords are untouched -----------------------------------

def test_shift_and_a_right_drag_still_pans(view):
    v, _ = view
    orientation = _orientation(v)
    target = _target(v)
    distance = v.camera.distance

    _drag(v, RMB, mods=SHIFT)

    assert not np.allclose(_target(v), target), "Shift no longer pans"
    assert _orientation(v) == orientation, "Shift orbited as well as panning"
    assert v.camera.distance == distance, "Shift zoomed as well as panning"


def test_a_plain_right_drag_still_orbits(view):
    v, _ = view
    orientation = _orientation(v)
    distance = v.camera.distance

    _drag(v, RMB)

    assert _orientation(v) != orientation, "a plain right drag stopped orbiting"
    assert v.camera.distance == distance, "a plain right drag zoomed"


# --- the Preferences page ------------------------------------------------

class _Window(QWidget):
    """Just enough window for the dialog to build its pages against."""

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        scene = Scene()
        self.viewport = vp_mod.Viewport(scene, SelectionManager(scene),
                                        config=cfg)
        self.osnap_bar = type("_Bar", (), {"refresh": lambda self: None})()

    def apply_user_shortcuts(self):
        pass

    def apply_user_aliases(self):
        pass


@pytest.fixture
def dlg(tmp_path):
    cfg = Config(path=str(tmp_path / "settings.json"))
    return SettingsDialog(_Window(cfg)), cfg


def test_the_mouse_page_says_that_ctrl_zooms(dlg):
    d, _ = dlg
    page = d.rb_right.parentWidget()
    texts = [lbl.text() for lbl in page.findChildren(QLabel)]
    sentences = [s for t in texts for s in re.split(r"(?<=\.)\s+", t)]
    saying_so = [s for s in sentences
                 if "Ctrl" in s and re.search(r"\bzoom", s, re.IGNORECASE)]
    assert saying_so, \
        f"no sentence on the Mouse page says Ctrl zooms; labels: {texts}"
