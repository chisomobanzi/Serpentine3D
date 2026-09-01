"""Drawing a section line across a model gives you the cut, as geometry.

This is how a section drawing starts: you draw a line across the plan
where you want the saw to go, and you get back the faces it went
through. The plane stands on that line and leans with the construction
plane, so the same two points drawn in Front cut vertically, which is
the way anyone coming from Rhino expects a section mark to behave.

What comes back is the cut face rather than its outline, so a hatch has
something to fill and a bore stays a bore. The objects you picked are
left alone: a section is a drawing of the model, not a change to it.
"""

from __future__ import annotations

import math

import pytest

from serpentine3d.core import geometry as g


def _areas(scene):
    """The cut faces that landed, biggest first."""
    layer = scene.layers.find_by_name("Sections")
    if layer is None:
        return []
    return sorted((g.surface_area(o.shape)
                   for o in scene.all() if o.layer_id == layer.id),
                  reverse=True)


def test_a_section_through_a_box_gives_the_face_the_plane_cut(env):
    scene, _sel, _hist, _ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 10, 20, 30))
    proc.run("section")
    proc.click_object(box.id)
    proc.finish_selection()
    proc.provide_text("5,-50,0")
    proc.provide_text("5,50,0")
    assert not proc.busy, "the command is still asking for something"
    assert _areas(scene) == [pytest.approx(600.0, rel=1e-6)], \
        "expected one 20 by 30 cut face on a Sections layer"


def test_the_objects_you_sectioned_are_left_alone(env):
    """A section is a drawing of the model, not a change to it."""
    scene, _sel, _hist, _ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 10, 20, 30))
    proc.run("section")
    proc.click_object(box.id)
    proc.finish_selection()
    proc.provide_text("5,-50,0")
    proc.provide_text("5,50,0")
    assert g.volume(scene.get(box.id).shape) == pytest.approx(6000.0), \
        "the box was cut in half instead of being drawn through"


def test_a_section_through_a_pipe_leaves_the_bore_open(env):
    """The reason the cut is a face: a hatch must not fill the bore in."""
    scene, _sel, _hist, _ctx, proc = env
    pipe = scene.add(g.boolean_difference(
        g.make_cylinder((0, 0, 0), 10, 30),
        g.make_cylinder((0, 0, 0), 6, 30)))
    proc.run("section")
    proc.click_object(pipe.id)
    proc.finish_selection()
    proc.provide_text("0,-50,15")
    proc.provide_text("0,50,15")
    # The plane stands on the line and leans with the construction plane,
    # so it runs down the pipe rather than across it: two rectangles of
    # wall, one either side of the bore.
    assert len(_areas(scene)) == 2, \
        f"expected the two walls either side of the bore, got {_areas(scene)}"
    assert _areas(scene)[0] == pytest.approx(4 * 30, rel=1e-3)


def test_a_line_that_misses_everything_makes_nothing_and_says_so(env):
    scene, _sel, _hist, _ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 10, 20, 30))
    proc.run("section")
    proc.click_object(box.id)
    proc.finish_selection()
    proc.provide_text("500,-50,0")
    proc.provide_text("500,50,0")
    assert _areas(scene) == [], "a plane nowhere near the box still cut it"
    assert len(scene.all()) == 1, "something landed in the scene anyway"


def test_two_points_in_the_same_spot_do_not_cut_anywhere(env):
    """Two points on top of each other name a line, but not a direction."""
    scene, _sel, _hist, _ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 10, 20, 30))
    proc.run("section")
    proc.click_object(box.id)
    proc.finish_selection()
    proc.provide_text("5,0,0")
    proc.provide_text("5,0,0")
    assert len(scene.all()) == 1, \
        "a section was cut through a plane nobody pointed at"


def test_one_section_is_one_undo(env):
    scene, _sel, _hist, _ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 10, 20, 30))
    proc.run("section")
    proc.click_object(box.id)
    proc.finish_selection()
    proc.provide_text("5,-50,0")
    proc.provide_text("5,50,0")
    assert _areas(scene)
    proc.run("undo")
    assert _areas(scene) == [], \
        "the section took more than one undo to put it back"
    assert len(scene.all()) == 1


def test_sectioning_a_surface_gives_a_curve_because_it_has_no_inside(env):
    scene, _sel, _hist, _ctx, proc = env
    face = scene.add(g.planar_face(g.make_polyline(
        [(0, 0, 0), (10, 0, 0), (10, 20, 0), (0, 20, 0)], closed=True)))
    proc.run("section")
    proc.click_object(face.id)
    proc.finish_selection()
    proc.provide_text("5,-50,0")
    proc.provide_text("5,50,0")
    layer = scene.layers.find_by_name("Sections")
    assert layer is not None, "nothing landed on a Sections layer"
    made = [o for o in scene.all() if o.layer_id == layer.id]
    assert len(made) == 1
    assert g.curve_length(made[0].shape) == pytest.approx(20.0, rel=1e-6), \
        "the cut across the surface is not the 20 long line it should be"


def test_the_section_line_can_be_drawn_across_several_objects_at_once(env):
    scene, _sel, _hist, _ctx, proc = env
    near = scene.add(g.make_box((0, 0, 0), 10, 20, 30))
    far = scene.add(g.make_box((0, 0, 100), 10, 20, 30))
    away = scene.add(g.make_box((900, 0, 0), 10, 10, 10))
    proc.run("section")
    for obj in (near, far, away):
        proc.click_object(obj.id)
    proc.finish_selection()
    proc.provide_text("5,-50,0")
    proc.provide_text("5,50,0")
    assert len(_areas(scene)) == 2, \
        "the plane crossed two of the three boxes, so expected two faces"
    assert all(a == pytest.approx(600.0, rel=1e-6) for a in _areas(scene))


def test_the_cut_leans_with_the_construction_plane(env):
    """The same two points drawn in Front cut vertically, as in Rhino."""
    scene, _sel, _hist, ctx, proc = env
    from serpentine3d.core.cplane import CPlane
    box = scene.add(g.make_box((0, 0, 0), 20, 20, 20))
    # A Front construction plane looks along +Y, so its normal is Y and a
    # line drawn left to right stands the cutting plane up in Z.
    ctx.replay_cplane = CPlane(origin=(0, 0, 0), normal=(0, 1, 0),
                               xdir=(1, 0, 0))
    proc.run("section")
    proc.click_object(box.id)
    proc.finish_selection()
    proc.provide_text("-50,0,10")
    proc.provide_text("50,0,10")
    assert _areas(scene) == [pytest.approx(400.0, rel=1e-6)], \
        "the cut did not lean with the construction plane"
    assert math.isclose(g.bbox(
        [o for o in scene.all()
         if o.layer_id == scene.layers.find_by_name("Sections").id][0].shape
    )[0][2], 10.0, abs_tol=1e-6), "the cut is not at the height it was drawn"


def test_the_drag_shows_the_cut_it_is_about_to_make(env):
    """You aim a section line by watching the cut, not the line."""
    scene, _sel, _hist, _ctx, proc = env
    box = scene.add(g.make_box((0, 0, 0), 10, 20, 30))
    proc.run("section")
    proc.click_object(box.id)
    proc.finish_selection()
    proc.provide_text("5,-50,0")
    show = proc.request.preview_fn
    assert show is not None, "the second point drags with nothing to look at"
    cut = show((5, 50, 0))
    assert g.surface_area(cut) == pytest.approx(600.0, rel=1e-6), \
        "the ghost is not the face the command goes on to make"
    assert show((5, -50, 0)) is None, \
        "a line with no length ghosted a plane nobody pointed at"
