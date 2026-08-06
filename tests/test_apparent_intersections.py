"""The crossing you can see but cannot touch.

Two curves that pass one over the other do not meet, so `int` has nothing
to offer at the place they cross on screen, and that place is often the
one you want: the point where a rafter passes over a wall, read off a Top
view. An apparent intersection is that point, and because it is made by
where you are standing it has to be worked out from the camera every time
rather than cached with the scene like a real one.
"""

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.core.snaps import SNAP_TYPES, SnapIndex
from serpentine3d.ui.camera import STANDARD_VIEWS


def _vp(scene):
    from serpentine3d.ui.viewport import Viewport
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(900, 700)
    vp.camera.target = np.zeros(3)
    vp.camera.distance = 60.0
    vp.point_axis = None
    return vp


def _look(vp, name):
    # set_standard_view, not just the angles: a named view is orthographic
    # in this app, and that is the view you read a crossing off
    vp.camera.set_standard_view(name)
    vp.camera._vp_cache = None


def _px(vp, world):
    scr = vp.camera.project(np.asarray([world], float),
                            vp.width(), vp.height())[0]
    return float(scr[0]), float(scr[1])


def _index(scene, **on):
    idx = SnapIndex(scene)
    for t in SNAP_TYPES:
        idx.types[t] = False
    for t, v in on.items():
        idx.types[t] = v
    return idx


def _find(idx, vp, px, py):
    return idx.find(vp.camera, px, py, vp.width(), vp.height())


# Top is 89.9 degrees, not 90, so the camera leans a tenth of a degree off
# straight down and two things at different heights do not quite stack up
# on screen. The crossing slides sideways by the height between them times
# tan(0.1 deg), about 0.017 per 10 units, and that is the drawing being
# honest rather than a snap being sloppy. Everything below is checked to a
# hair either side of that.
LEAN = 0.05


@pytest.fixture
def crossing():
    """A rail along X at z=0 and one along Y at z=8, seen from the top.

    They cross over the origin on screen and are eight apart in space.
    Neither is centred on the crossing, so no end or midpoint of either
    is sitting on the answer to flatter it."""
    scene = Scene()
    scene.add(g.make_line((-6.0, 0.0, 0.0), (30.0, 0.0, 0.0)))
    scene.add(g.make_line((0.0, -6.0, 8.0), (0.0, 30.0, 8.0)))
    vp = _vp(scene)
    _look(vp, "top")
    return scene, vp


# -- the snap itself --

def test_two_curves_that_miss_still_cross_on_screen(crossing):
    scene, vp = crossing
    idx = _index(scene, appint=True)
    px, py = _px(vp, (0.0, 0.0, 0.0))
    hit = _find(idx, vp, px, py)
    assert hit is not None
    assert hit[1] == "appint"
    assert hit[0][0] == pytest.approx(0.0, abs=1e-6)
    assert hit[0][1] == pytest.approx(0.0, abs=LEAN)


def test_the_point_lands_on_the_curve_nearest_the_camera(crossing):
    """One of the two is in front of the other, and the near one is the
    one you can see at that pixel. Landing on the far one would put the
    point behind something you are looking at."""
    scene, vp = crossing
    idx = _index(scene, appint=True)
    px, py = _px(vp, (0.0, 0.0, 0.0))
    hit = _find(idx, vp, px, py)
    assert hit[0][2] == pytest.approx(8.0, abs=1e-6)

    _look(vp, "bottom")
    hit = _find(idx, vp, *_px(vp, (0.0, 0.0, 0.0)))
    assert hit is not None
    assert hit[0][2] == pytest.approx(0.0, abs=1e-6)


def test_it_is_off_until_you_ask_for_it():
    """It is a specialist's snap and it fires wherever two lines happen to
    line up, so it is not one of the ones that start switched on."""
    assert SnapIndex(Scene()).types["appint"] is False


def test_switched_off_the_crossing_is_not_there(crossing):
    scene, vp = crossing
    idx = _index(scene, end=True, mid=True, int=True)
    assert _find(idx, vp, *_px(vp, (0.0, 0.0, 0.0))) is None


