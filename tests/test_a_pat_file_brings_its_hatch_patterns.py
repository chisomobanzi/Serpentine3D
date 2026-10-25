"""Hatch patterns come from .pat files, the industry's own (#92).

Asked for: the capability to use the industry standard hatch patterns, and
the .pat format they are stored in. A .pat file is loaded into the drawing
and its patterns are offered beside Lines, Cross and Solid wherever a
pattern is picked: for a hatch in the model, a hatch on a sheet, and the
section hatch of a layer or an object. What is loaded is saved with the
drawing, and a hatch drawn with one carries it, so it is still drawn the
same way where the pattern was never loaded.

A pattern is families of lines, dashed or whole, the way DXF and Rhino
files keep theirs too, so the import of those is the same object.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.hatch import HatchShape
from serpentine3d.core.hatch_patterns import (
    HatchPattern, PatternError, merge_into, parse_pat, pattern_segments,
    write_pat)
from serpentine3d.core.layers import DEFAULT_LAYER_ID, section_fill_dict
from serpentine3d.core.layout import (SectionFill, section_drawing,
                                      section_fills_of)
from serpentine3d.core.scene import Scene

PAT = """;; a few of the classics, written the way acad.pat writes them
*ANSI31, ANSI Iron, Brick, Stone masonry
45, 0,0, 0,.125
*ANSI37, ANSI Lead, Sheet metal
45, 0,0, 0,.125
135, 0,0, 0,.125
*DASH, Dashed lines
0, 0,0, .125,.125, .125,-.125
*DOTS, A grid of dots
0, 0,0, .03125,.0625, 0,-.0625
*AR-BRICK, Brick laid in thirds
0, 0,0, 0,.25
90, 0,0, .375,.25, .25,-.25
*SOLID, Solid fill
"""

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _patterns() -> dict:
    return {p.name: p for p in parse_pat(PAT)}


def _square(size=10.0):
    return g.make_polyline([(0, 0, 0), (size, 0, 0), (size, size, 0),
                            (0, size, 0)], closed=True)


def _face(size=10.0):
    (face,) = g.planar_regions([_square(size)])
    return face


def _inside(point, size=10.0, slack=1e-6):
    return all(-slack <= c <= size + slack for c in point[:2])


# --- reading a file ---------------------------------------------------------

def test_every_pattern_in_the_file_is_read_with_its_lines():
    found = _patterns()

    assert list(found) == ["ANSI31", "ANSI37", "DASH", "DOTS", "AR-BRICK",
                           "SOLID"]
    assert found["ANSI31"].description == "ANSI Iron, Brick, Stone masonry"
    assert len(found["ANSI37"].lines) == 2
    assert found["AR-BRICK"].lines[1].dashes == (0.25, -0.25)
    assert found["SOLID"].solid


def test_a_file_written_out_reads_back_the_same():
    again = {p.name: p for p in parse_pat(write_pat(parse_pat(PAT)))}

    assert again == _patterns()


@pytest.mark.parametrize("text", [
    "45, 0,0, 0,.125\n",                 # a line before any *NAME
    "*BAD, broken\n45, 0, zero, 0, 1\n",
    "*SHORT, too few numbers\n45, 0, 0\n",
    "*EMPTY, no lines and not SOLID\n",
])
def test_a_file_that_is_not_a_pattern_file_says_so(text):
    with pytest.raises(PatternError):
        parse_pat(text)


def test_a_pattern_named_like_the_app_s_own_is_kept_apart():
    """A file's LINES is not the app's Lines, so a hatch from that file is
    drawn as the file drew it and a layer set to Lines keeps the app's."""
    library = {}
    named = merge_into(library, parse_pat(
        "*LINES, imposter\n0, 0,0, .5,1, 1,-1\n*ANSI31\n45, 0,0, 0,.125\n"),
        source="acad")

    assert named == {"LINES": "LINES (acad)", "ANSI31": "ANSI31"}
    assert list(library) == ["LINES (acad)", "ANSI31"]


def test_a_pattern_that_draws_like_one_of_the_app_s_own_is_that_one():
    """Rhino's Plus, or a brick written in inches, is the app's own,
    whatever unit or name it came in."""
    library = {}
    named = merge_into(library, parse_pat(
        "*Plus\n0, -.125,0, 0,1, .25,-.75\n90, 0,-.125, 0,1, .25,-.75\n"
        "*MYBRICK\n0, 0,0, 0,.25\n90, 0,0, .25,.25, .25,-.25\n"
        "*SOLID\n"))

    assert named == {"Plus": "plus", "MYBRICK": "brick", "SOLID": "solid"}
    assert library == {}


def test_loading_a_pattern_again_replaces_it_whatever_its_case():
    library = {}
    merge_into(library, parse_pat("*ansi31\n45, 0,0, 0,1\n"))
    merge_into(library, parse_pat("*ANSI31\n45, 0,0, 0,.125\n"))

    assert list(library) == ["ANSI31"]
    assert library["ANSI31"].lines[0].offset == (0.0, 0.125)


# --- drawing one ------------------------------------------------------------

