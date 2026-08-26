"""Dragging with the right mouse button orbits, out of the box, as in Rhino.

A user coming from Rhino reported that the viewport contradicts their
muscle memory: in Rhino a right-button drag orbits the perspective view,
and here it did nothing until they found the option and switched it. The
option stays — anyone who has chosen the middle button keeps it — but a
fresh install now orbits on the right button, the Preferences page says
so, and a right *click* still means Enter, so orbit-on-right cannot
swallow the click that repeats the last command.
"""

import re

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
MMB = Qt.MouseButton.MiddleButton
NONE = Qt.KeyboardModifier.NoModifier


def _press(widget, button, at):
    QApplication.sendEvent(widget, QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(*at), button, button, NONE))


def _release(widget, button, at):
    QApplication.sendEvent(widget, QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(*at), button,
        Qt.MouseButton.NoButton, NONE))


def _drag(widget, button, start=(300.0, 200.0), end=(360.0, 240.0)):
    """Press, move, release — delivered the way Qt delivers them."""
    _press(widget, button, start)
    QApplication.sendEvent(widget, QMouseEvent(
        QEvent.Type.MouseMove, QPointF(*end), Qt.MouseButton.NoButton,
        button, NONE))
    _release(widget, button, end)


def _pose(view):
    return view.camera.azimuth, view.camera.elevation


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


# --- the drag ------------------------------------------------------------

def test_a_right_button_drag_orbits_on_a_fresh_install(view):
    v, _ = view
    before = _pose(v)
    _drag(v, RMB)
    assert _pose(v) != before, \
        "a right-button drag left the view where it was"


def test_the_middle_button_does_not_orbit_on_a_fresh_install(view):
    """The two buttons have to be distinguishable: with orbit on the right,
    a middle drag is not an orbit."""
    v, _ = view
    before = _pose(v)
    _drag(v, MMB)
    assert _pose(v) == before, "the middle button orbited as well"


def test_someone_who_chose_the_middle_button_keeps_it(view):
    """The default changes; a setting somebody made does not."""
    v, cfg = view
    cfg.set("mouse", "orbit_button", "middle")
    before = _pose(v)
    _drag(v, MMB)
    assert _pose(v) != before, "the middle button no longer orbits when chosen"


# --- the click -----------------------------------------------------------

def test_a_right_click_with_no_drag_still_repeats_the_last_command():
    """Rhino's right-click-as-Enter must survive the button also orbiting."""
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.set_view_layout("quad")
    QApplication.processEvents()
    pane = [v for v in w.all_viewports() if v._view_name == "perspective"][0]

    w.run_command("line")
    assert w.processor.busy, "the fixture command did not start"
    w.processor.cancel()
    assert not w.processor.busy and w.processor.last_command == "line"

    _press(pane, RMB, (300.0, 200.0))
    _release(pane, RMB, (300.0, 200.0))
    assert w.processor.busy, "the right click did not repeat the last command"
    assert w.processor.active is not None \
        and w.processor.active.name == "line"


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


def test_the_right_button_is_labelled_the_rhino_default(dlg):
    d, _ = dlg
    assert "Rhino default" in d.rb_right.text(), d.rb_right.text()
    assert "Rhino default" not in d.rb_middle.text(), d.rb_middle.text()


def test_the_page_does_not_claim_that_ctrl_orbits(dlg):
    d, _ = dlg
    page = d.rb_right.parentWidget()
    texts = [lbl.text() for lbl in page.findChildren(QLabel)]
    offending = [t for t in texts if re.search(
        r"Ctrl \+ (it|the orbit button)\b[^.]*\borbits", t)]
    assert offending == [], offending