def test_turn_the_view_and_the_crossing_goes_away(crossing):
    """It is made by where you are standing, so it does not survive
    standing somewhere else."""
    scene, vp = crossing
    idx = _index(scene, appint=True)
    px, py = _px(vp, (0.0, 0.0, 0.0))
    _look(vp, "front")
    assert _find(idx, vp, px, py) is None


def test_the_cursor_has_to_be_near_the_crossing(crossing):
    scene, vp = crossing
    idx = _index(scene, appint=True)
    px, py = _px(vp, (0.0, 0.0, 0.0))
    assert _find(idx, vp, px + 120.0, py) is None


def test_perspective_puts_the_point_where_the_curve_really_is():
    """Halfway across the screen is not halfway along the rail.

    A perspective view packs the far half of a line into fewer pixels, so
    the fraction the crossing sits at on screen is not the fraction it sits
    at in space. Both rails here run through one pixel and the near one runs
    through a point worked out in advance, so a snap that took the screen
    fraction for the real one would land off the rail altogether.
    """
    scene = Scene()
    vp = _vp(scene)
    _look(vp, "perspective")
    far = np.array([4.0, -2.0, 0.0])
    eye = np.asarray(vp.camera.position, float)
    near = eye + 0.6 * (far - eye)      # same pixel, nearer the camera

    def line(mid, along):
        d = np.asarray(along, float) * 10.0
        return g.make_line(tuple(float(v) for v in mid - d),
                           tuple(float(v) for v in mid + d))

    scene.add(line(far, (1.0, 0.0, 0.0)))
    scene.add(line(near, (0.0, 1.0, 0.0)))
    idx = _index(scene, appint=True)
    hit = _find(idx, vp, *_px(vp, tuple(far)))
    assert hit is not None
    assert hit[1] == "appint"
    assert np.allclose(hit[0], near, atol=1e-6)


def test_a_long_run_of_segments_is_not_skipped():
    """Objects big enough to be worth it are rejected on eight corners
    rather than every segment, and the corners have to be a box the object
    genuinely fits in or the crossing goes missing."""
    xs = np.linspace(-20.0, 20.0, 40)      # 39 legs, past the cull's floor
    scene = Scene()
    scene.add(g.make_polyline([(float(x), 0.0, 0.0) for x in xs]))
    scene.add(g.make_line((0.0, -10.0, 9.0), (0.0, 10.0, 9.0)))
    vp = _vp(scene)
    _look(vp, "top")
    idx = _index(scene, appint=True)
    hit = _find(idx, vp, *_px(vp, (0.0, 0.0, 0.0)))
    assert hit is not None
    assert hit[1] == "appint"
    assert hit[0][0] == pytest.approx(0.0, abs=1e-6)
    assert hit[0][2] == pytest.approx(9.0, abs=1e-9)


# -- what is not an apparent intersection --

def test_curves_that_really_meet_offer_nothing(crossing):
    """Where they touch it is a plain intersection, which `int` has had
    all along. Offering it twice under two names would only make you
    wonder which one you got."""
    scene = Scene()
    scene.add(g.make_line((-20.0, 0.0, 0.0), (20.0, 0.0, 0.0)))
    scene.add(g.make_line((0.0, -20.0, 0.0), (0.0, 20.0, 0.0)))
    vp = _vp(scene)
    _look(vp, "top")
    idx = _index(scene, appint=True)
    assert _find(idx, vp, *_px(vp, (0.0, 0.0, 0.0))) is None


def test_a_real_intersection_is_still_called_int():
    scene = Scene()
    scene.add(g.make_line((-20.0, 0.0, 0.0), (20.0, 0.0, 0.0)))
    scene.add(g.make_line((0.0, -20.0, 0.0), (0.0, 20.0, 0.0)))
    vp = _vp(scene)
    _look(vp, "top")
    idx = _index(scene, int=True, appint=True)
    hit = _find(idx, vp, *_px(vp, (0.0, 0.0, 0.0)))
    assert hit is not None and hit[1] == "int"


