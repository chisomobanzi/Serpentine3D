"""A typed number is a distance in the direction you are already aiming.

This is the other half of drawing by keyboard, and it was missing. A typed
length was taken only where the command named an axis of its own
(`number_from`) or where Tab had frozen one. Everywhere else — the end of a
line, the far corner of a box or a rectangle, the next vertex of a polyline —
a number came back as the coordinates hint and nothing moved, so a first
corner clicked with the mouse could not be finished from the keyboard at all.

Rhino calls it the distance constraint: the base point and the cursor already
say which way, so a number only has to say how far. Ortho comes along for the
ride, because the direction is read off the point the cursor resolves to and
that is where ortho has already been applied.
"""

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.commands.base import (CommandContext, CommandProcessor,
                                        PointReq, parse_value)
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager

AIM = (550, 220)             # a pixel off to one side of the base point


def _viewport(base=(0.0, 0.0, 0.0)):
    QApplication.instance() or QApplication([])
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    vp.set_point_mode(True)
    vp.snap_base = base
    return vp


def _ctx(vp):
    return CommandContext(vp.scene, SelectionManager(vp.scene),
                          History(vp.scene), viewport=vp)


def _cursor_at(vp, px=AIM[0], py=AIM[1]):
    """Stand in for a mouse move, which is where the viewport gets this.

    Nothing types a number without the cursor being somewhere first, and
    `aim_direction()` with no pixel is asked to read it off the last move.
    """
    from PySide6.QtCore import QPointF
    vp._last_mouse = QPointF(float(px), float(py))
    return vp


def _unit_to(vp, px, py):
    """The direction from the base to whatever that pixel resolves to."""
    d = np.asarray(vp.world_point_at(px, py), float) \
        - np.asarray(vp.snap_base, float)
    return d / np.linalg.norm(d)


# -- what the viewport answers --

def test_the_aim_runs_from_the_base_to_the_cursor():
    vp = _viewport()
    base, direction = vp.aim_direction(*AIM)
    assert np.allclose(base, vp.snap_base)
    assert np.allclose(direction, _unit_to(vp, *AIM), atol=1e-9)


def test_the_aim_is_the_point_the_cursor_resolves_to():
    """Read off `world_point_at`, so an aim over an object snap or an ortho
    direction is the one on screen and not a raw unproject of the pixel."""
    vp = _viewport()
    vp.ortho = True
    base, direction = vp.aim_direction(*AIM)
    assert np.allclose(direction, _unit_to(vp, *AIM), atol=1e-9)
    off_axis = sorted(abs(c) for c in direction)[:2]
    assert max(off_axis) < 1e-9, \
        "with ortho on the aim must be square to the CPlane, as the band is"


def test_there_is_no_aim_before_the_base_point_is_down():
    vp = _viewport()
    vp.snap_base = None
    assert vp.aim_direction(*AIM) is None


def test_there_is_no_aim_with_the_cursor_on_the_base_point():
    vp = _viewport()
    vp.snap_base = vp.world_point_at(*AIM)
    assert vp.aim_direction(*AIM) is None


def test_there_is_no_aim_before_the_cursor_has_been_over_the_viewport():
    """`aim_direction()` with no pixel falls back to the last mouse position,
    and until the mouse has moved there is not one."""
    vp = _viewport()
    assert vp.aim_direction() is None


# -- and what a typed number does with it --

def test_a_number_is_that_far_along_the_aim():
    vp = _cursor_at(_viewport())
    ok, pt = parse_value(PointReq("End of line"), "3400", _ctx(vp))
    assert ok, pt
    assert np.allclose(pt, np.asarray(vp.snap_base, float)
                       + 3400 * _unit_to(vp, *AIM), atol=1e-6)


def test_units_work_here_too():
    vp = _cursor_at(_viewport())
    ok, pt = parse_value(PointReq("End of line"), "30cm", _ctx(vp))
    assert ok, pt
    assert np.allclose(pt, np.asarray(vp.snap_base, float)
                       + 300 * _unit_to(vp, *AIM), atol=1e-6)


def test_the_first_point_of_a_command_still_takes_no_bare_number():
    """Nothing to measure from, so the coordinates hint is the right answer
    and always was."""
    vp = _viewport()
    vp.snap_base = None
    ok, msg = parse_value(PointReq("First corner of base"), "100", _ctx(vp))
    assert not ok
    assert "3,4,0" in msg


def test_a_command_with_an_axis_of_its_own_ignores_the_aim():
    """Extrude asks for its height along its own axis. Where the cursor
    happens to be pointing has no business bending that."""
    vp = _viewport()
    req = PointReq("Height", number_from=((0.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
    ok, pt = parse_value(req, "12", _ctx(vp))
    assert ok, pt
    assert np.allclose(pt, (0.0, 0.0, 12.0))


def test_a_prompt_that_wants_the_number_itself_still_gets_it():
    """Scale's factor is a number, not a length: 0.5 must stay 0.5 and not
    become a point half a millimetre away."""
    vp = _viewport()
    req = PointReq("Scale factor, or first reference point",
                   allow_number=True)
    ok, value = parse_value(req, "0.5", _ctx(vp))
    assert ok, value
    assert value == pytest.approx(0.5)


def test_the_tab_lock_beats_the_aim():
    """A frozen direction is a decision already made; the cursor moving on
    afterwards must not quietly undo it."""
    vp = _viewport()
    assert vp.toggle_direction_lock(*AIM)
    locked_base, locked_dir = vp.dir_lock
    vp._last_mouse = None                    # aim only from where we say
    ok, pt = parse_value(PointReq("End of line"), "100", _ctx(vp))
    assert ok, pt
    assert np.allclose(pt, np.asarray(locked_base, float)
                       + 100 * np.asarray(locked_dir, float), atol=1e-6)


# -- the bug as it was reported --

def _typed_after_a_click(name, text="100"):
    """The reported workflow: click the first point, aim, type the distance."""
    vp = _cursor_at(_viewport(base=None))
    ctx = _ctx(vp)
    proc = CommandProcessor(ctx)
    said = []
    ctx.add_echo_listener(said.append)
    import serpentine3d.commands                        # noqa: F401
    proc.run(name)
    proc.provide((0.0, 0.0, 0.0))
    vp.snap_base = (0.0, 0.0, 0.0)                      # what the app sets
    proc.provide_text(text)
    return proc, ctx, said


def test_a_line_started_with_the_mouse_finishes_from_the_keyboard():
    """It answered "Expected coordinates like 3,4,0" and stayed on the same
    prompt, so a line of a known length could not be drawn at all."""
    _proc, ctx, said = _typed_after_a_click("line", "3400")
    assert len(ctx.scene.all()) == 1, said
    lo, hi = ctx.scene.all()[0].bbox()
    length = np.linalg.norm(np.asarray(hi, float) - np.asarray(lo, float))
    assert length == pytest.approx(3400.0, abs=1e-4)


def test_a_box_corner_clicked_with_the_mouse_takes_a_typed_number_too():
    """Box reads its number as a side rather than a distance to the corner,
    so it asks for the width next — see test_typed_side_is_not_a_diagonal.
    What matters here is that the number is taken at all."""
    proc, _ctx, said = _typed_after_a_click("box")
    assert proc.prompt_text().startswith("Width"), \
        f"still stuck on the corner: {said[-1]}"
