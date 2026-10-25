"""Fillet, the way Rhino asks it.

Run it and the prompt says "Select first curve", with Radius and Trim
beside it. Both stay there, and both can be changed without answering
the prompt: type a number and that is the radius, type t and Trim flips,
and the question still stands. Click the first curve near the corner you
mean, click the second near the same corner, and the fillet is made.

Nothing else is asked, because nothing else has to be: the corner is
where the clicks are, which also says which side of a crossing to keep,
and the radius and Trim are already on the prompt.

Radius 0 is Rhino's sharp corner: the curves are cut back, or carried
out, to the point they cross at, with no arc between them.
"""

from __future__ import annotations

import math

import pytest

from serpentine3d.core import geometry as g


def _two_lines(scene, gap=0.0):
    """A horizontal and a vertical line meeting at (10, 0), or not."""
    a = scene.add(g.make_line((0.0, 0.0, 0.0), (10.0 + gap, 0.0, 0.0)),
                  name="Across")
    b = scene.add(g.make_line((10.0, 0.0 - gap, 0.0), (10.0, 10.0, 0.0)),
                  name="Up")
    return a, b


def _curves(scene):
    return [o for o in scene.all() if o.kind == "curve"]


def _length(scene):
    return sum(g.curve_length(o.shape) for o in _curves(scene))


# -- what the prompt offers ------------------------------------------------

def test_it_opens_on_the_first_curve_with_radius_and_trim(env):
    scene, _sel, _hist, _ctx, proc = env
    _two_lines(scene)

    proc.run("fillet")

    assert "first curve" in proc.request.prompt.lower()
    assert dict(proc.option_chips()) == {"Radius": "0", "Trim": "Yes"}


def test_a_typed_number_is_the_radius_and_the_question_stands(env):
    scene, _sel, _hist, _ctx, proc = env
    _two_lines(scene)
    proc.run("fillet")

    proc.provide_text("2.5")

    assert dict(proc.option_chips())["Radius"] == "2.5"
    assert "first curve" in proc.request.prompt.lower(), \
        "a radius is not an answer to which curve was meant"


def test_t_flips_trim_and_the_question_stands(env):
    scene, _sel, _hist, _ctx, proc = env
    _two_lines(scene)
    proc.run("fillet")

    proc.provide_text("t")

    assert dict(proc.option_chips())["Trim"] == "No"
    assert "first curve" in proc.request.prompt.lower()


def test_both_are_still_there_at_the_second_curve(env):
    scene, _sel, _hist, _ctx, proc = env
    a, _b = _two_lines(scene)
    proc.run("fillet")
    proc.click_object(a.id, at=(9.0, 0.0, 0.0))

    assert "second curve" in proc.request.prompt.lower()
    assert sorted(dict(proc.option_chips())) == ["Radius", "Trim"]

    proc.provide_text("3")
    assert dict(proc.option_chips())["Radius"] == "3"
    assert "second curve" in proc.request.prompt.lower()


# -- and what the second click makes ---------------------------------------

def test_the_fillet_is_made_on_the_second_click(env):
    scene, _sel, _hist, _ctx, proc = env
    a, b = _two_lines(scene)
    proc.run("fillet")
    proc.provide_text("2")
    proc.click_object(a.id, at=(9.0, 0.0, 0.0))
    proc.click_object(b.id, at=(10.0, 1.0, 0.0))

    assert not proc.busy, "it asked for something after the second curve"
    curves = _curves(scene)
    assert len(curves) == 1, "trimmed and joined, as it always did"
    # two legs of 8, plus a quarter circle of radius 2
    assert g.curve_length(curves[0].shape) == pytest.approx(
        16 + math.pi, rel=1e-3)


def test_radius_zero_makes_a_sharp_corner(env):
    scene, _sel, _hist, _ctx, proc = env
    a, b = _two_lines(scene, gap=5.0)      # neither reaches the corner
    proc.run("fillet")
    proc.click_object(a.id, at=(2.0, 0.0, 0.0))
    proc.click_object(b.id, at=(10.0, 5.0, 0.0))

    curves = _curves(scene)
    assert len(curves) == 1
    # carried out to (10, 0): ten across and ten up, no arc
    assert g.curve_length(curves[0].shape) == pytest.approx(20.0, rel=1e-6)


