"""Tests for the Rhino daily-driver gap batch: pipe, points, borders,
untrim, edge surfaces, isocurves."""

import math

import pytest

from serpentine3d.core import geometry as g


# --- point objects -----------------------------------------------------------

def test_make_point():
    v = g.make_point((1, 2, 3))
    assert g.shape_kind(v) == "point"
    assert g.point_coords(v) == pytest.approx((1, 2, 3))


# --- pipe --------------------------------------------------------------------

def test_pipe_straight_rail_capped_volume():
    rail = g.make_line((0, 0, 0), (10, 0, 0))
    solid = g.pipe(rail, 2.0)
    assert g.shape_kind(solid) == "solid"
    assert g.volume(solid) == pytest.approx(math.pi * 4 * 10, rel=1e-6)


def test_pipe_uncapped_is_surface():
    rail = g.make_line((0, 0, 0), (10, 0, 0))
    srf = g.pipe(rail, 2.0, cap=False)
    assert g.shape_kind(srf) == "surface"


def test_pipe_polyline_rail():
    rail = g.make_polyline([(0, 0, 0), (10, 0, 0), (10, 10, 0)])
    solid = g.pipe(rail, 1.0)
    assert g.shape_kind(solid) == "solid"
    assert g.volume(solid) > math.pi * 1 * 15  # more than 15 units of tube


def test_pipe_bad_radius():
    rail = g.make_line((0, 0, 0), (10, 0, 0))
    with pytest.raises(g.GeometryError):
        g.pipe(rail, 0)


# --- free boundaries / dupborder ----------------------------------------------

def test_free_boundaries_open_sheet():
    line = g.make_line((0, 0, 0), (10, 0, 0))
    sheet = g.extrude(line, (0, 0, 1), 5.0)
    wires = g.free_boundaries(sheet)
    assert len(wires) == 1
    assert g.curve_length(wires[0]) == pytest.approx(30.0)


def test_free_boundaries_solid_has_none():
    box = g.make_box((0, 0, 0), 1, 1, 1)
    assert g.free_boundaries(box) == []


# --- untrim --------------------------------------------------------------------

def _annulus():
    disc = g.planar_face(g.make_circle((0, 0, 0), 5))
    small = g.planar_face(g.make_circle((0, 0, 0), 1))
    return g.boolean_difference(disc, small)


def test_untrim_holes_restores_disc():
    annulus = _annulus()
    assert g.surface_area(annulus) == pytest.approx(math.pi * 24, rel=1e-4)
    fixed = g.untrim(annulus, holes_only=True)
    assert g.surface_area(fixed) == pytest.approx(math.pi * 25, rel=1e-4)


def test_untrim_all_on_partial_revolve():
    line = g.make_line((5, 0, 0), (5, 0, 10))
    quarter = g.revolve(line, (0, 0, 0), (0, 0, 1), 90)
    full = g.untrim(quarter, holes_only=False)
    assert g.surface_area(full) == pytest.approx(2 * math.pi * 5 * 10,
                                                 rel=1e-3)


# --- edge surface ---------------------------------------------------------------

def test_edge_surface_four_lines_unordered():
    a = g.make_line((0, 0, 0), (10, 0, 0))
    b = g.make_line((10, 0, 0), (10, 10, 0))
    c = g.make_line((10, 10, 0), (0, 10, 0))
    d = g.make_line((0, 10, 0), (0, 0, 0))
    srf = g.edge_surface([a, c, b, d])  # deliberately out of order
    assert g.shape_kind(srf) == "surface"
    assert g.surface_area(srf) == pytest.approx(100, rel=1e-4)


def test_edge_surface_three_lines():
    a = g.make_line((0, 0, 0), (10, 0, 0))
    b = g.make_line((10, 0, 0), (5, 8, 0))
    c = g.make_line((5, 8, 0), (0, 0, 0))
    srf = g.edge_surface([a, b, c])
    assert g.surface_area(srf) == pytest.approx(40, rel=1e-3)


def test_edge_surface_two_curves_ruled():
    a = g.make_line((0, 0, 0), (10, 0, 0))
    b = g.make_line((0, 5, 3), (10, 5, 3))
    srf = g.edge_surface([a, b])
    assert g.shape_kind(srf) == "surface"
    (mn, mx) = g.bbox(srf)
    assert mx[2] == pytest.approx(3, abs=1e-6)


def test_edge_surface_disconnected_rejected():
    a = g.make_line((0, 0, 0), (10, 0, 0))
    b = g.make_line((50, 50, 0), (60, 50, 0))
    c = g.make_line((60, 50, 0), (50, 55, 0))
    with pytest.raises(g.GeometryError):
        g.edge_surface([a, b, c])


# --- isocurve --------------------------------------------------------------------

def test_iso_curve_on_cylinder():
    line = g.make_line((3, 0, 0), (3, 0, 10))
    cyl = g.revolve(line, (0, 0, 0), (0, 0, 1), 360)
    # along U on a surface of revolution = around the circumference
    around = g.iso_curve(cyl, (3, 0, 5), along="u")
    assert g.curve_length(around) == pytest.approx(2 * math.pi * 3, rel=1e-4)
    up = g.iso_curve(cyl, (3, 0, 5), along="v")
    assert g.curve_length(up) == pytest.approx(10, rel=1e-6)