def test_a_corner_of_one_polyline_is_not_a_crossing():
    """Two legs of a polyline share a vertex, so every corner in the
    drawing would be offered as a crossing of the run with itself."""
    scene = Scene()
    scene.add(g.make_polyline([(0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
                               (10.0, 10.0, 0.0)]))
    vp = _vp(scene)
    _look(vp, "top")
    idx = _index(scene, appint=True)
    assert _find(idx, vp, *_px(vp, (10.0, 0.0, 0.0))) is None


def test_lines_that_run_together_on_screen_offer_nothing():
    scene = Scene()
    scene.add(g.make_line((-20.0, 0.0, 0.0), (20.0, 0.0, 0.0)))
    scene.add(g.make_line((-20.0, 0.0, 9.0), (20.0, 0.0, 9.0)))
    vp = _vp(scene)
    _look(vp, "top")
    idx = _index(scene, appint=True)
    assert _find(idx, vp, *_px(vp, (0.0, 0.0, 0.0))) is None


# -- one curve crossing itself --

def test_a_curve_that_passes_over_itself():
    """A run that climbs as it comes back round misses itself in space and
    crosses itself on screen, which is the same question asked of one
    object instead of two."""
    scene = Scene()
    scene.add(g.make_polyline([(-10.0, 0.0, 0.0), (10.0, 0.0, 0.0),
                               (10.0, 10.0, 4.0), (0.0, 10.0, 6.0),
                               (0.0, -10.0, 8.0)]))
    vp = _vp(scene)
    _look(vp, "top")
    idx = _index(scene, appint=True)
    hit = _find(idx, vp, *_px(vp, (0.0, 0.0, 0.0)))
    assert hit is not None
    assert hit[1] == "appint"
    # the leg coming back over the top is the near one, and it is at 7
    # where it passes over the first leg
    assert np.allclose(hit[0], (0.0, 0.0, 7.0), atol=LEAN)


# -- edges of solids count too --

def test_a_line_can_cross_the_edge_of_a_solid():
    """The edges of a box are not curve objects, and they are still lines
    you can see, so a curve passing over one crosses something."""
    scene = Scene()
    scene.add(g.make_box((-5.0, -5.0, 0.0), 10.0, 10.0, 10.0))
    scene.add(g.make_line((0.0, -14.0, 20.0), (0.0, 14.0, 20.0)))
    vp = _vp(scene)
    _look(vp, "top")
    idx = _index(scene, appint=True)
    hit = _find(idx, vp, *_px(vp, (0.0, 5.0, 20.0)))
    assert hit is not None
    assert hit[1] == "appint"
    assert np.allclose(hit[0], (0.0, 5.0, 20.0), atol=LEAN)
    # the line is flat, so the height it lands at is exact either way
    assert hit[0][2] == pytest.approx(20.0, abs=1e-9)


# -- it is wired into the app like the others --

def test_the_osnap_bar_has_a_button_for_it(qapp_bar):
    bar = qapp_bar
    assert "appint" in bar._buttons
    assert bar._buttons["appint"].text()


def test_the_osnap_command_offers_it():
    from serpentine3d.commands.view import _OSNAP_KINDS
    assert "AppInt" in _OSNAP_KINDS


def test_it_has_a_marker_of_its_own():
    from serpentine3d.ui.viewport import _snap_marker
    c = np.zeros(3)
    right = np.array([1.0, 0.0, 0.0])
    up = np.array([0.0, 1.0, 0.0])
    mine = _snap_marker("appint", c, right, up, 6.0)
    theirs = _snap_marker("int", c, right, up, 6.0)
    assert len(mine)
    assert np.asarray(mine).shape != np.asarray(theirs).shape or \
        not np.allclose(np.asarray(mine), np.asarray(theirs))


def test_the_setting_is_remembered():
    from serpentine3d.utils.config import DEFAULTS
    assert DEFAULTS["osnaps"]["appint"] is False


@pytest.fixture
def qapp_bar(monkeypatch, tmp_path):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    from serpentine3d.ui.osnap_bar import OsnapBar
    scene = Scene()
    vp = _vp(scene)
    bar = OsnapBar(vp, None)
    yield bar
    bar.deleteLater()