def test_a_crossing_keeps_the_sides_that_were_clicked(env):
    scene, _sel, _hist, _ctx, proc = env
    a = scene.add(g.make_line((-10.0, 0.0, 0.0), (10.0, 0.0, 0.0)))
    b = scene.add(g.make_line((0.0, -10.0, 0.0), (0.0, 10.0, 0.0)))
    proc.run("fillet")
    proc.click_object(a.id, at=(-8.0, 0.0, 0.0))
    proc.click_object(b.id, at=(0.0, -8.0, 0.0))

    assert _length(scene) == pytest.approx(20.0, rel=1e-6), \
        "the two halves that were clicked, cut at the crossing"


def test_trim_no_leaves_the_curves_and_adds_the_arc(env):
    scene, _sel, _hist, _ctx, proc = env
    a, b = _two_lines(scene)
    proc.run("fillet")
    proc.provide_text("2")
    proc.provide_text("t")
    proc.click_object(a.id, at=(9.0, 0.0, 0.0))
    proc.click_object(b.id, at=(10.0, 1.0, 0.0))

    curves = _curves(scene)
    assert len(curves) == 3, "both curves kept, the arc added"
    assert scene.get(a.id) is not None and scene.get(b.id) is not None
    arc = next(o for o in curves if o.id not in (a.id, b.id))
    assert g.curve_length(arc.shape) == pytest.approx(math.pi, rel=1e-3)


def test_trim_no_at_radius_zero_says_there_is_nothing_to_make(env):
    scene, _sel, _hist, ctx, proc = env
    said = []
    ctx.add_echo_listener(said.append)
    a, b = _two_lines(scene)
    proc.run("fillet")
    proc.provide_text("t")
    proc.click_object(a.id, at=(9.0, 0.0, 0.0))
    proc.click_object(b.id, at=(10.0, 1.0, 0.0))

    assert len(_curves(scene)) == 2, "nothing was made, nothing was cut"
    assert any("leaves the curves as they are" in m for m in said), said


# -- and what it remembers -------------------------------------------------

def test_the_radius_is_what_the_next_fillet_opens_on(env):
    """Typed once and it stays, as Rhino keeps a command's options: the
    second corner of a drawing is usually the same size as the first."""
    scene, _sel, _hist, _ctx, proc = env
    a, b = _two_lines(scene)
    proc.run("fillet")
    proc.provide_text("2")
    proc.click_object(a.id, at=(9.0, 0.0, 0.0))
    proc.click_object(b.id, at=(10.0, 1.0, 0.0))

    c = scene.add(g.make_line((0.0, 20.0, 0.0), (10.0, 20.0, 0.0)))
    d = scene.add(g.make_line((10.0, 20.0, 0.0), (10.0, 30.0, 0.0)))
    proc.run("fillet")

    assert dict(proc.option_chips())["Radius"] == "2"
    proc.click_object(c.id, at=(9.0, 20.0, 0.0))
    proc.click_object(d.id, at=(10.0, 21.0, 0.0))
    made = next(o for o in _curves(scene) if o.id == c.id)
    assert g.curve_length(made.shape) == pytest.approx(16 + math.pi, rel=1e-3)


@pytest.mark.parametrize("typed, radius", [
    ("2mm", 2.0), ("0.1in", 2.54), ('1/10"', 2.54), ("0.2cm", 2.0)])
def test_the_radius_takes_units(env, typed, radius):
    """A length typed with its units is a radius, not an object's name,
    as it was at the radius prompt this replaced."""
    scene, _sel, _hist, _ctx, proc = env
    a, b = _two_lines(scene)
    proc.run("fillet")
    proc.provide_text(typed)
    assert "first curve" in proc.request.prompt.lower()
    proc.click_object(a.id, at=(9.0, 0.0, 0.0))
    proc.click_object(b.id, at=(10.0, 1.0, 0.0))

    made = next(o for o in _curves(scene) if o.id == a.id)
    legs = 2 * (10 - radius)
    assert g.curve_length(made.shape) == pytest.approx(
        legs + math.pi * radius / 2, rel=1e-3)


