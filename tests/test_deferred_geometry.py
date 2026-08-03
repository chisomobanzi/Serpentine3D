"""Geometry on a switched-off layer is read but not converted (#5).

Not meshing what nothing draws was the first half. This is the second: a
drawing opened with most of it switched off should not pay to turn that
part into OCC geometry either. On a 61 MB survey file the hidden objects
are 3% of the count and 24% of the import, because what people switch off
is the heavy reference geometry.

So an object on a hidden layer arrives holding a `DeferredShape` — what
the file said, and how to convert it — and the conversion happens when
something asks: ticking the layer back on, or any code reading `.shape`.
The point of the exercise is that it never happens if nobody asks.
"""

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.deferred import DeferredShape
from serpentine3d.core.scene import Scene


def _box():
    return g.make_box((0, 0, 0), 10, 10, 10)


@pytest.fixture
def scene():
    return Scene()


# -- the placeholder itself --

def test_it_does_not_convert_on_the_way_in():
    calls = []
    DeferredShape(lambda: calls.append(1) or [_box()], kind="solid")
    assert calls == [], "converted something nobody asked for"


def test_it_converts_when_asked():
    d = DeferredShape(lambda: [_box()], kind="solid")
    assert len(d.shapes()) == 1


def test_it_converts_once():
    calls = []

    def build():
        calls.append(1)
        return [_box()]

    d = DeferredShape(build, kind="solid")
    first, second = d.shapes(), d.shapes()
    assert calls == [1], "converted twice"
    assert first[0] is second[0]


def test_it_says_whether_it_has_converted():
    d = DeferredShape(lambda: [_box()], kind="solid")
    assert not d.ready
    d.shapes()
    assert d.ready


def test_it_carries_the_kind_the_file_claimed():
    """So the scene can name and count an object it has not converted."""
    d = DeferredShape(lambda: [_box()], kind="solid")
    assert d.kind == "solid"


# -- an object holding one --

def test_adding_one_does_not_convert_it(scene):
    calls = []
    d = DeferredShape(lambda: calls.append(1) or [_box()], kind="solid")
    obj = scene.add(d, name="Reference")

    assert calls == []
    assert obj.kind == "solid"
    assert obj.name == "Reference"
    assert not obj.shape_ready


def test_it_counts_and_lists_like_any_other_object(scene):
    scene.add(DeferredShape(lambda: [_box()], kind="solid"))
    assert len(scene.all()) == 1


def test_reading_the_shape_converts_it(scene):
    obj = scene.add(DeferredShape(lambda: [_box()], kind="solid"))
    shape = obj.shape

    assert shape is not None
    assert not isinstance(shape, DeferredShape)
    assert obj.shape_ready
    assert obj.shape is shape, "converted again on the second read"


def test_a_real_shape_is_ready_from_the_start(scene):
    obj = scene.add(_box())
    assert obj.shape_ready


def test_the_kind_is_corrected_from_the_geometry(scene):
    """The file's word is a guess until the shape exists. A curve claimed
    as a solid would sort, colour and pick as one for the rest of the
    session, so realising has the last word."""
    obj = scene.add(DeferredShape(lambda: [_box()], kind="curve"))
    scene.realise(obj.id)
    assert obj.kind == "solid"


# -- what realising does that a bare read cannot --

def test_geometry_that_converts_to_nothing_leaves_no_object(scene):
    """15% of the hidden objects in the survey file convert to nothing at
    all. Importing them eagerly never made an object for those; deferring
    them must not leave a drawing full of empty ones."""
    obj = scene.add(DeferredShape(lambda: [], kind="solid"))
    scene.realise(obj.id)
    assert scene.get(obj.id) is None
    assert scene.all() == []


def test_reading_the_shape_of_one_that_converts_to_nothing(scene):
    """A caller holding the object still gets an answer, and it is not the
    placeholder it just asked to have converted."""
    obj = scene.add(DeferredShape(lambda: [], kind="solid"))
    assert obj.shape is None
    assert obj.shape_ready


def test_geometry_that_converts_to_several_keeps_them_all(scene):
    """One Rhino object can come back as a sewn solid and a mesh fallback
    beside it. Eager import made two objects, so this must too."""
    obj = scene.add(DeferredShape(
        lambda: [_box(), g.make_box((20, 0, 0), 10, 10, 10)],
        kind="solid"), name="Twin")
    scene.realise(obj.id)

    assert len(scene.all()) == 2
    assert scene.get(obj.id) is not None, "the original should still be there"


def test_the_extra_objects_land_on_the_same_layer(scene):
    lay = scene.layers.create("Reference")
    obj = scene.add(DeferredShape(
        lambda: [_box(), g.make_box((20, 0, 0), 10, 10, 10)],
        kind="solid"), layer_id=lay.id)
    scene.realise(obj.id)

    assert {o.layer_id for o in scene.all()} == {lay.id}


def test_realising_something_already_real_is_a_no_op(scene):
    obj = scene.add(_box())
    assert scene.realise(obj.id) is obj
    assert len(scene.all()) == 1


# -- and the layer switch, which is what actually asks --

