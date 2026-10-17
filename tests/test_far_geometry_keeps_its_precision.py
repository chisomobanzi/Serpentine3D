"""A detail 300,000 units out is still the size it was modelled at.

The anchoring in 0.8.1 stopped far geometry swimming while the camera
moved, but the data reaching it had already been rounded: tessellation
cast its vertices to float32 on the way out of the kernel, and out there
that grid is 8mm wide at 100,000 units and 6cm at a million. An anchor
subtracts in float64 and so can only give back digits the data still
has, which left a surveyed building's 4mm reveal standing still and
wrong, two faces on one grid node fighting over every pixel.

So display coordinates stay in double precision as far as the upload,
where the anchor has already made them small (`display_coords` in
utils/math3d.py). Near the origin nothing changes: float32 is good to a
fraction of a micron there and half the memory, which on a scanned
survey is most of the file.
"""

from __future__ import annotations

import numpy as np

from serpentine3d.core import geometry as g
from serpentine3d.core.mesh import MeshShape, mesh_to_display
from serpentine3d.core.tessellate import tessellate
from serpentine3d.ui import viewport as vp
from serpentine3d.utils.math3d import ANCHOR_NEAR, display_coords


FAR = np.array([300000.0, 200000.0, 0.0])
REVEAL = 0.004          # 4mm, under half of float32's grid out at FAR


# -- which precision coordinates come out in ------------------------------

def test_coordinates_far_from_home_keep_their_doubles():
    out = display_coords(FAR + np.array([[0.0, 0.0, 0.0]]))
    assert out.dtype == np.float64


def test_coordinates_near_home_stay_in_float32():
    out = display_coords([[1.0, 2.0, 3.0], [-10.0, 0.0, 4.0]])
    assert out.dtype == np.float32


def test_the_threshold_is_the_anchors_own():
    inside = display_coords([[ANCHOR_NEAR, 0.0, 0.0]])
    outside = display_coords([[ANCHOR_NEAR * 1.01, 0.0, 0.0]])
    assert inside.dtype == np.float32
    assert outside.dtype == np.float64


def test_one_far_corner_is_enough_to_keep_the_whole_array_double():
    """A mesh centred near home can still reach a long way out, and the
    far end is the end that suffers."""
    pts = np.array([[0.0, 0.0, 0.0], [1e6, 0.0, 0.0]])
    assert display_coords(pts).dtype == np.float64


def test_display_coords_is_contiguous_for_the_upload():
    pts = np.asfortranarray(FAR + np.zeros((4, 3)))
    assert display_coords(pts).flags["C_CONTIGUOUS"]


def test_an_empty_array_costs_nothing():
    out = display_coords(np.zeros((0, 3)))
    assert out.dtype == np.float32 and out.shape == (0, 3)


# -- the detail that used to collapse -------------------------------------

def _far_box(size=REVEAL):
    return g.make_box(tuple(FAR), size, size, size)


def test_a_millimetre_detail_out_at_survey_coordinates_survives():
    """The bug itself: a 4mm box 360,000 units out comes back 4mm."""
    mesh = tessellate(_far_box())
    assert mesh.vertices.dtype == np.float64
    span = mesh.vertices.max(axis=0) - mesh.vertices.min(axis=0)
    assert np.abs(span - REVEAL).max() < 1e-9
    # Cast the old way it has no width left along either axis that is far
    # out: both faces land on the same grid node. Only Z survives, and
    # only because the box sits on z = 0.
    old = mesh.vertices.astype(np.float32).astype(np.float64)
    old_span = old.max(axis=0) - old.min(axis=0)
    assert old_span[0] == 0.0 and old_span[1] == 0.0, \
        "float32 holds this box out here, so this test guards nothing"


def test_the_same_box_at_home_is_still_uploaded_as_float32():
    mesh = tessellate(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0))
    assert mesh.vertices.dtype == np.float32
    assert mesh.edge_segments.dtype == np.float32


def test_a_far_boxs_edges_and_corners_keep_their_digits():
    mesh = tessellate(_far_box())
    assert mesh.edge_segments.dtype == np.float64
    lengths = np.linalg.norm(mesh.edge_segments[:, 1]
                             - mesh.edge_segments[:, 0], axis=1)
    assert lengths.min() > REVEAL * 0.999


