"""A linear dimension is an object in the model, not only a mark on a sheet.

Asked for: linear dimensions as a real Serpentine3D object, one you can make
yourself and whose text height, decimal places and suffix you can change,
and the linear dimensions in DXF and 3dm files coming in as these.

A dimension measures two points along a direction and draws its extension
lines, dimension line, arrows and text from them. It is rebuilt whenever it
changes, so its number is always what it measures: move, turn or scale it
and the number follows. Its text reads left to right and upright however
it was turned or mirrored.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.dimension import DimensionShape


def _dim(**style):
    return DimensionShape((0, 0, 0), (100, 0, 0), (0, 20, 0),
                          direction=(1, 0, 0), **style)


# --- the shape --------------------------------------------------------------

def test_a_dimension_measures_and_says_so():
    dim = _dim()
    assert dim.measured == pytest.approx(100.0)
    assert dim.label == "100.00"
    assert g.shape_kind(dim) == "curve", "drawn as the curves it is made of"


def test_decimals_and_suffix_change_what_it_says():
    dim = _dim(decimals=0, suffix=" mm")
    assert dim.label == "100 mm"
    assert dim.edited(decimals=3, suffix="cm").label == "100.000 cm",         "a suffix is always set off by one space"
    assert dim.edited(suffix="  cm ").suffix == "cm"


def test_typed_text_replaces_the_number_and_keeps_it_with_brackets():
    assert _dim(text="Wall").label == "Wall"
    assert _dim(text="<> clear", decimals=0).label == "100 clear"


def test_a_horizontal_dimension_measures_only_along_its_direction():
    dim = DimensionShape((0, 0, 0), (30, 40, 0), (0, 60, 0),
                         direction=(1, 0, 0))
    assert dim.measured == pytest.approx(30.0)
    aligned = DimensionShape((0, 0, 0), (30, 40, 0), (0, 60, 0))
    assert aligned.measured == pytest.approx(50.0)


def test_its_line_runs_through_the_point_it_was_placed_at():
    lo, hi = g.bbox(_dim(text_height=5.0, arrow_size=4.0))
    assert lo[0] == pytest.approx(0.0, abs=1e-6)
    assert hi[0] == pytest.approx(100.0, abs=1e-6)
    assert lo[1] == pytest.approx(2.5, abs=1e-6), \
        "its extension lines stand off the points it measures"
    assert hi[1] > 20.0 + 5.0, "its text stands over the line"


def test_text_height_changes_the_lettering():
    small = g.bbox(_dim(text_height=2.0))[1][1]
    big = g.bbox(_dim(text_height=8.0))[1][1]
    assert big > small + 5.0


def test_ticks_replace_arrows():
    assert len(_dim(arrow="tick").to_curves()) != len(_dim().to_curves()) or \
        g.bbox(_dim(arrow="tick"))[0][0] < -0.5, "the line runs past a tick"


def test_scaled_it_measures_the_new_length_and_grows_its_text():
    dim = g.apply_matrix(_dim(text_height=5.0), np.diag([2., 2., 2., 1.]))
    assert isinstance(dim, DimensionShape)
    assert dim.label == "200.00"
    assert dim.text_height == pytest.approx(10.0)


def test_mirrored_its_text_still_reads():
    mirror = np.diag([-1., 1., 1., 1.])
    dim = g.apply_matrix(_dim(), mirror)
    _origin, along, across, normal = dim.frame()
    assert along == pytest.approx((1, 0, 0))
    assert across == pytest.approx((0, 1, 0))
    assert normal == pytest.approx((0, 0, 1))
    assert dim.label == "100.00"


def test_turned_upside_down_its_text_still_reads():
    turn = np.array([[-1., 0, 0, 0], [0, -1., 0, 0], [0, 0, 1., 0],
                     [0, 0, 0, 1.]])
    _origin, along, _across, _normal = g.apply_matrix(_dim(), turn).frame()
    assert along == pytest.approx((1, 0, 0))


def test_a_vertical_dimension_reads_from_below():
    dim = DimensionShape((0, 0, 0), (0, 50, 0), (-10, 0, 0),
                         direction=(0, 1, 0))
    _origin, along, across, _normal = dim.frame()
    assert along == pytest.approx((0, 1, 0))
    assert across == pytest.approx((-1, 0, 0)), "text on its left, as drawn"


def test_it_survives_a_save():
    dim = _dim(decimals=1, suffix=" m", text="<>!", arrow="tick",
               font_family="arial")
    back = g.shape_from_bytes(g.shape_to_bytes(dim))
    assert isinstance(back, DimensionShape)
    assert back.label == "100.0 m!"
    assert back.style == dim.style
    assert back.p2 == pytest.approx((100, 0, 0))


def test_it_snaps_to_what_it_measures():
    from serpentine3d.core.snaps import snap_points_for
    points = [p for p, _kind in snap_points_for(_dim())]
    assert any(np.allclose(p, (100, 0, 0)) for p in points)
    assert any(np.allclose(p, (100, 20, 0)) for p in points)


def test_a_dimension_goes_to_curves():
    curves = _dim().to_curves()
    assert len(curves) > 5
    assert all(not isinstance(c, DimensionShape) for c in curves)


# --- the command ------------------------------------------------------------

def _dims(scene):
    return [o for o in scene.all() if isinstance(o.shape, DimensionShape)]


def test_the_command_places_a_horizontal_dimension(env):
    scene, sel, _hist, _ctx, proc = env
    proc.run("dim")
    proc.provide((0.0, 0.0, 0.0))
    proc.provide((30.0, 40.0, 0.0))
    proc.provide((10.0, 60.0, 0.0))           # pulled out above: horizontal

    (dim,) = _dims(scene)
    assert dim.shape.measured == pytest.approx(30.0)
    assert sel.ids == [dim.id]


def test_pulled_out_sideways_it_measures_upright(env):
    scene, _sel, _hist, _ctx, proc = env
    proc.run("dim")
    proc.provide((0.0, 0.0, 0.0))
    proc.provide((30.0, 40.0, 0.0))
    proc.provide((60.0, 20.0, 0.0))

    (dim,) = _dims(scene)
    assert dim.shape.measured == pytest.approx(40.0)


def test_aligned_measures_between_the_points(env):
    scene, _sel, _hist, _ctx, proc = env
    proc.run("dim")
    proc.provide((0.0, 0.0, 0.0))
    proc.provide((30.0, 40.0, 0.0))
    proc.set_option("Direction", "Aligned")
    proc.provide((0.0, 10.0, 0.0))

    (dim,) = _dims(scene)
    assert dim.shape.measured == pytest.approx(50.0)


def test_a_new_dimension_looks_like_the_last(env):
    scene, _sel, _hist, _ctx, proc = env
    scene.add(_dim(text_height=7.0, decimals=0, suffix=" mm"))
    proc.run("dim")
    proc.provide((0.0, 0.0, 0.0))
    proc.provide((10.0, 0.0, 0.0))
    proc.provide((5.0, 5.0, 0.0))

    newest = _dims(scene)[-1].shape
    assert newest.text_height == pytest.approx(7.0)
    assert newest.label == "10 mm"


def test_the_first_reads_at_the_size_of_what_it_measures(env):
    scene, _sel, _hist, _ctx, proc = env
    proc.run("dim")
    proc.provide((0.0, 0.0, 0.0))
    proc.provide((4000.0, 0.0, 0.0))
    proc.provide((0.0, 500.0, 0.0))

    (dim,) = _dims(scene)
    assert 50 <= dim.shape.text_height <= 200
    assert math.isclose(dim.shape.arrow_size, dim.shape.text_height)


# --- properties -------------------------------------------------------------

def _panel_with(dim):
    from PySide6.QtWidgets import QApplication
    from serpentine3d.core.history import History
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    from serpentine3d.ui.properties import PropertiesPanel
    QApplication.instance() or QApplication([])
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    props = PropertiesPanel(scene, selection, history)
    obj = scene.add(dim, name="Dimension")
    selection.set([obj.id])
    return scene, history, props, obj


def test_properties_show_and_change_a_dimension():
    scene, history, props, obj = _panel_with(_dim(text_height=5.0))
    assert props.form.isRowVisible(props.dim_decimals)
    assert props.describe("objects").detail.startswith("Dimension")
    assert props.dim_text.placeholderText() == "100.00"

    props.dim_decimals.setValue(0)
    props.dim_suffix.setText(" mm")
    props.dim_suffix.editingFinished.emit()
    props.dim_text_height.setValue(8.0)
    dim = scene.get(obj.id).shape
    assert dim.label == "100 mm"
    assert dim.text_height == pytest.approx(8.0)

    history.undo()
    assert scene.get(obj.id).shape.label == "100.00", \
        "a run of edits to one dimension is one undo step"


def test_sizes_step_by_a_tenth_at_two_decimals():
    _scene, _history, props, _obj = _panel_with(_dim(text_height=0.5,
                                                     arrow_size=0.5))
    for box in (props.dim_text_height, props.dim_arrow_size):
        assert box.decimals() == 2
        box.stepUp()
        assert box.value() == pytest.approx(0.6)


def test_sizes_from_5_up_step_by_one():
    _scene, _history, props, _obj = _panel_with(_dim(text_height=4.9,
                                                     arrow_size=5.0))
    box = props.dim_text_height
    box.stepUp()
    assert box.value() == pytest.approx(5.0)
    box.stepUp()
    assert box.value() == pytest.approx(6.0)
    box = props.dim_arrow_size
    box.stepUp()
    assert box.value() == pytest.approx(6.0)
    box.stepDown()
    box.stepDown()
    assert box.value() == pytest.approx(4.0)
    box.stepDown()
    assert box.value() == pytest.approx(3.9), "below 5 by tenths again"


def test_sizes_from_50_up_step_by_ten():
    _scene, _history, props, _obj = _panel_with(_dim(text_height=49.0))
    box = props.dim_text_height
    box.stepUp()
    assert box.value() == pytest.approx(50.0)
    box.stepUp()
    assert box.value() == pytest.approx(60.0)
    box.stepDown()
    box.stepDown()
    assert box.value() == pytest.approx(40.0)
    box.stepDown()
    assert box.value() == pytest.approx(39.0)


def test_typed_text_goes_over_the_number():
    scene, _history, props, obj = _panel_with(_dim())
    props.dim_text.setText("<> clear")
    props.dim_text.editingFinished.emit()
    assert scene.get(obj.id).shape.label == "100.00 clear"


def test_properties_hide_the_dimension_rows_for_anything_else():
    scene, _history, props, obj = _panel_with(_dim())
    line = scene.add(g.make_line((0, 0, 0), (1, 0, 0)))
    props.selection.set([line.id])
    assert not props.form.isRowVisible(props.dim_decimals)


# --- the drawing file -------------------------------------------------------

def test_a_dimension_survives_a_saved_drawing(tmp_path):
    from serpentine3d.core.scene import Scene
    from serpentine3d.fileio import native

    scene = Scene()
    obj = scene.add(_dim(decimals=0, suffix=" mm", arrow="tick"),
                    name="Dimension")
    scene.update(obj.id, color=(1.0, 0.0, 0.0))
    path = str(tmp_path / "dims.serp")
    native.save_scene(scene, path)

    back = Scene()
    native.load_scene(back, path)
    (again,) = back.all()
    assert isinstance(again.shape, DimensionShape)
    assert again.shape.label == "100 mm"
    assert again.shape.arrow == "tick"
    assert again.color == pytest.approx((1.0, 0.0, 0.0))


def test_a_drawing_with_a_dimension_says_which_reader_it_needs(
        tmp_path, monkeypatch):
    from serpentine3d.core.scene import Scene
    from serpentine3d.fileio import native

    scene = Scene()
    scene.add(_dim())
    path = str(tmp_path / "dims.serp")
    native.save_scene(scene, path)
    monkeypatch.setattr(native, "FORMAT_VERSION", 8)
    with pytest.raises(ValueError, match="0.12.3"):
        native.load_scene(Scene(), path)

