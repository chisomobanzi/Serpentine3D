"""A flat face gets no isocurves, however its surface is spelled.

Isocurves describe curvature. On a flat face they are straight lines
lying in the plane of the edges around them, so they say nothing the
boundary has not already said. `_face_isocurves` used to decide by
asking OCCT for the surface type and bailing only on GeomAbs_Plane,
which is true of a box but not of the flat wall of anything built by
sweeping a NURBS curve, or of any extrusion read out of a .3dm, where
every face arrives as a BSpline. Those walls came back covered in
isocurves. Flatness is a property of the geometry, not of the name
OCCT happens to store it under.
"""

import numpy as np

from serpentine3d.core import geometry as g
from serpentine3d.core.tessellate import _face_isocurves, tessellate


def _isos(shape):
    return sum(len(_face_isocurves(f)) for f in g.faces_of(shape))


def test_a_prism_swept_from_a_nurbs_profile_has_no_isocurves():
    """The flat sides of a NURBS-profiled prism are still flat."""
    profile = g.make_control_curve(
        [(0.0, 0.0, 0.0), (50.0, 0.0, 0.0), (100.0, 0.0, 0.0)])
    wall = g.extrude(profile, (0.0, 0.0, 1.0), 30.0)
    # OCCT calls this a surface of extrusion, not a plane
    assert _isos(wall) == 0


def test_a_bent_sweep_keeps_its_isocurves():
    """Curvature is exactly what they are for, so it stays drawn."""
    profile = g.make_control_curve(
        [(0.0, 0.0, 0.0), (50.0, 40.0, 0.0), (100.0, 0.0, 0.0)])
    assert _isos(g.extrude(profile, (0.0, 0.0, 1.0), 30.0)) > 0


def test_a_cylinder_keeps_its_isocurves():
    """Nothing about the round cases changes."""
    assert _isos(g.make_cylinder((0.0, 0.0, 0.0), 40.0, 30.0)) > 0


def test_a_box_still_has_none():
    assert _isos(g.make_box((0.0, 0.0, 0.0), 100.0, 50.0, 30.0)) == 0


def test_the_display_mesh_carries_no_iso_segments_for_a_flat_sweep():
    """End to end: what the viewport would actually be handed."""
    profile = g.make_control_curve(
        [(0.0, 0.0, 0.0), (50.0, 0.0, 0.0), (100.0, 0.0, 0.0)])
    mesh = tessellate(g.extrude(profile, (0.0, 0.0, 1.0), 30.0))
    assert mesh.iso_segments is None or len(mesh.iso_segments) == 0


def test_a_flat_face_that_leans_is_still_flat():
    """Planarity is not axis alignment."""
    profile = g.make_control_curve(
        [(0.0, 0.0, 0.0), (30.0, 40.0, 10.0), (60.0, 80.0, 20.0)])
    wall = g.extrude(profile, (0.0, 0.0, 1.0), 30.0)
    assert _isos(wall) == 0


def test_a_trimmed_flat_face_draws_none_either():
    """A slab with a hole through it: every isocurve is the hole's.

    The slab's own faces are flat but now carry an inner trim loop, so
    this is the case where a lazy "does it have one boundary" shortcut
    would have gone wrong.
    """
    outer = g.make_polyline([(0.0, 0.0, 0.0), (100.0, 0.0, 0.0),
                             (100.0, 100.0, 0.0), (0.0, 100.0, 0.0)],
                            closed=True)
    slab = g.extrude(outer, (0.0, 0.0, 1.0), 10.0, cap=True)
    drill = g.make_cylinder((50.0, 50.0, -5.0), 20.0, 20.0)
    cut = g.boolean_difference(slab, drill)
    assert _isos(cut) == _isos(drill) > 0
