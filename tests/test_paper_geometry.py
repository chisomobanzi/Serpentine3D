"""Geometry that lives on the paper rather than in the model.

A border, a detail bubble, a north arrow — drawn in millimetres on the sheet,
not in the model and not seen through a detail. It is a real shape, so the
commands that offset and trim and fillet work on it the same way they work on
the model; that is the whole reason not to store it as a list of points.

The catch is that `Layout.clone()` is a deepcopy and runs on every undo
checkpoint, while a `TopoDS_Edge` will not pickle at all. A shape is never
edited in place — an edit replaces it — so a checkpoint can share one, which
is the same bargain `SceneObject.clone` already makes.
"""

from __future__ import annotations

import copy

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core import linetype
from serpentine3d.core.layout import Layout, PaperObject
from serpentine3d.core.scene import Scene


def _edge(a=(0.0, 0.0, 0.0), b=(100.0, 0.0, 0.0)):
    return g.make_line(a, b)


@pytest.fixture
def sheet_with_border():
    lay = Layout(name="Sheet1")
    lay.objects.append(PaperObject(shape=_edge(), name="Border"))
    return lay


# ------------------------------------------------------- it is a real shape

def test_the_paper_holds_a_shape_not_a_list_of_points(sheet_with_border):
    obj = sheet_with_border.objects[0]
    lo, hi = g.bbox(obj.shape)
    assert lo == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)
    assert hi == pytest.approx((100.0, 0.0, 0.0), abs=1e-6)


def test_paper_millimetres_are_the_coordinates(sheet_with_border):
    """No detail is involved, so 100 here is 100mm across the sheet — a third
    of the way over an A3 page."""
    assert sheet_with_border.paper_w == 420.0
    _, hi = g.bbox(sheet_with_border.objects[0].shape)
    assert hi[0] / sheet_with_border.paper_w == pytest.approx(100.0 / 420.0)


# --------------------------------------------------------- turning into lines

def test_a_shape_becomes_polylines_in_paper_millimetres(sheet_with_border):
    plines = sheet_with_border.objects[0].polylines
    assert len(plines) == 1
    assert len(plines[0]) >= 2
    assert plines[0][0] == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)
    assert plines[0][-1] == pytest.approx((100.0, 0.0, 0.0), abs=1e-6)


def test_polylines_not_loose_segments(sheet_with_border):
    """A dash pattern has to run along a whole curve, and it cannot if the
    curve arrives as unrelated two-point pieces."""
    obj = PaperObject(shape=g.make_circle((50.0, 50.0, 0.0), 20.0))
    plines = obj.polylines
    assert len(plines) == 1                  # one edge, one polyline
    assert len(plines[0]) > 8                # tessellated, not two points


def test_the_lines_are_worked_out_once(sheet_with_border):
    obj = sheet_with_border.objects[0]
    assert obj.polylines is obj.polylines


def test_replacing_the_shape_expires_the_lines(sheet_with_border):
    obj = sheet_with_border.objects[0]
    before = obj.polylines
    obj.shape = _edge((0, 0, 0), (7, 0, 0))
    assert obj.polylines is not before
    assert obj.polylines[0][-1] == pytest.approx((7.0, 0.0, 0.0), abs=1e-6)


# ------------------------------------------------------- surviving an undo

def test_a_layout_carrying_a_shape_can_still_be_cloned(sheet_with_border):
    """This is what a deepcopy could not do: a TopoDS_Edge will not pickle,
    and every history checkpoint clones every layout."""
    twin = sheet_with_border.clone()
    assert len(twin.objects) == 1
    assert twin.objects[0].name == "Border"


def test_the_clone_shares_the_shape_rather_than_copying_it(sheet_with_border):
    """Sharing is the point, not an accident of the implementation: shapes are
    immutable here, and copying one per checkpoint would be pure cost."""
    twin = sheet_with_border.clone()
    assert twin.objects[0].shape is sheet_with_border.objects[0].shape
    assert twin.objects[0] is not sheet_with_border.objects[0]


