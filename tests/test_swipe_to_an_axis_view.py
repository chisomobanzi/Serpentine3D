"""Alt and a swipe turn the camera to face the nearest axis.

Blender's gesture: hold Alt, drag the nav button the way you want to go, and
the camera lands looking down that axis. It earns its place in a maximised
pane, where the alternative is the view menu or remembering a command.

The swipe turns the camera and nothing else. A perspective pane comes out
perspective, seen from the top, and an ordinary drag orbits straight back
out of it. A pane that is already parallel comes out as the same parallel
Top the menu gives you. That way "Top" keeps meaning one thing.

The direction rule is the one the mouse already teaches: the swipe carries
on the way a drag-orbit would take you, ninety degrees, then lands on the
nearest axis. So it reads the same from a standard view (a quarter turn)
and from halfway through an orbit (the axis on that side).
"""

import math

import pytest
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from serpentine3d.ui.camera import (
    STANDARD_VIEWS,
    Camera,
    axis_view_after_swipe,
    eased,
    pose_between,
)


def _swipe(view: str, dx: float, dy: float) -> str | None:
    az, el = STANDARD_VIEWS[view]
    return axis_view_after_swipe(az, el, dx, dy)


# --------------------------------------------------- a quarter turn each way

def test_swiping_right_from_the_right_view_lands_on_front():
    assert _swipe("right", 60.0, 0.0) == "front"


def test_swiping_left_from_the_right_view_lands_on_back():
    assert _swipe("right", -60.0, 0.0) == "back"


def test_four_swipes_the_same_way_come_back_round():
    seen, az, el = [], *STANDARD_VIEWS["front"]
    for _ in range(4):
        name = axis_view_after_swipe(az, el, 60.0, 0.0)
        seen.append(name)
        az, el = STANDARD_VIEWS[name]
    assert seen == ["left", "back", "right", "front"]


def test_swiping_down_from_the_front_view_lands_on_top():
    """Down, because dragging down is what tips the top towards you."""
    assert _swipe("front", 0.0, 60.0) == "top"


def test_swiping_up_from_the_front_view_lands_on_bottom():
    assert _swipe("front", 0.0, -60.0) == "bottom"


def test_a_horizontal_swipe_in_the_top_view_still_goes_somewhere():
    """Turning about the world Z would be a no-op looking straight down."""
    assert _swipe("top", 60.0, 0.0) == "left"


def test_swiping_down_from_the_top_view_comes_over_the_pole():
    assert _swipe("top", 0.0, 60.0) == "back"


# ------------------------------------------------------ from anywhere at all

def test_a_swipe_mid_orbit_lands_on_the_nearest_axis_that_way():
    """Not a quarter turn from nowhere: the axis on the side you swiped."""
    az, el = STANDARD_VIEWS["perspective"]
    assert axis_view_after_swipe(az, el, 60.0, 0.0) == "left"


def test_every_landing_is_an_axis_view():
    """Never perspective or isometric: those are not directions to face."""
    axes = {"top", "bottom", "front", "back", "left", "right"}
    for az in range(-180, 180, 17):
        for el in (-80, -30, 0, 30, 80):
            for dx, dy in ((60, 0), (-60, 0), (0, 60), (0, -60)):
                got = axis_view_after_swipe(math.radians(az),
                                            math.radians(el), dx, dy)
                assert got in axes


# ------------------------------------------------------------ what counts

def test_a_twitch_is_not_a_swipe():
    assert _swipe("front", 3.0, 2.0) is None


def test_the_longer_side_of_the_drag_wins():
    assert _swipe("front", 60.0, 12.0) == "left"
    assert _swipe("front", 12.0, 60.0) == "top"


# --------------------------------------------------------- a named view is
# a pair of angles, and this only ever hands back one of those

def test_the_names_it_hands_back_are_ones_a_camera_knows():
    cam = Camera()
    for dx, dy in ((60, 0), (0, 60)):
        cam.set_standard_view("perspective")
        cam.set_standard_view(axis_view_after_swipe(cam.azimuth,
                                                    cam.elevation, dx, dy))


# ---------------------------------------------------------- the gesture itself

ALT = Qt.KeyboardModifier.AltModifier
NONE = Qt.KeyboardModifier.NoModifier
MMB = Qt.MouseButton.MiddleButton
RMB = Qt.MouseButton.RightButton


@pytest.fixture
def view(tmp_path):
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui import viewport as vp_mod
    from serpentine3d.utils.config import Config
    cfg = Config(path=str(tmp_path / "settings.json"))
    scene = Scene()
    v = vp_mod.Viewport(scene, SelectionManager(scene), config=cfg)
    v.resize(800, 600)
    return v, cfg


def _press(v, button, mods, at):
    v.mousePressEvent(QMouseEvent(QMouseEvent.Type.MouseButtonPress,
                                  QPointF(*at), QPointF(*at), button,
                                  button, mods))


