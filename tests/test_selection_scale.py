"""Orbiting with a lot selected should cost what orbiting always costs.

On the 522 MB cave file a frame takes 121 ms with nothing selected and
1092 ms with all 7064 objects selected. Almost all of the difference is two
things that walk the selection every frame: the membership test the draw
loop runs once per drawn object, and the gumball working out where to sit
by taking the bounding box of every selected object again.

Neither is work the frame needs. The selection does not change while you
orbit, and the answers are the same every frame until it does.
"""

import time

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


def _boxes(scene, n, step=3.0):
    for i in range(n):
        scene.add(g.make_box((i * step, 0, 0), 1, 1, 1), name=f"b{i}")
    return [o.id for o in scene.all()]


def _viewport(scene, sel):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from serpentine3d.ui.viewport import Viewport
    vp = Viewport(scene, sel)
    vp.resize(800, 600)
    return vp


# ------------------------------------------------------- membership test

def test_is_selected_does_not_read_the_whole_selection():
    """The draw loop asks this once per object, so a linear scan makes a
    frame cost objects x selection — 190 ms of one on the cave file."""
    scene = Scene()
    sel = SelectionManager(scene)
    ids = _boxes(scene, 400)

    def elapsed(k):
        sel.set(ids[:k])
        probe = ids[-1]                     # never selected: the worst case
        t0 = time.perf_counter()
        for _ in range(20_000):
            sel.is_selected(probe)
        return time.perf_counter() - t0

    small = elapsed(4)
    large = elapsed(399)
    assert large < small * 4, (
        f"asking cost {large / small:.0f}x more with 399 selected than with "
        f"4 — the test is reading the selection, not indexing it")


def test_membership_survives_every_way_the_selection_changes():
    """Whatever it is indexed by has to be kept honest by all of them."""
    scene = Scene()
    sel = SelectionManager(scene)
    a, b, c = _boxes(scene, 3)

    sel.set([a, b])
    assert [sel.is_selected(i) for i in (a, b, c)] == [True, True, False]
    sel.toggle(c)
    sel.toggle(a)
    assert [sel.is_selected(i) for i in (a, b, c)] == [False, True, True]
    sel.clear()
    assert not any(sel.is_selected(i) for i in (a, b, c))
    sel.select_all()
    assert all(sel.is_selected(i) for i in (a, b, c))
    scene.remove(b)
    assert sel.ids == [a, c]                 # reading it prunes what is gone
    assert not sel.is_selected(b)


# ------------------------------------------------------- gumball anchor

@pytest.fixture
def counted_bbox(monkeypatch):
    calls = []
    real = g.bbox

    def spy(shape):
        calls.append(shape)
        return real(shape)
    monkeypatch.setattr(g, "bbox", spy)
    return calls


def test_the_gumball_measures_the_selection_once_not_once_a_frame(
        counted_bbox):
    scene = Scene()
    sel = SelectionManager(scene)
    vp = _viewport(scene, sel)
    ids = _boxes(scene, 30)
    sel.set(ids)

    first = vp.gumball.anchor_and_axes()
    counted_bbox.clear()
    for _ in range(5):                       # five frames of orbiting
        again = vp.gumball.anchor_and_axes()
    assert counted_bbox == [], (
        f"asked {len(counted_bbox)} times for bounds that had not changed")
    assert np.allclose(again[0], first[0])


def test_the_anchor_follows_the_selection(counted_bbox):
    scene = Scene()
    sel = SelectionManager(scene)
    vp = _viewport(scene, sel)
    ids = _boxes(scene, 4)

    sel.set(ids[:1])
    near = vp.gumball.anchor_and_axes()[0]
    sel.set(ids)
    far = vp.gumball.anchor_and_axes()[0]
    assert far[0] > near[0], "the gumball stayed on the first box"


def test_the_anchor_follows_geometry_that_moved(counted_bbox):
    """A cached centre that outlives the move puts the handle off the
    object it is meant to be attached to."""
    scene = Scene()
    sel = SelectionManager(scene)
    vp = _viewport(scene, sel)
    ids = _boxes(scene, 2)
    sel.set(ids)
    before = vp.gumball.anchor_and_axes()[0]

    obj = scene.get(ids[0])
    obj.shape = g.translate(obj.shape, (0, 0, 100))
    obj._mesh = None
    scene.notify("objects")
    after = vp.gumball.anchor_and_axes()[0]
    assert after[2] > before[2] + 1.0, "the gumball did not follow the move"


def test_an_empty_selection_has_no_anchor():
    scene = Scene()
    sel = SelectionManager(scene)
    vp = _viewport(scene, sel)
    _boxes(scene, 2)
    assert vp.gumball.anchor_and_axes() is None