def test_a_plain_deepcopy_of_the_layout_works_too(sheet_with_border):
    """Anything that copies a scene reaches a layout eventually, so the fix
    belongs on the object that owns the shape and not at the call sites."""
    twin = copy.deepcopy(sheet_with_border)
    assert twin.objects[0].shape is sheet_with_border.objects[0].shape


def test_editing_the_copy_leaves_the_original_alone(sheet_with_border):
    twin = sheet_with_border.clone()
    twin.objects.append(PaperObject(shape=_edge((0, 0, 0), (5, 5, 0))))
    twin.objects[0].name = "Renamed"
    assert len(sheet_with_border.objects) == 1
    assert sheet_with_border.objects[0].name == "Border"


def test_undo_puts_paper_geometry_back(sheet_with_border):
    """The checkpoint is what all of this is for."""
    scene = Scene()
    scene.layouts.append(sheet_with_border)
    snap = scene.snapshot()
    sheet_with_border.objects.append(
        PaperObject(shape=_edge((0, 0, 0), (7, 7, 0)), name="Bubble"))
    assert len(scene.layouts[0].objects) == 2
    scene.restore(snap)
    assert [o.name for o in scene.layouts[0].objects] == ["Border"]


def test_redo_brings_it_back_again(sheet_with_border):
    scene = Scene()
    scene.layouts.append(sheet_with_border)
    before = scene.snapshot()
    sheet_with_border.objects.append(
        PaperObject(shape=_edge((0, 0, 0), (7, 7, 0)), name="Bubble"))
    after = scene.snapshot()
    scene.restore(before)
    assert len(scene.layouts[0].objects) == 1
    scene.restore(after)
    assert [o.name for o in scene.layouts[0].objects] == ["Border", "Bubble"]


# ------------------------------------------------------------ drawn on a sheet

def _window_on(lay):
    """A window looking at this sheet, fitted to the page."""
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    w.scene.layouts.append(lay)
    w.viewport.space = lay.id
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    return w, lv


def _drawing_of(lay):
    """What the sheet hands to the line drawer for this layout's geometry."""
    _w, lv = _window_on(lay)
    drawn = []
    lv._draw_segs = lambda mvp, segs, color, width: drawn.append(
        (segs, color, width))
    lv._paint_objects(lay, lv._paper_mvp())
    return drawn


def test_the_sheet_draws_its_paper_geometry(sheet_with_border):
    drawn = _drawing_of(sheet_with_border)
    assert len(drawn) == 1
    segs, _color, _width = drawn[0]
    assert segs.shape == (1, 2, 3)
    assert segs[0][0] == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)
    assert segs[0][1] == pytest.approx((100.0, 0.0, 0.0), abs=1e-6)


def test_it_is_drawn_in_the_sheets_ink_by_default(sheet_with_border):
    from serpentine3d.ui.layout_view import LINE_VISIBLE
    _segs, color, _width = _drawing_of(sheet_with_border)[0]
    assert color == LINE_VISIBLE


def test_an_objects_own_colour_wins():
    lay = Layout(name="Sheet1")
    lay.objects.append(PaperObject(shape=_edge(), color=(1.0, 0.0, 0.0)))
    _segs, color, _width = _drawing_of(lay)[0]
    assert color == pytest.approx((1.0, 0.0, 0.0, 1.0))


def test_the_lineweight_is_millimetres_on_the_paper():
    """A lineweight is what it is on a drawing — 0.35mm is 0.35mm wide when
    printed, and so it has to be scaled by the zoom to be drawn on screen."""
    lay = Layout(name="Sheet1")
    lay.objects.append(PaperObject(shape=_edge(), lineweight=6.0))
    _w, lv = _window_on(lay)
    _segs, _color, width = _drawing_of(lay)[0]
    assert width == pytest.approx(6.0 * lv.px_per_mm)


