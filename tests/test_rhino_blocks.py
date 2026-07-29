"""Blocks (instance references) coming in from a .3dm.

A block is a definition kept once and placed many times. Serpentine3D has no
block object of its own, so an instance comes in as its content, transformed
into place — the same trade Rhino's own Explode makes.

Before this, an instance imported as nothing at all and the definition's
members imported as loose objects sitting at the definition's origin. A
drawing that placed one block fifty times gave you one ghost copy at the
origin and none of the fifty. See tests/data/make_blocks.py for the fixture.
"""

import os

import numpy as np
import pytest

from serpentine3d.core.tessellate import tessellate
from serpentine3d.fileio import rhino_parallel as rp
from serpentine3d.fileio.rhino import import_3dm

FIXTURE = os.path.join(os.path.dirname(__file__), "data", "blocks.3dm")

BLOCKS_RED = (200 / 255.0, 40 / 255.0, 40 / 255.0)
STEEL_BLUE = (40 / 255.0, 40 / 255.0, 200 / 255.0)
INSTANCE_GREEN = (30 / 255.0, 200 / 255.0, 60 / 255.0)


def _bbox(shape):
    pts = tessellate(shape).vertices
    if not len(pts):
        pts = np.array([[0.0, 0.0, 0.0]])
    return np.min(pts, axis=0), np.max(pts, axis=0)


@pytest.fixture(scope="module")
def imported():
    return import_3dm(FIXTURE)


@pytest.fixture(scope="module")
def by_name(imported):
    out = {}
    for name, shape, meta in imported:
        out.setdefault(name, []).append((shape, meta))
    return out


def test_the_fixture_is_there():
    assert os.path.exists(FIXTURE), \
        "run tests/data/make_blocks.py to rebuild the fixture"


def test_a_placed_block_arrives_at_all(by_name):
    """Four instances were placed. None of them used to arrive."""
    placed = [n for n in by_name
              if n.startswith(("widget", "squashed", "assembly"))]
    assert placed, "every block instance was dropped on import"


def test_the_definitions_content_does_not_leak_in_on_its_own(by_name):
    """The box, mast and rail exist only as part of an instance.

    They used to import as loose objects at the definition's origin, so a
    drawing came in with one ghost copy of every block whether or not it was
    ever placed.
    """
    for member in ("body", "mast", "rail"):
        assert member not in by_name, \
            f"{member!r} came in as a top-level object of its own"


def test_ordinary_objects_are_untouched(by_name):
    assert "loose line" in by_name


def test_each_instance_brings_the_whole_definition(by_name):
    """The widget is a box and a mast, so an instance of it is two shapes."""
    for name in ("widget 1", "widget 2"):
        parts = [p for n, p in by_name.items() if n.startswith(name)]
        assert sum(len(p) for p in parts) == 2, f"{name} arrived incomplete"


def test_an_instance_lands_where_it_was_placed(by_name):
    """widget 1 sits at x=10 and widget 2 at x=20, not both at the origin."""
    def solid_at(prefix):
        for name, entries in by_name.items():
            if not name.startswith(prefix):
                continue
            for shape, _ in entries:
                lo, hi = _bbox(shape)
                if np.all(hi - lo > 1.0):          # the box, not the mast
                    return lo, hi
        raise AssertionError(f"no solid found for {prefix}")

    lo1, hi1 = solid_at("widget 1")
    lo2, hi2 = solid_at("widget 2")
    assert lo1[0] == pytest.approx(10.0, abs=1e-6)
    assert lo2[0] == pytest.approx(20.0, abs=1e-6)
    assert hi1[2] == pytest.approx(2.0, abs=1e-6)


def test_an_unevenly_scaled_instance_keeps_its_shape(by_name):
    """Three times as tall as it is wide.

    Rhino lets you scale a block by different amounts per axis, which is not
    a similarity, so it cannot go through the transform used everywhere else.
    """
    for name, entries in by_name.items():
        if not name.startswith("squashed"):
            continue
        for shape, _ in entries:
            lo, hi = _bbox(shape)
            if np.all(hi - lo > 1.0):
                assert hi[0] - lo[0] == pytest.approx(2.0, abs=1e-6)
                assert hi[2] - lo[2] == pytest.approx(6.0, abs=1e-6)
                return
    raise AssertionError("the unevenly scaled instance did not arrive")


def test_a_block_inside_a_block_is_placed_through_both(by_name):
    """assembly holds a widget lifted 10 up, and sits 30 along Y itself.

    Its box should end up at y=30, z=10 — both transforms applied, in order.
    """
    for name, entries in by_name.items():
        if not name.startswith("assembly"):
            continue
        for shape, _ in entries:
            lo, hi = _bbox(shape)
            if np.all(hi - lo > 1.0):
                assert lo[1] == pytest.approx(30.0, abs=1e-6)
                assert lo[2] == pytest.approx(10.0, abs=1e-6)
                return
    raise AssertionError("the nested block never got placed")


def test_a_member_keeps_its_own_layer(by_name):
    """The box lives on 'steel' inside a definition placed on 'blocks'."""
    for name, entries in by_name.items():
        if not name.startswith("widget 1"):
            continue
        for shape, meta in entries:
            lo, hi = _bbox(shape)
            if np.all(hi - lo > 1.0):
                assert meta["layer"] == "steel"
                assert meta["layer_color"] == pytest.approx(STEEL_BLUE)
                return
    raise AssertionError("no widget 1 body found")


def test_a_member_coloured_by_parent_takes_the_instances_colour(by_name):
    """The mast's colour source is ColorFromParent.

    In widget 2, whose instance is green, the mast should be green. That
    source was read as 'no override' before, so it silently fell back to the
    mast's own layer and the instance's colour was thrown away.
    """
    masts = [(s, m) for name, entries in by_name.items()
             if name.startswith("widget 2")
             for s, m in entries if np.all(_bbox(s)[1] - _bbox(s)[0] < 1.0)]
    assert masts, "widget 2's mast did not arrive"
    assert masts[0][1]["color"] == pytest.approx(INSTANCE_GREEN)


def test_a_member_coloured_by_parent_falls_back_to_the_instances_layer(
        by_name):
    """widget 1 has no colour of its own, so its layer decides for the mast."""
    masts = [(s, m) for name, entries in by_name.items()
             if name.startswith("widget 1")
             for s, m in entries if np.all(_bbox(s)[1] - _bbox(s)[0] < 1.0)]
    assert masts, "widget 1's mast did not arrive"
    assert masts[0][1]["color"] == pytest.approx(BLOCKS_RED)


def test_parts_are_named_after_the_instance_that_placed_them(by_name):
    """You have to be able to find them again in the object list."""
    assert any(n.startswith("widget 1") for n in by_name)
    assert all(not n.startswith("3dm object") for n in by_name), \
        "block content came in unnamed"


def _summary(objects):
    """What an import came to, in a form two paths can be compared by."""
    out = []
    for name, shape, meta in objects:
        lo, hi = _bbox(shape)
        out.append((name, meta, tuple(np.round(lo, 6)),
                    tuple(np.round(hi, 6))))
    return out


def test_the_parallel_importer_places_blocks_the_same_way(imported):
    """A file past MIN_PARALLEL_BYTES converts in a pool of processes.

    Those workers hold their own copy of the model and resolve everything
    themselves, so a block has to be expanded there too. Otherwise the same
    drawing came in one way when it was small and another when it was big,
    which is worse than either path being wrong.
    """
    assert _summary(rp.import_3dm_parallel(FIXTURE, workers=2)) \
        == _summary(imported)
