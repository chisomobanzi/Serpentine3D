"""Hatching a shape with a hole in it fills the material, not the hole.

A section through a pipe is a ring of wall with a bore down the middle.
Hatched as a single outline the bore fills in solid and the drawing says
"bar" where the model says "pipe", which is the one thing a section
drawing exists to tell you apart.

So a hatch is asked about a region, meaning the ring around the outside
plus whatever rings are punched out of it, and both drawing paths (the
screen and the plot) ask it in the same place.
"""

from __future__ import annotations

import pytest

from serpentine3d.core.layout import (
    Hatch, Layout, annotation_bounds, cut_hatching, hatch_lines,
    hatch_region, layouts_from_json, layouts_to_json, move_annotation,
)


SQUARE = [(0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)]
HOLE = [(5.0, 5.0), (15.0, 5.0), (15.0, 15.0), (5.0, 15.0)]


def _by_row(segments):
    """Hatch segments grouped by the scanline they sit on."""
    rows: dict = {}
    for (ax, ay), (bx, by) in segments:
        rows.setdefault(round(ay, 6), []).append(
            (round(min(ax, bx), 6), round(max(ax, bx), 6)))
    return {y: sorted(spans) for y, spans in rows.items()}


# -- the region itself --

def test_a_scanline_across_a_ring_stops_at_the_hole_and_starts_again():
    rows = _by_row(hatch_region([SQUARE, HOLE], 0.0, 2.0))
    assert rows[11.0] == [(0.0, 5.0), (15.0, 20.0)], \
        "the line ran straight through the hole instead of skipping it"


def test_a_scanline_clear_of_the_hole_still_crosses_the_whole_shape():
    rows = _by_row(hatch_region([SQUARE, HOLE], 0.0, 2.0))
    assert rows[1.0] == [(0.0, 20.0)], \
        "the hole took material with it below where it starts"


def test_a_region_with_no_holes_is_hatched_the_way_it_always_was():
    """`hatch_lines` is the one-loop case, so it must stay the same."""
    assert hatch_region([SQUARE], 45.0, 2.0) == hatch_lines(SQUARE, 45.0, 2.0)


def test_a_ring_too_small_to_be_a_ring_is_passed_over():
    """A cut can graze an edge and come back as a point or a line.

    That is a ring with no inside, and it must not take the rest of the
    hatch down with it.
    """
    grazed = [(3.0, 3.0), (4.0, 3.0)]
    assert hatch_region([SQUARE, grazed], 0.0, 2.0) == \
        hatch_region([SQUARE], 0.0, 2.0)
    assert hatch_region([grazed], 0.0, 2.0) == []


# -- what both drawing paths ask for --

def test_the_cut_is_placed_on_the_paper_and_every_ring_is_outlined():
    """Screen and plot want the same two answers about the same cut.

    Model units into paper millimetres, then the lines that fill the
    region and the loops to draw round it. Asking twice in two places is
    how the plot and the screen came to disagree about a bore.
    """
    fill, loops, _solid = cut_hatching([[SQUARE, HOLE]], cx=100.0, cy=50.0,
                                       s=0.5, angle=0.0,
                                       spacing=1.0)
    assert len(loops) == 2, "the hole was not outlined, only the ring"
    assert loops[0][0] == pytest.approx((100.0, 50.0)), \
        "the cut is not where the detail puts it on the paper"
    assert loops[1][0] == pytest.approx((102.5, 52.5))
    rows = _by_row(fill)
    assert rows[55.5] == [(100.0, 102.5), (107.5, 110.0)], \
        "the bore filled in once the cut reached the paper"


def test_two_separate_cuts_do_not_shadow_each_other():
    """Even-odd is per region: two bars are two fills, not a checkerboard."""
    far = [(40.0, 0.0), (60.0, 0.0), (60.0, 20.0), (40.0, 20.0)]
    fill, loops, _solid = cut_hatching([[SQUARE], [far]], cx=0.0, cy=0.0,
                                       s=1.0, angle=0.0,
                                       spacing=2.0)
    assert len(loops) == 2
    assert _by_row(fill)[1.0] == [(0.0, 20.0), (40.0, 60.0)], \
        "the gap between two separate cuts was hatched as if it were solid"


# -- a hatch on the sheet remembers its holes --

def test_a_saved_hatch_keeps_its_holes():
    lay = Layout()
    lay.hatches.append(Hatch(points=[list(p) for p in SQUARE],
                             holes=[[list(p) for p in HOLE]]))
    back = layouts_from_json(layouts_to_json([lay]))[0]
    assert back.hatches[0].holes == [[list(p) for p in HOLE]], \
        "the hole was lost on the way through the file"


def test_an_older_file_with_no_holes_still_opens():
    """A sheet saved before holes existed is a sheet with none."""
    raw = layouts_to_json([Layout()])
    raw[0]["hatches"] = [{"id": "h1", "points": [[0, 0], [10, 0], [10, 10]],
                          "pattern": "lines", "angle": 45.0, "spacing": 3.0}]
    assert layouts_from_json(raw)[0].hatches[0].holes == []


def test_dragging_a_hatch_takes_its_holes_along():
    hatch = Hatch(points=[list(p) for p in SQUARE],
                  holes=[[list(p) for p in HOLE]])
    move_annotation("hatch", hatch, 10.0, 0.0)
    assert hatch.points[0] == [10.0, 0.0]
    assert hatch.holes[0][0] == [15.0, 5.0], \
        "the hole stayed behind and now sits outside the hatch"


def test_a_hatch_is_no_bigger_than_its_outside_ring():
    """Holes are inside the ring, so they cannot grow what it covers."""
    plain = Hatch(points=[list(p) for p in SQUARE])
    holed = Hatch(points=[list(p) for p in SQUARE],
                  holes=[[list(p) for p in HOLE]])
    assert annotation_bounds("hatch", holed) == annotation_bounds("hatch",
                                                                  plain)