def test_a_hairline_is_still_drawn():
    """0.25mm at a whole A3 page on screen is a quarter of a pixel, and a
    border you cannot see is worse than one a shade too heavy."""
    lay = Layout(name="Sheet1")
    lay.objects.append(PaperObject(shape=_edge(), lineweight=0.25))
    _segs, _color, width = _drawing_of(lay)[0]
    assert width == pytest.approx(1.0)


def test_a_dashed_line_is_drawn_in_pieces():
    """One straight edge, many segments — the pattern runs along it."""
    lay = Layout(name="Sheet1")
    lay.objects.append(PaperObject(shape=_edge(), linetype="Dashed"))
    segs, _color, _width = _drawing_of(lay)[0]
    assert len(segs) > 4
    # and it runs the length of the line, short only of the gap it ends on: a
    # pattern stops where it stops, but a dashed 100mm line that gives up at
    # 40mm is a different bug
    period = sum(linetype.pattern_for("Dashed"))
    assert segs.reshape(-1, 3)[:, 0].max() > 100.0 - period


def test_an_empty_sheet_draws_nothing():
    assert _drawing_of(Layout(name="Sheet1")) == []


# --------------------------------------------------------- drawn by a command

DET = {"x": 20.0, "y": 30.0, "w": 160.0, "h": 120.0,
       "scale_denom": 2.0, "target": [400.0, 250.0, 0.0]}


@pytest.fixture
def bare_sheet():
    """A window on a sheet with no detail entered — paper and nothing else."""
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    lay = Layout(name="Sheet1")
    w.scene.layouts.append(lay)
    w.viewport.space = lay.id
    w.viewport.layout_view.entered_detail = None
    return w, lay


def _run(w, name, *inputs):
    w.run_command(name)
    for text in inputs:
        w.processor.provide_text(text)


def test_a_curve_on_bare_paper_is_drawn_on_the_paper(bare_sheet):
    """What stage 1's refusal was standing in for: there is no model point
    under a sheet, but there is a sheet, and a line drawn on one belongs to
    it."""
    w, lay = bare_sheet
    _run(w, "line", "10,10,0", "110,10,0")
    assert len(lay.objects) == 1
    lo, hi = g.bbox(lay.objects[0].shape)
    assert lo == pytest.approx((10.0, 10.0, 0.0), abs=1e-6)
    assert hi == pytest.approx((110.0, 10.0, 0.0), abs=1e-6)
    # and the model is exactly as empty as it was
    assert w.scene.all() == []


def test_the_numbers_are_millimetres_on_the_sheet(bare_sheet):
    w, lay = bare_sheet
    _run(w, "line", "0,0,0", "210,0,0")
    _, hi = g.bbox(lay.objects[0].shape)
    assert hi[0] == pytest.approx(lay.paper_w / 2.0)     # half an A3 page


@pytest.mark.parametrize(("name", "inputs"), [
    ("line", ("10,10,0", "110,10,0")),
    ("polyline", ("10,10,0", "60,10,0", "60,60,0", "")),
    ("circle", ("50,50,0", "70,50,0")),
    ("rectangle", ("10,10,0", "110,60,0")),
    ("arc", ("10,10,0", "60,40,0", "110,10,0")),
])
def test_every_curve_command_can_draw_on_paper(bare_sheet, name, inputs):
    w, lay = bare_sheet
    _run(w, name, *inputs)
    assert not w.processor.busy                          # it finished
    assert len(lay.objects) == 1, f"{name} drew nothing on the sheet"
    assert w.scene.all() == []


def test_it_is_named_so_the_command_can_say_what_it_made(bare_sheet):
    w, lay = bare_sheet
    said = []
    w.ctx.add_echo_listener(said.append)
    _run(w, "line", "10,10,0", "110,10,0")
    name = lay.objects[0].name
    assert name
    assert name in " ".join(said)