def _move(v, button, mods, to):
    v.mouseMoveEvent(QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(*to),
                                 QPointF(*to), Qt.MouseButton.NoButton,
                                 button, mods))


def _release(v, button, mods, at):
    v.mouseReleaseEvent(QMouseEvent(QMouseEvent.Type.MouseButtonRelease,
                                    QPointF(*at), QPointF(*at), button,
                                    Qt.MouseButton.NoButton, mods))


def _drag(v, button, mods, frm=(300.0, 200.0), to=(420.0, 200.0)):
    """The whole gesture, and then wherever the view settles.

    The turn is animated, so these tests ask about the destination rather
    than about the flight. The flight has its own section further down.
    """
    _press(v, button, mods, frm)
    for t in (0.25, 0.6, 1.0):
        _move(v, button, mods, (frm[0] + (to[0] - frm[0]) * t,
                                frm[1] + (to[1] - frm[1]) * t))
    _release(v, button, mods, to)
    v.land_flight()


def test_an_alt_drag_turns_the_pane_to_an_axis(view):
    v, _ = view
    _drag(v, MMB, ALT)
    assert (v.camera.azimuth, v.camera.elevation) == STANDARD_VIEWS["left"]


def test_the_pane_is_still_the_perspective_pane_afterwards(view):
    """Nothing about the pane changed, only where its camera stands."""
    v, _ = view
    _drag(v, MMB, ALT)
    assert v.camera.projection == "perspective"
    assert v._view_name == "perspective"


def test_a_swipe_in_a_flat_pane_lands_on_the_whole_named_view(view):
    """Already parallel, so this is the same Left the View menu gives you,
    construction plane and label included."""
    v, _ = view
    v.set_view("top")
    seen = []
    v.viewChanged.connect(seen.append)
    _drag(v, MMB, ALT)
    assert v._view_name == "left"
    assert v.camera.projection == "parallel"
    assert seen == ["left"]


def test_the_target_and_the_zoom_are_not_touched(view):
    """It turns the camera; it does not re-frame what you were looking at."""
    v, _ = view
    v.camera.target[:] = (5.0, -2.0, 1.0)
    v.camera.distance = 12.5
    _drag(v, MMB, ALT)
    assert list(v.camera.target) == [5.0, -2.0, 1.0]
    assert v.camera.distance == pytest.approx(12.5)


def test_the_swipe_does_not_orbit_on_the_way(view):
    """Otherwise the view lurches under the cursor and then jumps."""
    v, _ = view
    before = (v.camera.azimuth, v.camera.elevation)
    _press(v, MMB, ALT, (300.0, 200.0))
    _move(v, MMB, ALT, (360.0, 230.0))
    assert (v.camera.azimuth, v.camera.elevation) == before
    _release(v, MMB, ALT, (420.0, 200.0))


def test_a_drag_without_alt_still_orbits(view):
    v, _ = view
    before = v.camera.azimuth
    _drag(v, MMB, NONE)
    assert v.camera.azimuth != before
    assert (v.camera.azimuth, v.camera.elevation) != STANDARD_VIEWS["left"]


def test_an_alt_click_that_goes_nowhere_still_opens_the_popup(view):
    """Under the threshold it was never a swipe, so the middle button keeps
    the meaning it already had."""
    v, _ = view
    popups = []
    v.popupRequested.connect(lambda: popups.append(1))
    _drag(v, MMB, ALT, frm=(300.0, 200.0), to=(302.0, 201.0))
    assert popups == [1]
    assert v.camera.azimuth == STANDARD_VIEWS["perspective"][0]


def test_another_button_let_go_mid_swipe_does_not_cancel_it(view):
    """The swipe belongs to the button that started it."""
    v, _ = view
    _press(v, MMB, ALT, (300.0, 200.0))
    _move(v, MMB, ALT, (360.0, 200.0))
    _release(v, Qt.MouseButton.LeftButton, ALT, (360.0, 200.0))
    _move(v, MMB, ALT, (420.0, 200.0))
    _release(v, MMB, ALT, (420.0, 200.0))
    v.land_flight()
    assert (v.camera.azimuth, v.camera.elevation) == STANDARD_VIEWS["left"]


def test_the_swipe_follows_the_configured_orbit_button(view):
    """Whichever button orbits is the one that swipes."""
    v, cfg = view
    cfg.set("mouse", "orbit_button", "right")
    enters = []
    v.enterShortcut.connect(lambda: enters.append(1))
    _drag(v, RMB, ALT)
    assert (v.camera.azimuth, v.camera.elevation) == STANDARD_VIEWS["left"]
    assert enters == [], "the right button also fired its Enter shortcut"


# ------------------------------------------------------------- the flight