def test_a_far_curve_is_tessellated_in_double_precision():
    circle = g.make_circle(tuple(FAR), REVEAL, (0.0, 0.0, 1.0))
    mesh = tessellate(circle)
    assert mesh.edge_segments.dtype == np.float64
    radii = np.linalg.norm(
        mesh.edge_segments.reshape(-1, 3) - FAR, axis=1)
    assert np.abs(radii - REVEAL).max() < 1e-9


# -- mesh objects: scans, OBJ, SketchUp ------------------------------------

def _far_mesh_shape(size=REVEAL):
    corners = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]],
                       float) * size + FAR
    return MeshShape(corners, np.array([[0, 1, 2], [0, 2, 3]], np.uint32))


def test_a_far_mesh_object_reaches_the_display_undamaged():
    dm = mesh_to_display(_far_mesh_shape())
    assert dm.vertices.dtype == np.float64
    assert np.abs(dm.vertices - _far_mesh_shape().vertices).max() == 0.0


def test_a_far_mesh_objects_feature_edges_keep_their_digits():
    dm = mesh_to_display(_far_mesh_shape())
    assert dm.edge_segments.dtype == np.float64
    lengths = np.linalg.norm(dm.edge_segments[:, 1] - dm.edge_segments[:, 0],
                             axis=1)
    assert lengths.min() > REVEAL * 0.999


def test_a_mesh_object_at_home_is_unchanged():
    near = MeshShape(_far_mesh_shape().vertices - FAR,
                     np.array([[0, 1, 2], [0, 2, 3]], np.uint32))
    dm = mesh_to_display(near)
    assert dm.vertices.dtype == np.float32
    assert dm.normals.dtype == np.float32


# -- and out the other end, onto the card ----------------------------------

def test_the_anchor_hands_the_card_a_box_it_can_draw():
    """What the GPU actually receives: small float32 numbers that still
    describe a 4mm box, where the old path handed it one point."""
    mesh = tessellate(_far_box())
    anchor = vp.mesh_anchor(mesh)
    assert anchor is not None
    rel = vp.rebased(mesh.vertices, anchor)
    assert rel.dtype == np.float32
    assert np.abs(rel).max() < REVEAL
    wide = rel.astype(np.float64)
    span = wide.max(axis=0) - wide.min(axis=0)
    assert np.abs(span - REVEAL).max() < 1e-9


# -- through undo and the clipboard ---------------------------------------

def test_a_far_mesh_survives_undo_and_paste():
    """The shape bytes used to be absolute float32, so a move of a survey
    mesh came back from undo on a 6cm grid."""
    from serpentine3d.core.geometry import shape_from_bytes, shape_to_bytes
    mesh = _far_mesh_shape()
    blob = shape_to_bytes(mesh)
    back = shape_from_bytes(blob)
    assert np.abs(back.vertices - mesh.vertices).max() < 1e-6
    span = back.vertices.max(axis=0) - back.vertices.min(axis=0)
    assert np.abs(span[:2] - REVEAL).max() < 1e-6


def test_a_mesh_near_home_is_written_the_way_it_always_was():
    from serpentine3d.core.geometry import (_MESH_TAG, shape_from_bytes,
                                            shape_to_bytes)
    near = MeshShape(_far_mesh_shape().vertices - FAR,
                     np.array([[0, 1, 2], [0, 2, 3]], np.uint32))
    blob = shape_to_bytes(near)
    assert blob.startswith(_MESH_TAG)
    assert np.allclose(shape_from_bytes(blob).vertices, near.vertices)


def test_a_dashed_far_edge_is_dashed_in_double_precision():
    """Linetypes rebuild the edge segments, so they are a second way in."""
    mesh = tessellate(_far_box())
    segs = vp._dashed_edge_segments(mesh, (2.0, 1.0), 1.0)
    assert segs.dtype == np.float64
    assert np.abs(np.asarray(segs).reshape(-1, 3) - FAR).max() < REVEAL * 2
