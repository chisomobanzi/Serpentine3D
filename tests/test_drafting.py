"""Drafting depth: annotation editing, associative dims, styles, tables."""

import math

import pytest

from serpentine.core.layout import (
    AngularDim, DetailView, Hatch, Layout, Leader, LinearDim, RadialDim,
    TextNote, annotation_at, annotation_bounds, delete_annotation,
    detail_project, detail_unproject, enclosing_polygon, layouts_from_json,
    layouts_to_json, move_annotation, resolve_associative,
)


def _detail(**kw):
    # top view, centred at origin, 1:10, 100x80mm at (10,10)
    return DetailView(x=10, y=10, w=100, h=80, scale_denom=10.0, **kw)


def test_detail_project_roundtrip():
    det = _detail()
    m = detail_unproject(det, 40.0, 30.0)
    px, py = detail_project(det, m)
    assert px == pytest.approx(40.0) and py == pytest.approx(30.0)
    # centre of the frame maps to the target
    m0 = detail_unproject(det, 10 + 50, 10 + 40)
    assert m0 == pytest.approx([0, 0, 0])


def test_associative_dim_follows_detail():
    lay = Layout()
    det = _detail()
    lay.details.append(det)
    dim = LinearDim(x1=20, y1=20, x2=40, y2=20, scale_denom=10.0,
                    detail_id=det.id,
                    m1=detail_unproject(det, 20, 20),
                    m2=detail_unproject(det, 40, 20))
    lay.dims.append(dim)
    # pan the detail one paper-mm right in model terms: target -x by 10
    det.target = [det.target[0] - 10.0, det.target[1], det.target[2]]
    resolve_associative(lay)
    assert dim.x1 == pytest.approx(21.0)
    assert dim.x2 == pytest.approx(41.0)
    # rescale 1:10 -> 1:20 halves the paper length about the centre
    det.target = [det.target[0] + 10.0, det.target[1], det.target[2]]
    det.scale_denom = 20.0
    resolve_associative(lay)
    assert dim.x2 - dim.x1 == pytest.approx(10.0)
    assert dim.scale_denom == pytest.approx(20.0)
    # hand-moving an associative dim breaks the anchor
    move_annotation("dim", dim, 5.0, 0.0)
    assert dim.detail_id == "" and dim.m1 is None


def test_annotation_hit_move_delete():
    lay = Layout()
    note = TextNote(x=50, y=50, text="HELLO", height=4)
    lay.notes.append(note)
    dim = LinearDim(x1=100, y1=30, x2=140, y2=30, offset=8)
    lay.dims.append(dim)
    leader = Leader(points=[[200, 40], [210, 60], [225, 60]], text="note")
    lay.leaders.append(leader)
    hatch = Hatch(points=[[250, 20], [280, 20], [280, 50], [250, 50]])
    lay.hatches.append(hatch)

    assert annotation_at(lay, 55, 51)[0] == "note"
    assert annotation_at(lay, 120, 38)[0] == "dim"     # on the dim line
    assert annotation_at(lay, 205, 50)[0] == "leader"
    assert annotation_at(lay, 265, 35)[0] == "hatch"
    assert annotation_at(lay, 5, 5) is None

    move_annotation("note", note, 3, -2)
    assert (note.x, note.y) == (53, 48)
    move_annotation("hatch", hatch, 10, 0)
    assert hatch.points[0] == [260, 20]
    x0, y0, x1, y1 = annotation_bounds("dim", dim)
    assert x0 == 100 and x1 == 140 and y1 == pytest.approx(38)

    assert delete_annotation(lay, "leader", leader)
    assert not lay.leaders
    assert not delete_annotation(lay, "leader", leader)


def test_enclosing_polygon():
    square = [(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]
    big = [(-5, -5), (25, -5), (25, 25), (-5, 25), (-5, -5)]
    open_poly = [(50, 50), (60, 50), (60, 60)]
    # picks the smallest containing loop, ignores open polylines
    assert enclosing_polygon([big, square, open_poly], 5, 5) == square[:-1]
    assert enclosing_polygon([big, square], 15, 15) == big[:-1]
    assert enclosing_polygon([square], 40, 40) is None


def test_layout_serialization_v2_fields():
    lay = Layout(name="S1")
    det = _detail()
    lay.details.append(det)
    lay.dims.append(LinearDim(x1=1, y1=2, x2=3, y2=4, detail_id=det.id,
                              m1=[0, 0, 0], m2=[10, 0, 0], style="Small"))
    lay.notes.append(TextNote(x=1, y=1, text="a\nb", style="Heading"))
    lay.revisions.append(["A", "2026-07-13", "first issue"])
    out = layouts_to_json([lay])
    back = layouts_from_json(out)[0]
    assert back.dims[0].detail_id == det.id
    assert back.dims[0].m2 == [10, 0, 0]
    assert back.dims[0].style == "Small"
    assert back.notes[0].text == "a\nb"
    assert back.revisions == [["A", "2026-07-13", "first issue"]]


def test_annot_styles_roundtrip(tmp_path):
    from serpentine import fileio
    from serpentine.core.scene import Scene
    scene = Scene()
    scene.annot_styles["Big"] = {"text_height": 8.0, "arrow_size": 3.0,
                                 "dim_offset": 8.0}
    scene.layouts.append(Layout(name="Sheet 1"))
    path = str(tmp_path / "styles.serp")
    fileio.export_file(scene, path)
    loaded = Scene()
    fileio.import_file(loaded, path)
    assert loaded.annot_styles["Big"]["text_height"] == 8.0

    from serpentine.ui.annot_paint import style_of
    assert style_of(loaded, "Big")["text_height"] == 8.0
    assert style_of(loaded, "")["text_height"] == 3.2       # Standard
    assert style_of(loaded, "Heading")["text_height"] == 6.0


def test_drafting_commands(env):
    """text with style + multiline, dim anchoring, revision, sheetindex."""
    scene, sel, hist, ctx, proc = env
    from serpentine.core.layout import Layout
    lay = Layout(name="Sheet 1")
    det = _detail()
    lay.details.append(det)
    scene.layouts.append(lay)
    from tests.conftest import StubViewport
    ctx.viewport = StubViewport(lay.id)

    proc.run("text")
    proc.provide_text("50,50")
    proc.provide_text("line one\\nline two")
    proc.provide_text("Style=Heading")
    proc.provide_text("")                    # accept default height
    assert lay.notes[0].text == "line one\nline two"
    assert lay.notes[0].style == "Heading"

    proc.run("dim")
    proc.provide_text("20,20")
    proc.provide_text("40,20")
    proc.provide_text("30,28")
    dim = lay.dims[0]
    assert dim.detail_id == det.id and dim.m1 is not None

    proc.run("revision")
    proc.provide_text("A")
    proc.provide_text("issued for review")
    assert lay.revisions[0][0] == "A"
    assert lay.revisions[0][2] == "issued for review"

    proc.run("sheetindex")
    proc.provide_text("300,150")
    assert lay.notes[-1].text.startswith("SHEET INDEX")

    proc.run("dimstyle")
    proc.provide_text("Big")
    proc.provide_text("8")
    proc.provide_text("3")
    assert scene.annot_styles["Big"]["text_height"] == 8.0

    proc.run("annotedit")
    proc.provide_text("55,49")               # near the note
    proc.provide_text("edited")
    assert lay.notes[0].text == "edited"