def test_a_pattern_s_spacing_is_the_distance_between_its_rows():
    """ANSI31 is lines at 45 degrees an eighth of an inch apart: at a
    spacing of 1 its lines are 1 apart, as Lines' are, whatever unit the
    file was written in."""
    segs = pattern_segments([SQUARE], _patterns()["ANSI31"], 0.0, 1.0)
    normal = np.array([-1.0, 1.0]) / math.sqrt(2)
    offsets = sorted({round(float(np.dot(a, normal)), 6) for a, _b in segs})

    assert np.diff(offsets) == pytest.approx(np.ones(len(offsets) - 1))
    for a, b in segs:
        assert (b[1] - a[1]) == pytest.approx(b[0] - a[0]), "at 45 degrees"


def test_dashes_are_drawn_with_their_gaps():
    segs = pattern_segments([SQUARE], _patterns()["DASH"], 0.0, 1.0)
    lengths = [math.dist(a, b) for a, b in segs]

    assert max(lengths) == pytest.approx(1.0), "each dash as long as a row"
    covered = sum(lengths)
    # nine rows: the two along the square's top and bottom are its edges
    assert covered == pytest.approx(0.5 * 10 * 9, rel=0.1), \
        "half of every row is gap"


def test_dots_are_drawn_as_marks_you_can_see():
    segs = pattern_segments([SQUARE], _patterns()["DOTS"], 0.0, 1.0)

    assert len(segs) > 50
    assert all(0 < math.dist(a, b) < 0.1 for a, b in segs)


def test_every_family_is_drawn_and_stays_in_the_region():
    segs = pattern_segments([SQUARE], _patterns()["AR-BRICK"], 30.0, 1.0)
    directions = {round(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
                        % 180.0) for a, b in segs}

    assert directions == {30, 120}, "courses and joints, turned together"
    assert all(_inside(a) and _inside(b) for a, b in segs)


def test_a_hole_is_left_empty_by_a_pattern_too():
    hole = [(4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0)]
    segs = pattern_segments([SQUARE, hole], _patterns()["AR-BRICK"], 0.0, 0.5)

    for a, b in segs:
        middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        assert not (4.0 + 1e-6 < middle[0] < 6.0 - 1e-6
                    and 4.0 + 1e-6 < middle[1] < 6.0 - 1e-6)


# --- in the drawing ---------------------------------------------------------

def test_a_loaded_pattern_is_offered_as_a_section_fill():
    scene = Scene()
    merge_into(scene.hatch_patterns, parse_pat(PAT))

    assert "ANSI31" in section_fills_of(scene)
    assert section_fills_of(scene)[:4] == ("none", "lines", "cross", "solid")


def test_a_layer_s_cut_is_drawn_with_the_pattern_it_names():
    scene = Scene()
    merge_into(scene.hatch_patterns, parse_pat(PAT))
    box = scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    scene.layers.set_hatch(DEFAULT_LAYER_ID, "ANSI37")

    fill = scene.section_fill_of(scene.get(box.id))
    assert fill.definition == _patterns()["ANSI37"]

    lines, _outlines, _floods = section_drawing(
        [[SQUARE]], 0.0, 0.0, 1.0, [fill])
    (_color, segs), = lines
    directions = {round(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))
                        % 180.0) for a, b in segs}
    assert directions == {90, 180 % 180} or directions == {0, 90}, \
        "two families at 45 and 135, turned by the layer's 45"


def test_a_pattern_the_drawing_has_not_got_is_drawn_as_lines():
    plain = section_drawing([[SQUARE]], 0.0, 0.0, 1.0,
                            [SectionFill("lines", 45.0, 1.0)])[0]
    unknown = section_drawing([[SQUARE]], 0.0, 0.0, 1.0,
                              [SectionFill("ANSI31", 45.0, 1.0)])[0]

    assert unknown == plain


def test_an_object_s_own_section_can_name_a_loaded_pattern():
    scene = Scene()
    merge_into(scene.hatch_patterns, parse_pat(PAT))
    box = scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    scene.update(box.id, section_fill=section_fill_dict("AR-BRICK"))

    assert scene.section_fill_of(scene.get(box.id)).definition.name == "AR-BRICK"


def test_the_library_is_part_of_what_undo_puts_back():
    scene = Scene()
    before = scene.snapshot()
    merge_into(scene.hatch_patterns, parse_pat(PAT))
    scene.restore(before)

    assert scene.hatch_patterns == {}


# --- a hatch in the model ---------------------------------------------------

def test_a_model_hatch_carries_its_pattern():
    brick = _patterns()["AR-BRICK"]
    hatch = HatchShape(_face(), "AR-BRICK", angle=0.0, spacing=1.0,
                       definition=brick)

    assert hatch.definition == brick
    assert len(hatch.pattern_segments()) > 20
    back = HatchShape.from_bytes(hatch.to_bytes())
    assert back.pattern == "AR-BRICK" and back.definition == brick
    assert len(back.pattern_segments()) == len(hatch.pattern_segments())
    moved = hatch.transformed(np.diag([2.0, 2.0, 2.0, 1.0]))
    assert moved.definition == brick and moved.spacing == pytest.approx(2.0)


