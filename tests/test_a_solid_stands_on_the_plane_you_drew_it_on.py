"""A primitive is built on the plane you drew it on, not on world XY.

Every solid primitive read its base off the world X and Y axes and stood it
up the world Z axis, whichever pane you were working in. So a box started in
the Front pane never got anywhere: the two corners of its base differ in X
and Z there, the command saw no Y between them, and all you got was a rubber
line and a complaint about a zero width. The same went for the axis of a
cylinder, a cone, a torus and a helix, and for the ring `arraypolar` turns
its copies around.

The construction plane already knows which way is along and which way is up.
These ask it.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core.cplane import PRESETS
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


class _Pane:
    """A viewport that only knows its plane and where the cursor points."""

    def __init__(self, cplane=None, direction=(1.0, 1.0, 1.0)):
        self._cplane = cplane or PRESETS["top"]()
        self._dir = direction

    def aim_direction(self):
        d = np.asarray(self._dir, float)
        return ((0.0, 0.0, 0.0), tuple(d / np.linalg.norm(d)))

    def locked_direction(self):
        return None

    def active_cplane(self):
        return self._cplane


def _run(command, inputs, pane=None, scene=None, selection=None):
    """Run a command to the end, answering its prompts with typed text."""
    import serpentine3d.commands                             # noqa: F401
    scene = scene if scene is not None else Scene()
    selection = selection or SelectionManager(scene)
    ctx = CommandContext(scene, selection, History(scene),
                         viewport=pane or _Pane())
    said: list = []
    ctx.add_echo_listener(said.append)
    proc = CommandProcessor(ctx)
    proc.run(command)
    for text in inputs:
        assert proc.busy, \
            f"{command} ended before it was told {text!r}: {said}"
        proc.provide_text(text)
    return scene, said


def _sides(obj):
    lo, hi = obj.bbox()
    return tuple(round(h - l, 6) for l, h in zip(lo, hi))


def _front():
    # u runs along world X, v up world Z, and the normal comes at you down -Y
    return _Pane(PRESETS["front"]())


def _right():
    # u runs along world Y, v up world Z, and the normal runs along X
    return _Pane(PRESETS["right"]())


# -- box ---------------------------------------------------------------------

def test_a_box_typed_in_the_front_pane_comes_out_a_box():
    """The bug as it was met: it came out nothing at all."""
    scene, said = _run("box", ["0,0,0", "100", "50", "20"], _front())
    assert len(scene.all()) == 1, said
    assert _sides(scene.all()[0]) == (100.0, 20.0, 50.0)


def test_a_box_clicked_out_in_the_front_pane_lies_in_that_pane():
    scene, said = _run("box", ["0,0,0", "30,0,20", "10"], _front())
    assert len(scene.all()) == 1, said
    assert _sides(scene.all()[0]) == (30.0, 10.0, 20.0)


def test_a_box_in_the_right_pane_stands_up_out_of_that_pane():
    scene, said = _run("box", ["0,0,0", "40", "30", "10"], _right())
    assert len(scene.all()) == 1, said
    assert _sides(scene.all()[0]) == (10.0, 40.0, 30.0)


def test_a_box_in_the_top_pane_is_what_it_always_was():
    scene, said = _run("box", ["0,0,0", "100", "50", "20"])
    assert len(scene.all()) == 1, said
    assert _sides(scene.all()[0]) == (100.0, 50.0, 20.0)


# -- the round ones ----------------------------------------------------------

def test_a_cylinder_in_the_right_pane_lies_along_that_pane_s_normal():
    scene, said = _run("cylinder", ["0,0,0", "10", "30"], _right())
    assert len(scene.all()) == 1, said
    assert _sides(scene.all()[0]) == (30.0, 20.0, 20.0)


def test_a_cone_in_the_right_pane_points_along_that_pane_s_normal():
    scene, said = _run("cone", ["0,0,0", "10", "30"], _right())
    assert len(scene.all()) == 1, said
    assert _sides(scene.all()[0]) == (30.0, 20.0, 20.0)


def test_a_torus_in_the_front_pane_is_a_ring_you_can_see():
    """Drawn in Front and left on world XY it is a ring seen edge on, which
    is a line, and not what anyone drew."""
    scene, said = _run("torus", ["0,0,0", "20", "5"], _front())
    assert len(scene.all()) == 1, said
    x, y, z = _sides(scene.all()[0])
    # OCC boxes a torus generously across the ring and tightly along its
    # axis, so the ring is measured by which way is thin
    assert y == pytest.approx(10.0, abs=1e-6)
    assert x == pytest.approx(z, abs=1e-6)
    assert x >= 50.0


def test_a_helix_in_the_front_pane_winds_around_that_pane_s_normal():
    scene, said = _run("helix", ["0,0,0", "10", "4", "2"], _front())
    assert len(scene.all()) == 1, said
    x, y, z = _sides(scene.all()[0])
    # the rise is measured along the axis, and the box a curve gets is drawn
    # a little wide of it in the two directions it winds through
    assert y == pytest.approx(8.0, abs=1e-3)      # two turns at a pitch of 4
    assert min(x, z) >= 20.0


def test_the_round_ones_in_the_top_pane_are_what_they_always_were():
    scene, said = _run("cylinder", ["0,0,0", "10", "30"])
    assert _sides(scene.all()[0]) == (20.0, 20.0, 30.0), said


# -- arraypolar --------------------------------------------------------------

def _ringed(pane):
    from serpentine3d.core import geometry as g
    scene = Scene()
    seed = scene.add(g.make_box((10.0, -1.0, -1.0), 2.0, 2.0, 2.0))
    selection = SelectionManager(scene)
    selection.set([seed.id])
    _run("arraypolar", ["0,0,0", "4", "360"], pane, scene, selection)
    return scene


def test_arraypolar_turns_its_copies_around_the_plane_you_are_on():
    """Four around a Front pane is a ring you are looking straight at. Turned
    about world Z instead, three of the four land somewhere off in Y."""
    scene = _ringed(_front())
    assert len(scene.all()) == 4
    for obj in scene.all():
        lo, hi = obj.bbox()
        assert lo[1] == pytest.approx(-1.0, abs=1e-6)
        assert hi[1] == pytest.approx(1.0, abs=1e-6)
    reach = [round(obj.bbox()[1][2], 6) for obj in scene.all()]
    assert max(reach) == pytest.approx(12.0, abs=1e-6)


def test_arraypolar_in_the_top_pane_is_what_it_always_was():
    scene = _ringed(_Pane())
    assert len(scene.all()) == 4
    for obj in scene.all():
        lo, hi = obj.bbox()
        assert lo[2] == pytest.approx(-1.0, abs=1e-6)
        assert hi[2] == pytest.approx(1.0, abs=1e-6)
