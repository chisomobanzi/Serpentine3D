"""Binding a command to a mouse button held with modifiers.

Keyboard shortcuts have been settable for a while; the mouse had only a
choice of orbit button. This is the same idea for a button and modifiers
held together — 'ctrl+shift+mmb' runs a command.

It fires on a click, not on a press, because the middle button is also the
orbit button: acting on press would mean holding those modifiers made the
view unorbitable.
"""

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod
from serpentine3d.utils.config import Config, chord_key, parse_chord

CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier
ALT = Qt.KeyboardModifier.AltModifier
NONE = Qt.KeyboardModifier.NoModifier
MMB = Qt.MouseButton.MiddleButton
RMB = Qt.MouseButton.RightButton


@pytest.mark.parametrize("text", [
    "ctrl+shift+middle", "Ctrl+Shift+MMB", "mmb+ctrl+shift",
    "SHIFT + CONTROL + Middle", "shift+ctrl+wheel",
])
def test_a_chord_reads_the_same_however_it_is_written(text):
    """Nobody should have to guess the order or the spelling."""
    assert parse_chord(text) == "ctrl+shift+middle"


@pytest.mark.parametrize("text", [
    "", "ctrl+shift", "middle+right", "ctrl+shift+q", "ctrl++middle",
])
def test_nonsense_is_not_a_chord(text):
    assert parse_chord(text) is None


def test_a_bare_button_is_a_chord_too():
    assert parse_chord("mmb") == "middle"


def test_the_canonical_form_is_what_an_event_produces():
    assert chord_key("middle", ctrl=True, shift=True) == "ctrl+shift+middle"
    assert chord_key("right", alt=True) == "alt+right"
    assert chord_key("middle") == "middle"


# --- the viewport end ----------------------------------------------------

def _click(view, button, mods, at=(300.0, 200.0), to=None):
    """A press and a release. `to` moves the mouse in between, which is a
    drag rather than a click."""
    start, end = QPointF(*at), QPointF(*(to or at))
    for kind, pos in ((QMouseEvent.Type.MouseButtonPress, start),
                      (QMouseEvent.Type.MouseButtonRelease, end)):
        view.__class__.__mro__  # noqa: B018  (keeps the widget alive in Qt)
        ev = QMouseEvent(kind, pos, pos, button,
                         button if kind == QMouseEvent.Type.MouseButtonPress
                         else Qt.MouseButton.NoButton, mods)
        if kind == QMouseEvent.Type.MouseButtonPress:
            view.mousePressEvent(ev)
        else:
            view.mouseReleaseEvent(ev)


@pytest.fixture
def view(tmp_path):
    scene = Scene()
    cfg = Config(path=str(tmp_path / "settings.json"))
    v = vp_mod.Viewport(scene, SelectionManager(scene), config=cfg)
    v.resize(800, 600)
    return v, cfg


def test_a_bound_chord_runs_its_command(view):
    v, cfg = view
    cfg.set("mouse", "chords", {"ctrl+shift+mmb": "zoomselected"})
    fired = []
    v.chordActivated.connect(fired.append)

    _click(v, MMB, CTRL | SHIFT)
    assert fired == ["zoomselected"]


def test_the_chord_takes_the_click_from_the_popup(view):
    """The middle click already means something. A bound chord has to win,
    or the popup opens on top of whatever the command asks for."""
    v, cfg = view
    cfg.set("mouse", "chords", {"ctrl+shift+mmb": "zoomselected"})
    popups = []
    v.popupRequested.connect(lambda: popups.append(1))

    _click(v, MMB, CTRL | SHIFT)
    assert popups == [], "the recent-commands popup opened as well"


def test_a_plain_middle_click_still_opens_the_popup(view):
    v, cfg = view
    cfg.set("mouse", "chords", {"ctrl+shift+mmb": "zoomselected"})
    popups, fired = [], []
    v.popupRequested.connect(lambda: popups.append(1))
    v.chordActivated.connect(fired.append)

    _click(v, MMB, NONE)
    assert popups == [1] and fired == []


def test_an_unbound_chord_is_left_alone(view):
    v, cfg = view
    cfg.set("mouse", "chords", {"ctrl+shift+mmb": "zoomselected"})
    fired = []
    v.chordActivated.connect(fired.append)

    _click(v, MMB, ALT)
    assert fired == []


def test_dragging_with_the_chord_held_still_orbits(view):
    """The middle button orbits. If holding the modifiers stole the drag,
    the binding would cost you the view."""
    v, cfg = view
    cfg.set("mouse", "chords", {"ctrl+shift+mmb": "zoomselected"})
    fired = []
    v.chordActivated.connect(fired.append)

    _click(v, MMB, CTRL | SHIFT, at=(300.0, 200.0), to=(360.0, 240.0))
    assert fired == [], "a drag was taken as a click"


def test_the_right_button_can_be_bound_too(view):
    v, cfg = view
    cfg.set("mouse", "chords", {"ctrl+rmb": "zoomextents"})
    fired, enters = [], []
    v.chordActivated.connect(fired.append)
    v.enterShortcut.connect(lambda: enters.append(1))

    _click(v, RMB, CTRL)
    assert fired == ["zoomextents"] and enters == []


def test_nothing_is_bound_out_of_the_box(view):
    """Chords are opt-in: an empty setting must not change how the mouse
    already behaves."""
    v, cfg = view
    assert cfg.get("mouse", "chords", default=None) == {}
    fired, popups = [], []
    v.chordActivated.connect(fired.append)
    v.popupRequested.connect(lambda: popups.append(1))

    _click(v, MMB, CTRL | SHIFT)
    assert fired == [] and popups == [1]
