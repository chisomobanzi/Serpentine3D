"""Point objects on paper.

`point` was refused on a sheet, and the reason was honest: a point object is a
vertex, a vertex has no edges, and the sheet drew its geometry by walking edges.
The point would have been stored and never seen again.

So the sheet draws vertices too. A point mark is a working mark rather than ink
— a fixed size on screen however far the page is zoomed, and no part of the
print — but it is geometry like the rest of it: it can be picked by clicking it,
a band takes it, and it counts towards what the sheet's own bounds are.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import (DetailView, Layout, PaperObject,
                                      paper_object_at, paper_object_bounds,
                                      paper_object_crosses)
from serpentine3d.ui.layout_view import point_marks

DET = {"x": 20.0, "y": 30.0, "w": 160.0, "h": 120.0,
       "scale_denom": 2.0, "target": [400.0, 250.0, 0.0]}


@pytest.fixture
def sheet():
    w = MainWindow()
    w.resize(1200, 800)
    lay = Layout(name="Sheet1")
    lay.details.append(DetailView(**DET))
    w.scene.layouts.append(lay)
    w.viewport.space = lay.id
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    lv.entered_detail = None
    return w, lv, lay


def _dot(x=60.0, y=70.0):
    return PaperObject(shape=g.make_point((x, y, 0.0)), name="Dot")


# -- the shape says where it is -----------------------------------------------

def test_a_vertex_is_a_free_point():
    assert g.free_points(g.make_point((3.0, 4.0, 5.0))) == [(3.0, 4.0, 5.0)]


def test_the_corners_of_a_curve_are_not_free_points():
    """A vertex an edge already owns is drawn by that edge, not on its own."""
    assert g.free_points(g.make_line((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))) == []


def test_paper_geometry_carries_its_points_in_millimetres():
    pts = _dot().points
    assert len(pts) == 1
    assert tuple(pts[0]) == pytest.approx((60.0, 70.0, 0.0))


def test_the_points_expire_when_the_shape_is_swapped():
    """Same bargain `polylines` makes: the answer is keyed on the shape."""
    obj = _dot()
    assert obj.points is obj.points
    obj.shape = g.make_point((1.0, 2.0, 0.0))
    assert tuple(obj.points[0]) == pytest.approx((1.0, 2.0, 0.0))


def test_a_point_has_no_line_work_to_print():
    """Nothing changes for PDF or DXF: they draw polylines, and there are
    none. A point is a mark you work to, not ink on the printed sheet."""
    assert _dot().polylines == []


# -- picking it ----------------------------------------------------------------

def test_a_click_on_a_point_picks_it():
    lay = Layout(name="Sheet1")
    lay.objects.append(_dot())
    assert paper_object_at(lay, 60.5, 70.4) is lay.objects[0]


def test_a_click_away_from_a_point_picks_nothing():
    lay = Layout(name="Sheet1")
    lay.objects.append(_dot())
    assert paper_object_at(lay, 80.0, 70.0) is None


def test_a_band_over_a_point_takes_it():
    obj = _dot()
    assert paper_object_crosses(obj, 50.0, 60.0, 70.0, 80.0)
    assert not paper_object_crosses(obj, 0.0, 0.0, 10.0, 10.0)


def test_a_point_is_as_big_as_where_it_is():
    assert paper_object_bounds(_dot()) == pytest.approx((60.0, 70.0,
                                                         60.0, 70.0))


def test_bounds_take_in_points_and_line_work_together():
    obj = PaperObject(shape=g.make_compound([
        g.make_line((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
        g.make_point((0.0, 40.0, 0.0))]))
    x0, y0, x1, y1 = paper_object_bounds(obj)
    assert (x0, y0) == pytest.approx((0.0, 0.0))
    assert (x1, y1) == pytest.approx((10.0, 40.0))


# -- drawing it ----------------------------------------------------------------

def test_a_point_is_drawn_as_a_cross():
    segs = point_marks([(60.0, 70.0, 0.0)], 2.0)
    assert segs.shape == (2, 2, 3)
    assert segs[0][0] == pytest.approx((58.0, 70.0, 0.0))
    assert segs[0][1] == pytest.approx((62.0, 70.0, 0.0))
    assert segs[1][0] == pytest.approx((60.0, 68.0, 0.0))
    assert segs[1][1] == pytest.approx((60.0, 72.0, 0.0))


def test_no_points_is_no_marks():
    assert len(point_marks([], 2.0)) == 0


def test_the_mark_is_the_same_size_however_far_you_zoom(sheet):
    """A point mark is a marker, not geometry with a width: zooming in on the
    page must not grow it into a plus sign the size of the drawing."""
    from serpentine3d.ui.layout_view import POINT_MARK_PX
    _w, lv, lay = sheet
    lay.objects.append(_dot())
    lv.px_per_mm = 4.0
    small = lv._point_mark_size()
    lv.px_per_mm = 16.0
    assert lv._point_mark_size() == pytest.approx(small / 4.0)
    assert small * 4.0 == pytest.approx(POINT_MARK_PX)


def test_the_sheet_draws_the_points_it_holds():
    """The paint path is GL, so read it rather than run it."""
    import inspect

    from serpentine3d.ui.layout_view import LayoutView
    src = inspect.getsource(LayoutView._paint_objects)
    assert "point_marks" in src
    assert "obj.points" in src


# -- running the command -------------------------------------------------------

def test_point_is_allowed_on_bare_paper():
    from serpentine3d.commands.base import resolve
    assert resolve("point").space == "any"


def test_a_point_placed_on_the_sheet_lands_on_the_sheet(sheet):
    w, _lv, lay = sheet
    w.run_command("point")
    w.processor.provide_text("60,70,0")
    w.processor.provide_text("")
    assert w.scene.all() == []               # not in the model at paper numbers
    assert len(lay.objects) == 1
    assert tuple(lay.objects[0].points[0]) == pytest.approx((60.0, 70.0, 0.0))


def test_a_point_on_the_sheet_can_be_deleted(sheet):
    _w, lv, lay = sheet
    lay.objects.append(_dot())
    lv.selected = [("object", lay.objects[0])]
    assert lv.delete_selected()
    assert lay.objects == []


def test_a_point_survives_being_saved_and_opened(sheet, tmp_path):
    """A vertex is a shape, and paper geometry is stored as its shape, so
    nothing here is new — but a point that came back as nothing would be worse
    than not having drawn it at all."""
    from serpentine3d.core.scene import Scene
    from serpentine3d.fileio import native
    w, _lv, lay = sheet
    lay.objects.append(_dot())
    path = str(tmp_path / "sheet.s3d")
    native.save_scene(w.scene, path)
    back = Scene()
    native.load_scene(back, path)
    pts = [p for o in back.layouts[0].objects for p in o.points]
    assert len(pts) == 1
    assert tuple(pts[0]) == pytest.approx((60.0, 70.0, 0.0))


def test_a_point_placed_in_a_detail_is_a_model_point(sheet):
    w, lv, lay = sheet
    lv.entered_detail = lay.details[0].id
    w.run_command("point")
    w.processor.provide_text("400,250,0")
    w.processor.provide_text("")
    assert lay.objects == []
    objs = w.scene.all()
    assert len(objs) == 1
    assert np.asarray(g.point_coords(objs[0].shape)) == pytest.approx(
        (400.0, 250.0, 0.0))