"""It turns over about a fifth of a second rather than teleporting.

Front and Back look identical on a symmetric model, so a cut says nothing
about which way you went or where you ended up. The motion is the whole
answer to that.

The angles are interpolated in pairs, not the eye direction: azimuth is
also what a Top view is rolled to, so spreading that turn over the flight
gets you a plan view already the right way up instead of a quarter turn
popping in at the end.
"""


def _flight_from(v, ms=None):
    """Set a swipe going and hand back its clock, without landing it."""
    if ms is not None:
        v.config.set("display", "view_transition_ms", ms)
    _press(v, MMB, ALT, (300.0, 200.0))
    for x in (340.0, 400.0, 420.0):
        _move(v, MMB, ALT, (x, 200.0))
    _release(v, MMB, ALT, (420.0, 200.0))
    return v.flight_started_at


# --- the pure part, which needs no window

def test_a_pose_partway_is_the_pair_partway():
    assert pose_between((0.0, 0.0), (2.0, 1.0), 0.0) == (0.0, 0.0)
    assert pose_between((0.0, 0.0), (2.0, 1.0), 1.0) == (2.0, 1.0)
    assert pose_between((0.0, 0.0), (2.0, 1.0), 0.25) == (0.5, 0.25)


def test_the_azimuth_goes_the_short_way_round():
    """Two degrees apart across the wrap is a two degree turn, not 358."""
    a, b = math.radians(179.0), math.radians(-179.0)
    mid = pose_between((a, 0.0), (b, 0.0), 0.5)[0]
    assert math.degrees(mid) == pytest.approx(180.0)


def test_the_ease_starts_fast_and_settles():
    assert eased(0.0) == 0.0
    assert eased(1.0) == 1.0
    assert eased(0.5) > 0.5, "an ease-out is more than half done halfway"
    assert all(eased(t) < eased(t + 0.1) for t in (0.0, 0.3, 0.6, 0.85))


# --- and what the pane does with it

def test_the_swipe_sets_off_a_flight_rather_than_jumping(view):
    v, _ = view
    start = (v.camera.azimuth, v.camera.elevation)
    _flight_from(v)
    assert v.flying
    assert (v.camera.azimuth, v.camera.elevation) == start


def test_it_is_partway_there_partway_through(view):
    """And turning the way the swipe went: right, so azimuth winds down."""
    v, _ = view
    t0 = _flight_from(v, ms=200)
    v.advance_flight(t0 + 0.1)
    az = v.camera.azimuth
    assert v.flying
    assert -math.pi < az < STANDARD_VIEWS["perspective"][0]


def test_the_flight_lands_exactly_on_the_view(view):
    """Near enough is not good enough: the next swipe reads these angles."""
    v, _ = view
    t0 = _flight_from(v, ms=200)
    v.advance_flight(t0 + 0.25)
    assert not v.flying
    assert (v.camera.azimuth, v.camera.elevation) == STANDARD_VIEWS["left"]


def test_a_flat_pane_takes_the_named_view_on_arrival(view):
    """The label and the construction plane change when you get there."""
    v, _ = view
    v.set_view("top")
    seen = []
    v.viewChanged.connect(seen.append)
    t0 = _flight_from(v, ms=200)
    v.advance_flight(t0 + 0.1)
    assert seen == [], "it renamed the pane before the camera arrived"
    v.advance_flight(t0 + 0.25)
    assert seen == ["left"] and v._view_name == "left"
    assert v.camera.projection == "parallel"


def test_the_setting_turns_the_animation_off(view):
    v, _ = view
    _flight_from(v, ms=0)
    assert not v.flying
    assert (v.camera.azimuth, v.camera.elevation) == STANDARD_VIEWS["left"]


def test_the_next_click_lands_it_at_once(view):
    """Whatever you do next, you do it in the view you asked for."""
    v, _ = view
    _flight_from(v, ms=200)
    _press(v, Qt.MouseButton.LeftButton, NONE, (300.0, 200.0))
    assert not v.flying
    assert (v.camera.azimuth, v.camera.elevation) == STANDARD_VIEWS["left"]


def test_a_second_swipe_lands_the_first_and_turns_again(view):
    """Two flicks are two quarter turns, however fast they come. Turning
    from wherever the animation had got to would make the second one
    depend on how quick your hand was."""
    v, _ = view
    t0 = _flight_from(v, ms=200)
    v.advance_flight(t0 + 0.1)
    _flight_from(v, ms=200)
    assert (v.camera.azimuth, v.camera.elevation) == STANDARD_VIEWS["left"]
    v.land_flight()
    assert (v.camera.azimuth, v.camera.elevation) == STANDARD_VIEWS["back"]


def test_set_view_still_lands_at_once(view):
    """Scripts and the RPC bridge read the camera the moment they set it."""
    v, _ = view
    v.set_view("front")
    assert not v.flying
    assert (v.camera.azimuth, v.camera.elevation) == STANDARD_VIEWS["front"]