def test_switching_a_layer_on_converts_what_is_on_it(scene):
    lay = scene.layers.create("Reference")
    scene.layers.set_visible(lay.id, False)
    calls = []
    obj = scene.add(DeferredShape(lambda: calls.append(1) or [_box()],
                                  kind="solid"), layer_id=lay.id)
    assert calls == []

    scene.realise_layer(lay.id)

    assert calls == [1]
    assert obj.shape_ready


def test_switching_one_layer_on_leaves_the_others_alone(scene):
    off = scene.layers.create("Off")
    other = scene.layers.create("Still off")
    for lay in (off, other):
        scene.layers.set_visible(lay.id, False)
    a = scene.add(DeferredShape(lambda: [_box()], kind="solid"),
                  layer_id=off.id)
    b = scene.add(DeferredShape(lambda: [_box()], kind="solid"),
                  layer_id=other.id)

    scene.realise_layer(off.id)

    assert a.shape_ready
    assert not b.shape_ready


def test_a_layer_of_real_objects_costs_nothing_to_realise(scene):
    lay = scene.layers.create("Ordinary")
    scene.add(_box(), layer_id=lay.id)
    assert scene.realise_layer(lay.id) == 0


def test_realise_layer_reports_how_many_it_converted(scene):
    lay = scene.layers.create("Reference")
    for _ in range(3):
        scene.add(DeferredShape(lambda: [_box()], kind="solid"),
                  layer_id=lay.id)
    assert scene.realise_layer(lay.id) == 3


# -- and the object switch, which is what most of them are waiting on --

def test_unhiding_an_object_converts_it(scene):
    """On the real survey file 266 of the 280 deferred objects are hidden
    one by one on a layer that is switched on, so this is the trigger that
    matters, not the layer one. It also has to happen here rather than when
    the viewport gets round to drawing: realising can remove the object, and
    the draw path is no place to find that out."""
    calls = []
    obj = scene.add(DeferredShape(lambda: calls.append(1) or [_box()],
                                  kind="solid"))
    scene.update(obj.id, visible=False)

    scene.update(obj.id, visible=True)

    assert calls == [1]
    assert scene.get(obj.id).shape_ready


def test_unhiding_one_that_converts_to_nothing_leaves_no_object(scene):
    obj = scene.add(DeferredShape(lambda: [], kind="solid"))
    scene.update(obj.id, visible=False)

    scene.update(obj.id, visible=True)

    assert scene.get(obj.id) is None


def test_hiding_an_object_converts_nothing(scene):
    calls = []
    obj = scene.add(DeferredShape(lambda: calls.append(1) or [_box()],
                                  kind="solid"))
    scene.update(obj.id, visible=False)
    assert calls == []


def test_updating_something_else_converts_nothing(scene):
    calls = []
    obj = scene.add(DeferredShape(lambda: calls.append(1) or [_box()],
                                  kind="solid"))
    scene.update(obj.id, name="Renamed")
    assert calls == []


# -- and the things that walk the scene, which must not trip over one --

def test_an_object_left_holding_nothing_still_answers(scene):
    """Realising to nothing removes the object, but whoever was iterating
    still has it in hand. Asked to draw or measure itself it gives back an
    empty answer; the alternative is a crash inside the kernel."""
    obj = scene.add(DeferredShape(lambda: [], kind="solid"))
    assert obj.shape is None

    assert len(obj.mesh.vertices) == 0
    assert obj.bbox() == ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))



def test_the_bounding_box_skips_what_is_hidden(scene):
    """`Scene.bbox` measures what is shown, and measuring is a read of the
    shape. A hidden layer must not be converted by a zoom extents."""
    lay = scene.layers.create("Reference")
    scene.layers.set_visible(lay.id, False)
    obj = scene.add(DeferredShape(lambda: [_box()], kind="solid"),
                    layer_id=lay.id)
    scene.add(g.make_box((0, 0, 0), 1, 1, 1))

    scene.bbox()

    assert not obj.shape_ready


def test_a_hidden_deferred_object_is_not_a_visible_object(scene):
    lay = scene.layers.create("Reference")
    scene.layers.set_visible(lay.id, False)
    obj = scene.add(DeferredShape(lambda: [_box()], kind="solid"),
                    layer_id=lay.id)
    assert obj not in scene.visible_objects()


def test_a_snapshot_of_a_deferred_object_does_not_convert_it(scene):
    calls = []
    obj = scene.add(DeferredShape(lambda: calls.append(1) or [_box()],
                                  kind="solid"))
    scene.snapshot()
    assert calls == []
    assert not obj.shape_ready


def test_undo_does_not_convert_it_a_second_time(scene):
    """A clone shares the placeholder, so the work already done comes back
    with it rather than being paid for again."""
    calls = []
    obj = scene.add(DeferredShape(lambda: calls.append(1) or [_box()],
                                  kind="solid"))
    snap = scene.snapshot()
    obj.shape
    scene.restore(snap)

    assert scene.all()[0].shape is not None
    assert calls == [1]


def test_setting_a_shape_by_hand_clears_the_placeholder(scene):
    obj = scene.add(DeferredShape(lambda: [_box()], kind="solid"))
    obj.shape = g.make_box((0, 0, 0), 2, 2, 2)
    assert obj.shape_ready
    (lo, hi) = obj.bbox()
    assert np.allclose(hi, (2, 2, 2))