def test_a_second_curve_gets_its_own_name(bare_sheet):
    w, lay = bare_sheet
    _run(w, "line", "10,10,0", "110,10,0")
    _run(w, "line", "10,20,0", "110,20,0")
    assert lay.objects[0].name != lay.objects[1].name


def test_undo_takes_the_paper_curve_away(bare_sheet):
    """The checkpoint is only kept if the scene says it changed, and a layout
    edit has to say so too or there is nothing to undo."""
    w, _lay = bare_sheet
    _run(w, "line", "10,10,0", "110,10,0")
    assert w.history.can_undo
    w.history.undo()
    assert w.scene.layouts[0].objects == []


def test_a_curve_inside_a_detail_still_goes_in_the_model(bare_sheet):
    """A detail is a window onto the model, and drawing through a window puts
    the geometry on the other side of it."""
    from serpentine3d.core.layout import DetailView
    w, lay = bare_sheet
    lay.details.append(DetailView(**DET))
    w.viewport.layout_view.entered_detail = lay.details[0].id
    _run(w, "line", "400,250,0", "500,250,0")
    assert len(w.scene.all()) == 1
    assert lay.objects == []


def test_a_curve_in_the_model_is_untouched():
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.resize(1200, 800)
    assert w.viewport.space == "model"
    _run(w, "line", "0,0,0", "100,0,0")
    assert len(w.scene.all()) == 1


def test_a_point_object_is_refused_rather_than_drawn_invisibly(bare_sheet):
    """A vertex has no edges and the sheet draws lines, so a point on paper
    would be stored and never seen. Refusing says so; storing it lies."""
    w, lay = bare_sheet
    _run(w, "point", "50,50,0")
    assert lay.objects == []
    assert w.scene.all() == []


def test_a_solid_is_still_refused_on_bare_paper(bare_sheet):
    """Paper geometry is flat and in millimetres; a box is neither, so the
    stage-1 refusal still stands for anything that can only mean the model."""
    w, lay = bare_sheet
    _run(w, "box", "0,0,0", "40,40,0", "30")
    assert w.scene.all() == []
    assert lay.objects == []


# -------------------------------------------------------- printed and exported

def test_paper_geometry_is_printed(sheet_with_border):
    """A border that does not come out of the printer is not a border. The PDF
    is checked at the painter rather than in the file, because what matters is
    that the millimetres survived the trip to device dots."""
    from unittest.mock import MagicMock

    from PySide6.QtGui import QPolygonF

    from serpentine3d.fileio.pdf import _paint_layout
    w, _lv = _window_on(sheet_with_border)
    painter = MagicMock()
    k = 600 / 25.4                                   # dots per mm at 600 dpi
    _paint_layout(painter, w, sheet_with_border, k)

    drawn = [c.args[0] for c in painter.drawPolyline.call_args_list
             if c.args and isinstance(c.args[0], QPolygonF)]
    assert drawn, "nothing was drawn for the sheet's paper geometry"
    xs = [p.x() for poly in drawn for p in poly]
    ys = [p.y() for poly in drawn for p in poly]
    assert min(xs) == pytest.approx(0.0, abs=1.0)
    assert max(xs) == pytest.approx(100.0 * k, abs=1.0)
    # paper is y-up and the page is y-down, so y=0 is the bottom of the page
    assert min(ys) == pytest.approx(sheet_with_border.paper_h * k, abs=1.0)


def test_the_printed_line_is_as_heavy_as_its_lineweight(sheet_with_border):
    from unittest.mock import MagicMock

    from serpentine3d.fileio.pdf import _paint_layout
    sheet_with_border.objects[0].lineweight = 0.7
    w, _lv = _window_on(sheet_with_border)
    painter = MagicMock()
    k = 600 / 25.4
    _paint_layout(painter, w, sheet_with_border, k)
    widths = [c.args[0].widthF() for c in painter.setPen.call_args_list
              if c.args and hasattr(c.args[0], "widthF")]
    assert pytest.approx(0.7 * k, abs=0.5) in widths


