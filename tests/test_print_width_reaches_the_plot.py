"""A layer's print width has to reach the paper the detail plots on.

Setting a layer to plot at 0.5mm means every edge of every object on it
comes out of the layout at 0.5mm, in the PDF and in the DXF alike. The
hidden-line pass already knows which object each edge came from, so the
plot groups the edges by the pen they take and puts each group down once.

A layer left at the device default plots the way the detail always has, a
thin default line, so an existing drawing prints exactly as before.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout, merge_line_groups
from serpentine3d.ui.camera import STANDARD_VIEWS

ezdxf = pytest.importorskip("ezdxf")


# -- the pure grouping helper -------------------------------------------------

def test_no_line_work_is_no_groups():
    assert merge_line_groups([]) == []


def test_one_pen_gathers_its_objects():
    a, b = [np.zeros((2, 2))], [np.ones((2, 2))]
    groups = merge_line_groups([(0.5, "Continuous", a),
                                (0.5, "Continuous", b)])
    assert len(groups) == 1
    width, name, polys = groups[0]
    assert (width, name) == (0.5, "Continuous")
    assert len(polys) == 2


def test_different_widths_are_different_groups():
    groups = merge_line_groups([(0.5, "Continuous", [np.zeros((2, 2))]),
                                (0.25, "Continuous", [np.ones((2, 2))])])
    assert {w for w, _n, _p in groups} == {0.5, 0.25}


def test_same_width_but_a_different_dash_splits():
    groups = merge_line_groups([(0.5, "Continuous", [np.zeros((2, 2))]),
                                (0.5, "Dashed", [np.ones((2, 2))])])
    assert len(groups) == 2


def test_first_seen_order_is_kept():
    groups = merge_line_groups([(0.7, "Continuous", [np.zeros((2, 2))]),
                                (0.2, "Continuous", [np.ones((2, 2))])])
    assert [w for w, _n, _p in groups] == [0.7, 0.2]


# -- through the detail to the paper ------------------------------------------

def _sheet_with_box_on(print_width):
    """A front-view detail of one box, on a layer plotted at `print_width`."""
    w = MainWindow()
    w.resize(1200, 800)
    lid = w.scene.layers.create("Plot").id
    w.scene.layers.set_print_width(lid, print_width)
    w.scene.add(g.make_box((-20.0, -20.0, 0.0), 40.0, 40.0, 40.0),
                layer_id=lid)
    lay = Layout(name="Sheet1")
    az, el = STANDARD_VIEWS["front"]
    det = DetailView(x=40.0, y=60.0, w=200.0, h=150.0, azimuth=az,
                     elevation=el, target=[0.0, 0.0, 20.0], scale_denom=2.0,
                     display_mode="wireframe")
    lay.details.append(det)
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    return w, lv, lay, det


def test_the_hlr_data_carries_the_layers_print_width():
    w, lv, _lay, det = _sheet_with_box_on(0.5)
    try:
        data = lv._detail_hlr(det)
        widths = {round(width, 6) for width, _n, polys
                  in data["visible_groups"] if polys}
        assert widths == {0.5}
    finally:
        w.mark_saved()
        w.close()


def test_the_dxf_plots_visible_edges_at_the_print_width(tmp_path):
    from serpentine3d.fileio.dxf import export_layout_dxf
    w, _lv, lay, _det = _sheet_with_box_on(0.35)
    try:
        path = str(tmp_path / "sheet.dxf")
        export_layout_dxf(w, lay, path)
    finally:
        w.mark_saved()
        w.close()
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    weights = {e.dxf.lineweight for e in msp
               if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "VISIBLE"}
    assert weights == {35}          # 0.35mm in DXF's 1/100mm


def test_a_default_layer_sets_no_dxf_lineweight(tmp_path):
    """Nothing set means the plot stays the way it has always drawn."""
    from serpentine3d.fileio.dxf import export_layout_dxf
    w, _lv, lay, _det = _sheet_with_box_on(0.0)
    try:
        path = str(tmp_path / "sheet.dxf")
        export_layout_dxf(w, lay, path)
    finally:
        w.mark_saved()
        w.close()
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    weights = {e.dxf.lineweight for e in msp
               if e.dxftype() == "LWPOLYLINE" and e.dxf.layer == "VISIBLE"}
    assert weights == {-1}          # ezdxf's "by layer" default, unchanged


def test_the_pdf_pen_is_the_print_width():
    """The PDF draws each group with a pen the width the layer plots at."""
    from serpentine3d.fileio import pdf
    w, lv, lay, det = _sheet_with_box_on(0.6)
    try:
        pens = []

        class Recorder:
            def save(self): pass
            def restore(self): pass
            def setClipRect(self, *a): pass
            def setPen(self, pen): pens.append(pen.widthF())
            def drawPolyline(self, *a): pass
            def drawLine(self, *a): pass

        k = 1.0
        pdf._paint_detail_vector(Recorder(), lv, det, lay, k)
        # the visible group is drawn at 0.6mm * k; nothing at the old 0.3mm
        assert any(abs(wd - 0.6) < 1e-6 for wd in pens)
        assert not any(abs(wd - 0.3) < 1e-6 for wd in pens)
    finally:
        w.mark_saved()
        w.close()
