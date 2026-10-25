"""Boundary mode for Hatch: pick the regions the curves make (#45).

Rhino's term for it. It is asked about only where the answer is not
already obvious: one closed curve is its own boundary, curves lying
apart make one hatch each, and a curve inside another is its hole, so
all three are filled straight away. Two outlines running through each
other leave regions nobody can guess at, and that is the pick: click a
region to keep it, click it again to let it go, All (Alt+A) for every
one, Enter to finish.

This is the same question CurveBoolean asks, asked from the same place
(commands/regions.py), so the two commands behave alike: what you learn
clicking regions in one works in the other.
"""

from __future__ import annotations

import math

import pytest

from serpentine3d.core import geometry as g


def _square(size=10.0, corner=(0.0, 0.0), z=0.0):
    x, y = corner
    return g.make_polyline([(x, y, z), (x + size, y, z),
                            (x + size, y + size, z), (x, y + size, z)],
                           closed=True)


def _pick(proc, *objs):
    for o in objs:
        proc.click_object(o.id)
    proc.finish_selection()


def _hatches(scene):
    return [o for o in scene.all() if o.kind == "hatch"]


def _area(obj):
    return g.surface_area(obj.shape)


# -- boundary mode off -----------------------------------------------------

def test_one_closed_curve_is_hatched_without_asking_which_region(env):
    scene, _sel, _hist, _ctx, proc = env
    outline = scene.add(_square(10.0), name="Outline")

    proc.run("hatch")
    _pick(proc, outline)
    proc.provide_text("Solid")

    assert len(_hatches(scene)) == 1
    assert _area(_hatches(scene)[0]) == pytest.approx(100.0, rel=1e-6)
    assert not proc.busy, "it never asked which region to keep"


# -- boundary mode on ------------------------------------------------------

def test_curves_lying_apart_are_each_filled_without_asking(env):
    scene, _sel, _hist, _ctx, proc = env
    a = scene.add(_square(10.0), name="A")
    b = scene.add(_square(10.0, corner=(20.0, 0.0)), name="B")

    proc.run("hatch")
    _pick(proc, a, b)
    proc.provide_text("Solid")

    assert len(_hatches(scene)) == 2, "nothing to decide, so nothing asked"


def test_many_curves_lying_apart_are_still_filled_without_asking(env):
    """However many there are: a sheet of separate outlines is as obvious
    as two of them, and was filled straight away before boundary mode."""
    scene, _sel, _hist, _ctx, proc = env
    squares = [scene.add(_square(10.0, corner=(20.0 * i, 0.0)), name=f"S{i}")
               for i in range(20)]

    proc.run("hatch")
    _pick(proc, *squares)
    assert "region" not in proc.request.prompt.lower(), proc.request.prompt
    proc.provide_text("Solid")

    assert len(_hatches(scene)) == 20


def test_a_curve_inside_another_is_its_hole_without_asking(env):
    scene, _sel, _hist, _ctx, proc = env
    outer = scene.add(_square(10.0), name="Outline")
    inner = scene.add(g.make_circle((5, 5, 0), 2.0), name="Island")

    proc.run("hatch")
    _pick(proc, outer, inner)
    proc.provide_text("Solid")

    hatches = _hatches(scene)
    assert len(hatches) == 1
    assert _area(hatches[0]) == pytest.approx(100.0 - math.pi * 4, rel=1e-3)


def test_two_overlapping_squares_ask_which_regions_to_fill(env):
    scene, _sel, _hist, _ctx, proc = env
    a = scene.add(_square(10.0), name="A")
    b = scene.add(_square(10.0, corner=(6.0, 0.0)), name="B")

    proc.run("hatch")
    _pick(proc, a, b)
    assert "region" in proc.request.prompt.lower(), proc.request.prompt

    proc.provide((8.0, 5.0, 0.0))      # the overlap
    proc.provide(None)                 # Enter
    proc.provide_text("Solid")

    hatches = _hatches(scene)
    assert len(hatches) == 1
    assert _area(hatches[0]) == pytest.approx(4.0 * 10.0, rel=1e-6)


def test_all_keeps_every_region(env):
    scene, _sel, _hist, _ctx, proc = env
    a = scene.add(_square(10.0), name="A")
    b = scene.add(_square(10.0, corner=(6.0, 0.0)), name="B")

    proc.run("hatch")
    _pick(proc, a, b)
    proc.provide_text("All")
    proc.provide(None)
    proc.provide_text("Solid")

    hatches = _hatches(scene)
    assert len(hatches) == 3, "left, overlap and right"
    assert sum(_area(h) for h in hatches) == pytest.approx(160.0, rel=1e-6)


def test_clicking_a_region_twice_lets_it_go(env):
    scene, _sel, _hist, _ctx, proc = env
    a = scene.add(_square(10.0), name="A")
    b = scene.add(_square(10.0, corner=(6.0, 0.0)), name="B")

    proc.run("hatch")
    _pick(proc, a, b)
    proc.provide((2.0, 5.0, 0.0))
    proc.provide((2.0, 5.0, 0.0))
    proc.provide((8.0, 5.0, 0.0))
    proc.provide(None)
    proc.provide_text("Solid")

    hatches = _hatches(scene)
    assert len(hatches) == 1
    assert _area(hatches[0]) == pytest.approx(40.0, rel=1e-6)


def test_finishing_with_nothing_kept_places_nothing(env):
    scene, _sel, _hist, ctx, proc = env
    said = []
    ctx.add_echo_listener(said.append)
    a = scene.add(_square(10.0), name="A")
    b = scene.add(_square(10.0, corner=(6.0, 0.0)), name="B")

    proc.run("hatch")
    _pick(proc, a, b)
    proc.provide(None)

    assert not _hatches(scene)
    assert any("no region" in m.lower() for m in said), said


def test_an_island_inside_a_crossing_pair_can_be_chosen(env):
    """Where the pick is on, every region is in it, the island among
    them: so a hole can be filled as a patch of its own after all."""
    scene, _sel, _hist, _ctx, proc = env
    a = scene.add(_square(10.0), name="A")
    b = scene.add(_square(10.0, corner=(6.0, 0.0)), name="B")
    scene.add(g.make_circle((3.0, 5.0, 0.0), 1.0), name="Island")

    proc.run("hatch")
    _pick(proc, *scene.all())
    proc.provide((3.0, 5.0, 0.0))      # inside the island itself
    proc.provide(None)
    proc.provide_text("Solid")

    hatches = _hatches(scene)
    assert len(hatches) == 1
    assert _area(hatches[0]) == pytest.approx(math.pi, rel=1e-3)


def test_the_curves_are_kept_and_what_was_made_is_selected(env):
    scene, sel, _hist, _ctx, proc = env
    a = scene.add(_square(10.0), name="A")
    b = scene.add(_square(10.0, corner=(6.0, 0.0)), name="B")

    proc.run("hatch")
    _pick(proc, a, b)
    proc.provide_text("All")
    proc.provide(None)
    proc.provide_text("Solid")

    assert scene.get(a.id) is not None and scene.get(b.id) is not None
    assert sorted(sel.ids) == sorted(h.id for h in _hatches(scene))