def test_trim_is_remembered_the_same_way(env):
    scene, _sel, _hist, _ctx, proc = env
    a, b = _two_lines(scene)
    proc.run("fillet")
    proc.provide_text("2")
    proc.provide_text("t")
    proc.click_object(a.id, at=(9.0, 0.0, 0.0))
    proc.click_object(b.id, at=(10.0, 1.0, 0.0))

    proc.run("fillet")

    assert dict(proc.option_chips())["Trim"] == "No"


def test_a_fresh_start_is_a_sharp_trimming_corner_again(env):
    """What the module holds dies with the program, which is the whole
    of "until it is started again"."""
    from serpentine3d.commands import edit

    scene, _sel, _hist, _ctx, proc = env
    edit._FILLET_STICKY.update({"Radius": "7", "Trim": "No"})
    edit._FILLET_STICKY.update({"Radius": "0", "Trim": "Yes"})  # a restart
    _two_lines(scene)
    proc.run("fillet")

    assert dict(proc.option_chips()) == {"Radius": "0", "Trim": "Yes"}


# -- without a click to read -----------------------------------------------

def test_curves_named_rather_than_clicked_take_the_nearest_corner(env):
    """Typed, scripted or chosen from a list: no click to read a corner
    off, so the ends that lie nearest each other are the corner meant."""
    scene, _sel, _hist, _ctx, proc = env
    scene.add(g.make_line((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)), name="Across")
    scene.add(g.make_line((10.0, 0.0, 0.0), (10.0, 10.0, 0.0)), name="Up")
    proc.run("fillet")
    proc.provide_text("2")
    proc.provide_text("Across")
    proc.provide_text("Up")

    curves = _curves(scene)
    assert len(curves) == 1
    assert g.curve_length(curves[0].shape) == pytest.approx(
        16 + math.pi, rel=1e-3)


# -- polylines keep the rest of themselves ---------------------------------

def _two_polylines(scene):
    """Two three-piece polylines whose last pieces make a corner.

    Across runs 0,20 -> 0,10 -> 5,0 -> 15,0, Up runs 20,0 -> 20,10, with
    a long tail behind each: filleting the corner at (20, 0) has no claim
    on anything but the piece it is made in.
    """
    a = scene.add(g.make_polyline([(0.0, 20.0, 0.0), (0.0, 10.0, 0.0),
                                   (5.0, 0.0, 0.0), (15.0, 0.0, 0.0)]),
                  name="Across")
    b = scene.add(g.make_polyline([(20.0, 20.0, 0.0), (20.0, 15.0, 0.0),
                                   (20.0, 0.0, 0.0)]), name="Up")
    return a, b


def test_a_polyline_keeps_the_pieces_the_corner_never_touched(env):
    """Both are carried out to (20, 0) and rounded there, and everything
    drawn behind that corner is still there afterwards."""
    scene, _sel, _hist, _ctx, proc = env
    a, b = _two_polylines(scene)
    before = _length(scene)
    proc.run("fillet")
    proc.provide_text("2")
    proc.click_object(a.id, at=(14.0, 0.0, 0.0))
    proc.click_object(b.id, at=(20.0, 1.0, 0.0))

    curves = _curves(scene)
    assert len(curves) == 1, "the two polylines joined into one curve"
    # the tails are untouched, the two clicked pieces reach the corner,
    # and the arc cuts 2 off each leg in exchange for a quarter circle
    grown = (20.0 - 15.0) + (20.0 - 0.0) - 20.0
    assert g.curve_length(curves[0].shape) == pytest.approx(
        before + grown - 4 + math.pi, rel=1e-3), \
        "a fillet dropped part of a polyline nobody picked"


def test_a_sharp_corner_keeps_them_too(env):
    scene, _sel, _hist, _ctx, proc = env
    a, b = _two_polylines(scene)
    before = _length(scene)
    proc.run("fillet")
    proc.click_object(a.id, at=(14.0, 0.0, 0.0))
    proc.click_object(b.id, at=(20.0, 1.0, 0.0))

    curves = _curves(scene)
    assert len(curves) == 1
    assert g.curve_length(curves[0].shape) == pytest.approx(
        before + 5.0, rel=1e-6), \
        "both clicked pieces carried out to (20, 0), the tails left alone"