def test_paper_geometry_is_exported_to_dxf(tmp_path, sheet_with_border):
    """Paper millimetres are already what a 2D DXF wants, so the border goes
    out as it is — on its own layer, so it can be turned off."""
    import ezdxf

    from serpentine3d.fileio.dxf import export_layout_dxf
    w, _lv = _window_on(sheet_with_border)
    path = str(tmp_path / "sheet.dxf")
    export_layout_dxf(w, sheet_with_border, path)

    doc = ezdxf.readfile(path)
    polys = [e for e in doc.modelspace()
             if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "PAPER"]
    assert len(polys) == 1
    pts = [(p[0], p[1]) for p in polys[0].get_points()]
    assert min(p[0] for p in pts) == pytest.approx(0.0, abs=1e-6)
    assert max(p[0] for p in pts) == pytest.approx(100.0, abs=1e-6)


def test_a_dashed_paper_line_is_dashed_in_the_dxf(tmp_path, sheet_with_border):
    import ezdxf

    from serpentine3d.fileio.dxf import export_layout_dxf
    sheet_with_border.objects[0].linetype = "Dashed"
    w, _lv = _window_on(sheet_with_border)
    path = str(tmp_path / "sheet.dxf")
    export_layout_dxf(w, sheet_with_border, path)
    doc = ezdxf.readfile(path)
    poly = next(e for e in doc.modelspace() if e.dxf.layer == "PAPER")
    assert poly.dxf.linetype.upper() == "DASHED"


def test_a_curve_says_it_can_work_in_either_space():
    """Not "paper": the same command draws in the model and through a detail.
    "any" is the honest answer, and it is the viewport that decides which."""
    from serpentine3d.commands.base import resolve
    for name in ("line", "polyline", "circle", "arc", "rectangle"):
        assert resolve(name).space == "any", name
    assert resolve("box").space == "model"


# --------------------------------------------------------- saving and loading

def test_paper_geometry_survives_a_save_and_a_load(tmp_path,
                                                   sheet_with_border):
    from serpentine3d.fileio.native import load_scene, save_scene
    scene = Scene()
    scene.layouts.append(sheet_with_border)
    path = str(tmp_path / "sheet.serp")
    save_scene(scene, path)

    other = Scene()
    load_scene(other, path)
    objs = other.layouts[0].objects
    assert len(objs) == 1
    assert objs[0].name == "Border"
    lo, hi = g.bbox(objs[0].shape)
    assert lo == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)
    assert hi == pytest.approx((100.0, 0.0, 0.0), abs=1e-6)


def test_how_it_is_drawn_is_saved_with_it(tmp_path):
    from serpentine3d.fileio.native import load_scene, save_scene
    lay = Layout(name="Sheet1")
    lay.objects.append(PaperObject(shape=_edge(), color=(1.0, 0.0, 0.0),
                                   linetype="Dashed", lineweight=0.5))
    scene = Scene()
    scene.layouts.append(lay)
    path = str(tmp_path / "sheet.serp")
    save_scene(scene, path)

    other = Scene()
    load_scene(other, path)
    obj = other.layouts[0].objects[0]
    assert obj.color == pytest.approx((1.0, 0.0, 0.0))
    assert obj.linetype == "Dashed"
    assert obj.lineweight == pytest.approx(0.5)


def test_a_file_written_before_any_of_this_still_opens(tmp_path):
    """Sheets saved by 0.5.5 have no `objects` key at all."""
    from serpentine3d.core.layout import layouts_from_json
    lays = layouts_from_json([{"id": "L1", "name": "Sheet1",
                               "paper_w": 420.0, "paper_h": 297.0}])
    assert lays[0].objects == []