def test_a_model_hatch_cannot_name_a_pattern_it_was_not_given():
    with pytest.raises(g.GeometryError):
        HatchShape(_face(), "AR-BRICK", spacing=1.0)


def test_a_hatch_turned_back_to_lines_lets_its_pattern_go():
    hatch = HatchShape(_face(), "AR-BRICK", spacing=1.0,
                       definition=_patterns()["AR-BRICK"])

    lines = hatch.edited(pattern="lines")
    assert lines.pattern == "lines" and lines.definition is None


def test_too_fine_a_pattern_is_refused_rather_than_drawn():
    with pytest.raises(g.GeometryError, match="larger spacing"):
        HatchShape(_face(), "DOTS", spacing=0.001,
                   definition=_patterns()["DOTS"])


def test_a_drawing_keeps_its_patterns_and_hatches_through_a_save(tmp_path):
    from serpentine3d.fileio import native

    scene = Scene()
    merge_into(scene.hatch_patterns, parse_pat(PAT))
    scene.layers.set_hatch(DEFAULT_LAYER_ID, "ANSI31")
    scene.add(HatchShape(_face(), "AR-BRICK", spacing=1.0,
                         definition=_patterns()["AR-BRICK"]), name="Hatch")
    path = str(tmp_path / "patterns.serp")
    native.save_scene(scene, path)

    back = Scene()
    native.load_scene(back, path)
    assert back.hatch_patterns == scene.hatch_patterns
    assert back.layers.get(DEFAULT_LAYER_ID).hatch == "ANSI31"
    (hatch,) = [o.shape for o in back.all() if o.kind == "hatch"]
    assert hatch.definition == _patterns()["AR-BRICK"]


def test_a_file_with_a_patterned_hatch_says_which_reader_it_needs(tmp_path):
    import json
    import zipfile

    from serpentine3d.fileio import native

    scene = Scene()
    scene.add(HatchShape(_face(), "AR-BRICK", spacing=1.0,
                         definition=_patterns()["AR-BRICK"]), name="Hatch")
    path = str(tmp_path / "brick.serp")
    native.save_scene(scene, path)

    with zipfile.ZipFile(path) as zf:
        doc = json.loads(zf.read("document.json"))
    assert doc["version"] >= 8


def test_a_dxf_hatch_is_written_with_the_pattern_it_is_drawn_with(tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    from serpentine3d import fileio

    scene = Scene()
    scene.add(HatchShape(_face(), "AR-BRICK", spacing=1.0,
                         definition=_patterns()["AR-BRICK"]), name="Hatch")
    path = str(tmp_path / "brick.dxf")
    fileio.export_file(scene, path)

    (out,) = ezdxf.readfile(path).modelspace().query("HATCH")
    assert out.dxf.pattern_name == "AR-BRICK"
    rows = out.pattern.lines
    assert len(rows) == 2
    assert math.hypot(rows[0].offset.x, rows[0].offset.y) == pytest.approx(1.0)
    assert [round(d, 6) for d in rows[1].dash_length_items] == [1.0, -1.0]


# --- the command ------------------------------------------------------------

def test_the_command_loads_a_pat_file_into_the_drawing(env, tmp_path):
    scene, _sel, history, _ctx, proc = env
    path = tmp_path / "classic.pat"
    path.write_text(PAT, encoding="utf-8")

    proc.run("hatchpatterns")
    proc.provide_text("Load")
    proc.provide_text(str(path))

    assert list(scene.hatch_patterns) == ["ANSI31", "ANSI37", "DASH (classic)",
                                          "DOTS (classic)", "AR-BRICK"]
    assert scene.hatch_patterns["ANSI31"] == _patterns()["ANSI31"]


def test_a_hatch_can_be_drawn_with_a_loaded_pattern(env, tmp_path):
    scene, _sel, _hist, _ctx, proc = env
    merge_into(scene.hatch_patterns, parse_pat(PAT))
    outline = scene.add(_square(), name="Outline")

    proc.run("hatch")
    proc.click_object(outline.id)
    proc.finish_selection()
    assert "ANSI31" in proc.form.fields[0].req.options
    proc.provide_form({"pattern": "ANSI31", "spacing": 1.0, "angle": 0.0})

    (hatch,) = [o.shape for o in scene.all() if o.kind == "hatch"]
    assert hatch.pattern == "ANSI31"
    assert hatch.definition == _patterns()["ANSI31"]


def test_a_file_that_cannot_be_read_says_so(env, tmp_path):
    scene, _sel, _hist, ctx, proc = env
    path = tmp_path / "broken.pat"
    path.write_text("45, 0,0, 0,1\n", encoding="utf-8")
    said = []
    ctx.echo = said.append

    proc.run("hatchpatterns Load")
    proc.provide_text(str(path))

    assert scene.hatch_patterns == {}
    assert any("Could not read broken.pat" in line for line in said)


def test_a_pattern_has_a_dict_form_that_reads_back():
    brick = _patterns()["AR-BRICK"]

    assert HatchPattern.from_dict(brick.to_dict()) == brick