def test_what_lies_past_the_corner_is_what_the_trim_takes(env):
    """A piece in the middle of a polyline is cut at the corner, so what
    hangs off its other side goes with the cut: that is what trimming a
    curve to a corner means, and the clicks say which side is kept."""
    scene, _sel, _hist, _ctx, proc = env
    a = scene.add(g.make_polyline([(0.0, 0.0, 0.0), (20.0, 0.0, 0.0),
                                   (20.0, -5.0, 0.0)]), name="Across")
    b = scene.add(g.make_line((10.0, 0.0, 0.0), (10.0, 10.0, 0.0)),
                  name="Up")
    proc.run("fillet")
    proc.click_object(a.id, at=(2.0, 0.0, 0.0))     # the side to keep
    proc.click_object(b.id, at=(10.0, 8.0, 0.0))

    curves = _curves(scene)
    assert len(curves) == 1
    assert g.curve_length(curves[0].shape) == pytest.approx(
        20.0, rel=1e-6), \
        "ten across to the corner and ten up, the rest trimmed away"


# -- drawn curves, not just lines and arcs ---------------------------------

def _a_drawn_curve(scene):
    """A degree-3 curve through four points, dipping below y=0 and coming
    back up across it. Its one crossing with the line below is the kind
    the kernel's distance extrema used to walk straight past, which is
    why filleting a drawn curve was refused as not crossing at all."""
    points = [(0.0, -3.0, 0.0), (5.0, -6.0, 0.0),
              (10.0, -6.0, 0.0), (15.0, 3.0, 0.0)]
    return scene.add(g.make_interp_curve(points), name="Drawn")


def test_a_drawn_curve_fillets_against_a_line(env):
    scene, _sel, _hist, _ctx, proc = env
    curve = _a_drawn_curve(scene)
    line = scene.add(g.make_line((-5.0, 0.0, 0.0), (20.0, 0.0, 0.0)),
                     name="Flat")
    proc.run("fillet")
    proc.provide_text("2")
    proc.click_object(curve.id, at=(14.0, 2.0, 0.0))
    proc.click_object(line.id, at=(18.0, 0.0, 0.0))

    curves = _curves(scene)
    assert len(curves) == 1, "they cross, so there is a corner to round"
    assert g.is_valid(curves[0].shape)


def test_a_drawn_curve_fillets_against_a_polyline(env):
    scene, _sel, _hist, _ctx, proc = env
    curve = _a_drawn_curve(scene)
    poly = scene.add(g.make_polyline([(-5.0, 0.0, 0.0), (20.0, 0.0, 0.0),
                                      (20.0, 9.0, 0.0)]), name="Flat")
    proc.run("fillet")
    proc.click_object(curve.id, at=(14.0, 2.0, 0.0))
    proc.click_object(poly.id, at=(18.0, 0.0, 0.0))

    curves = _curves(scene)
    assert len(curves) == 1
    assert g.is_valid(curves[0].shape)


def test_two_drawn_curves_find_their_crossing(env):
    scene, _sel, _hist, _ctx, proc = env
    a = _a_drawn_curve(scene)
    b = scene.add(g.make_interp_curve([(8.0, -10.0, 0.0), (12.0, -4.0, 0.0),
                                       (14.0, 6.0, 0.0)]), name="Other")
    proc.run("fillet")
    proc.click_object(a.id, at=(14.0, 2.0, 0.0))
    proc.click_object(b.id, at=(8.5, -9.0, 0.0))

    curves = _curves(scene)
    assert len(curves) == 1
    assert g.is_valid(curves[0].shape)


def test_the_corner_of_a_drawn_curve_is_where_it_really_crosses(env):
    """Not near enough: the corner is the crossing itself, so the two
    pieces meet exactly and the line keeps the end that was clicked."""
    scene, _sel, _hist, _ctx, proc = env
    curve = _a_drawn_curve(scene)
    line = scene.add(g.make_line((-5.0, 0.0, 0.0), (20.0, 0.0, 0.0)))
    kept, rest = g.corner_curves(curve.shape, line.shape,
                                 (14.0, 2.0, 0.0), (18.0, 0.0, 0.0))

    corner = g._shared_end(kept, rest)
    assert corner is not None, "the two pieces do not meet"
    assert corner[1] == pytest.approx(0.0, abs=1e-6), \
        "the corner should sit on the line it was cut at"
    assert g.curve_length(rest) == pytest.approx(20.0 - corner[0], rel=1e-6)
    assert g.curve_length(kept) < g.curve_length(curve.shape)


