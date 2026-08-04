"""At a corner prompt a typed number is a side, not a distance to the corner.

Box and rectangle both read "or length" at their second corner in Rhino: type
one number and you are asked for the width, so a 100 cube is `box`, a corner,
then 100 three times.

The general rule for a point prompt is that a number is how far along the way
you are pointing, which is right at the end of a line and wrong here. It would
make 100 the diagonal rather than the side, and with ortho on — where the
cursor is square to the CPlane and the two corners share a coordinate — it
collapses the base to a line and the command complains about a zero height
nobody had been asked for yet.
"""

import numpy as np
import pytest

from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


class _Aiming:
    """A viewport that is only pointing somewhere, which is all this needs."""

    def __init__(self, direction=(1.0, 1.0, 0.0), cplane=None):
        self._dir = direction
        self._cplane = cplane or CPlane()

    def aim_direction(self):
        if self._dir is None:
            return None
        d = np.asarray(self._dir, float)
        return ((0.0, 0.0, 0.0), tuple(d / np.linalg.norm(d)))

    def locked_direction(self):
        return None

    def active_cplane(self):
        return self._cplane


def _run(command, inputs, viewport=None):
    """Run a command to the end, answering its prompts with typed text."""
    import serpentine3d.commands                             # noqa: F401
    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene),
                         viewport=viewport or _Aiming())
    said = []
    ctx.add_echo_listener(said.append)
    proc = CommandProcessor(ctx)
    proc.run(command)
    for text in inputs:
        assert proc.busy, \
            f"{command} ended before it was told {text!r}: {said}"
        proc.provide_text(text)
    return scene, proc, said


def _sides(obj):
    lo, hi = obj.bbox()
    return tuple(round(h - l, 6) for l, h in zip(lo, hi))


# -- box --

def test_a_typed_length_and_width_give_the_base_those_sides():
    scene, _proc, said = _run("box", ["0,0,0", "100", "50", "20"])
    assert len(scene.all()) == 1, said
    assert _sides(scene.all()[0]) == (100.0, 50.0, 20.0)


def test_the_second_corner_offers_the_length():
    """A prompt that does not say so is a feature nobody finds."""
    import serpentine3d.commands                             # noqa: F401
    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene),
                         viewport=_Aiming())
    proc = CommandProcessor(ctx)
    proc.run("box")
    proc.provide_text("0,0,0")
    assert "length" in proc.prompt_text().lower()


def test_the_base_runs_the_way_the_cursor_is_pointing():
    """Which quadrant the sides go into is the one thing the number does not
    say, and the cursor has been saying it all along."""
    scene, _proc, said = _run("box", ["0,0,0", "100", "50", "20"],
                              viewport=_Aiming((-1.0, -1.0, 0.0)))
    lo, hi = scene.all()[0].bbox()
    assert lo[0] == pytest.approx(-100.0, abs=1e-5)
    assert lo[1] == pytest.approx(-50.0, abs=1e-5)
    assert hi[0] == pytest.approx(0.0, abs=1e-5)
    assert hi[1] == pytest.approx(0.0, abs=1e-5)


def test_with_the_cursor_nowhere_the_sides_run_positive():
    """Typed into a batch or over the bridge there is no cursor to ask."""
    scene, _proc, said = _run("box", ["0,0,0", "100", "50", "20"],
                              viewport=_Aiming(None))
    assert _sides(scene.all()[0]) == (100.0, 50.0, 20.0)
    lo, _hi = scene.all()[0].bbox()
    assert lo[0] == pytest.approx(0.0, abs=1e-5)
    assert lo[1] == pytest.approx(0.0, abs=1e-5)


def test_the_width_can_still_be_dragged():
    """It is a distance in the model like any other, so a point answers it."""
    import serpentine3d.commands                             # noqa: F401
    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene),
                         viewport=_Aiming())
    proc = CommandProcessor(ctx)
    proc.run("box")
    proc.provide_text("0,0,0")
    proc.provide_text("100")
    proc.provide((60.0, 40.0, 0.0))          # a click, not a number
    proc.provide_text("20")
    assert _sides(scene.all()[0]) == (100.0, 40.0, 20.0)


def test_clicking_both_corners_is_untouched():
    scene, _proc, said = _run("box", ["0,0,0", "30,20", "10"])
    assert _sides(scene.all()[0]) == (30.0, 20.0, 10.0), said


def test_a_zero_side_says_which_one():
    """It used to report a zero height whatever had actually been zero,
    which sends you looking at the wrong number."""
    _scene, _proc, said = _run("box", ["0,0,0", "0"])
    assert "length" in said[-1].lower(), said[-1]


# -- rectangle --

def test_a_rectangle_takes_a_length_and_a_width_too():
    scene, _proc, said = _run("rectangle", ["0,0,0", "100", "50"])
    assert len(scene.all()) == 1, said
    assert _sides(scene.all()[0])[:2] == (100.0, 50.0)


def test_a_rectangle_measures_its_sides_on_the_plane_it_is_drawn_on():
    """A rectangle on a tilted CPlane has sides of its own; the world's idea
    of them is a pair of shadows."""
    tilted = CPlane(origin=(0.0, 0.0, 0.0), normal=(0.0, 1.0, 0.0))
    scene, _proc, said = _run("rectangle", ["0,0,0", "100", "50"],
                              viewport=_Aiming(cplane=tilted))
    assert len(scene.all()) == 1, said
    lo, hi = scene.all()[0].bbox()
    span = sorted(round(h - l, 6) for l, h in zip(lo, hi))
    assert span[0] == pytest.approx(0.0, abs=1e-6), "flat on its own plane"
    assert span[1:] == [50.0, 100.0]