# -- curves that never touch at all ----------------------------------------

def _two_apart(scene):
    """Two drawn curves lying near each other and crossing nowhere.

    A line or an arc is carried out to a corner by its own geometry, so
    a gap between two of those is no trouble. A drawn curve has no more
    of itself to read: it is carried on straight, the way it was heading
    when it stopped, and that is what reaches the corner.
    """
    over = scene.add(g.make_interp_curve(
        [(10.0, 28.0, 0.0), (15.0, 36.0, 0.0), (23.0, 40.5, 0.0),
         (32.0, 37.5, 0.0), (37.5, 28.0, 0.0), (38.0, 17.0, 0.0)]),
        name="Over")
    under = scene.add(g.make_interp_curve(
        [(28.7, 22.8, 0.0), (31.0, 18.0, 0.0), (35.0, 12.0, 0.0),
         (42.0, 10.2, 0.0), (52.0, 14.0, 0.0), (62.0, 23.0, 0.0),
         (69.3, 29.5, 0.0)]), name="Under")
    return over, under


def test_curves_that_never_meet_are_carried_on_to_their_corner(env):
    scene, _sel, _hist, _ctx, proc = env
    over, under = _two_apart(scene)
    assert g.curve_length(over.shape) > 0
    proc.run("fillet")
    proc.provide_text("2")
    proc.click_object(over.id, at=(38.0, 18.0, 0.0))
    proc.click_object(under.id, at=(29.0, 22.0, 0.0))

    curves = _curves(scene)
    assert len(curves) == 1, "a fillet, not a refusal"
    assert g.is_valid(curves[0].shape)


def test_it_is_the_same_corner_wherever_the_curves_are_clicked(env):
    """The clicks say which side of each curve to keep, and with one
    corner to be had they all find it: picking the far end of a curve is
    not a different question about where the corner is."""
    scene, _sel, _hist, _ctx, proc = env
    over, under = _two_apart(scene)
    corners = []
    for on_over, on_under in [((38.0, 18.0, 0.0), (29.0, 22.0, 0.0)),
                              ((35.0, 30.0, 0.0), (33.0, 15.0, 0.0)),
                              ((20.0, 39.0, 0.0), (60.0, 21.0, 0.0))]:
        kept, rest = g.corner_curves(over.shape, under.shape,
                                     on_over, on_under)
        corners.append(g._shared_end(kept, rest))

    assert all(c is not None for c in corners), "the pieces must meet"
    for other in corners[1:]:
        assert other == pytest.approx(corners[0], abs=1e-6)


def test_the_straight_run_is_added_not_the_curve_redrawn(env):
    """What the curve was stays as it was: the reach to the corner is
    added to it, so nothing anyone drew is moved or smoothed away."""
    scene, _sel, _hist, _ctx, proc = env
    over, under = _two_apart(scene)
    was = g.curve_length(over.shape)

    kept, _rest = g.corner_curves(over.shape, under.shape,
                                  (38.0, 18.0, 0.0), (29.0, 22.0, 0.0))

    assert g.curve_length(kept) > was, "the curve had to reach further"
    assert g.curve_length(kept) == pytest.approx(was + 6.1, abs=0.5), \
        "and only by the straight bit, not by being redrawn"


def test_curves_facing_away_from_each_other_still_say_no(env):
    """Carrying a curve on is not licence to invent a corner anywhere:
    two that head apart have none, and the message says that."""
    scene, _sel, _hist, _ctx, proc = env
    a = g.make_interp_curve([(0.0, 0.0, 0.0), (5.0, 2.0, 0.0),
                             (10.0, 0.0, 0.0)])
    b = g.make_interp_curve([(0.0, 20.0, 0.0), (5.0, 22.0, 0.0),
                             (10.0, 20.0, 0.0)])
    with pytest.raises(g.GeometryError, match="do not cross"):
        g.corner_curves(a, b, (9.0, 0.5, 0.0), (9.0, 20.5, 0.0))
