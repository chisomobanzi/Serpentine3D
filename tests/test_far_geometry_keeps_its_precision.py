"""A detail 300,000 units out is still the size it was modelled at.

The anchoring in 0.8.1 stopped far geometry swimming while the camera
moved, but the data reaching it had already been rounded: tessellation
cast its vertices to float32 on the way out of the kernel, and out there
that grid is 8mm wide at 100,000 units and 6cm at a million. That left a
surveyed building's 4mm reveal standing still and wrong, two faces on
one grid node fighting over every pixel.

A display mesh keeps its coordinates as float32 offsets from the point
it sits at (core/tessellate.py), so four bytes hold a fraction of a
micron wherever it is, and a survey costs no more memory than a model at
home. What the kernel hands over is simply the coordinates it worked
out, in the doubles it worked them out in; the mesh does the rest.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.mesh import MeshShape, mesh_to_display
from serpentine3d.core.tessellate import DisplayMesh, tessellate
from serpentine3d.ui import viewport as vp


FAR = np.array([300000.0, 200000.0, 0.0])
REVEAL = 0.004          # 4mm, under half of float32's grid out at FAR


# -- how a mesh keeps what it is given ------------------------------------

def _mesh_of(points):
    mesh = DisplayMesh()
    mesh.vertices = np.asarray(points, float)
    return mesh


def test_a_far_mesh_keeps_offsets_from_where_it_sits():
    mesh = _mesh_of(FAR + np.array([[0.0, 0.0, 0.0], [REVEAL, 0.0, 0.0]]))

    assert mesh.far
    assert mesh.local.dtype == np.float32
    assert np.abs(mesh.local).max() <= REVEAL
    assert np.abs(mesh.origin - FAR).max() < 1.0


def test_a_mesh_at_home_carries_no_origin_at_all():
    mesh = _mesh_of([[1.0, 2.0, 3.0], [-10.0, 0.0, 4.0]])

    assert not mesh.far
    assert mesh.local.dtype == np.float32
    assert np.array_equal(mesh.origin, np.zeros(3))


def test_the_world_s_coordinates_come_back_as_they_went_in():
    points = FAR + np.array([[0.0, 0.0, 0.0], [REVEAL, REVEAL, REVEAL]])
    mesh = _mesh_of(points)

    assert np.abs(mesh.vertices - points).max() < 1e-7


def test_every_array_is_measured_from_the_same_point():
    """A mesh's edges and its faces are in the same place by definition,
    so they share an origin: one subtraction, one matrix to fold it back
    into, and the pieces still line up with each other."""
    mesh = _mesh_of(FAR + np.zeros((1, 3)))
    mesh.edge_segments = np.array([[FAR, FAR + (REVEAL, 0, 0)]])
    mesh.points = np.array([FAR + (0, REVEAL, 0)])

    assert np.abs(mesh.local_edges).max() <= REVEAL
    assert np.abs(mesh.local_points).max() <= REVEAL
    far_end = mesh.edge_segments[0, 1]
    assert np.abs(far_end - (FAR + (REVEAL, 0, 0))).max() < 1e-7


def test_an_empty_mesh_costs_nothing():
    mesh = DisplayMesh()

    assert not mesh.far
    assert mesh.bounds() is None
    assert mesh.vertices.shape == (0, 3)


@pytest.mark.parametrize("stray", [
    g.make_point((1_000_000.0, 0.0, 0.0)),
    g.make_line((1_000_000.0, 0.0, 0.0), (1_000_100.0, 0.0, 0.0)),
], ids=["point", "edge"])
def test_a_stray_far_piece_leaves_the_faces_where_they_are(stray):
    """A surface model with a survey point or line far out: one origin
    for the lot, chosen from all of it, and the faces stay at home."""
    box = g.make_box((0, 0, 0), 10, 10, 10)
    mesh = tessellate(g.make_compound([box, stray]))

    xs = mesh.vertices[:, 0]
    assert abs(xs.min()) < 0.1 and abs(xs.max() - 10) < 0.1


def test_arrays_given_one_at_a_time_still_share_one_origin():
    mesh = _mesh_of([[0.0, 0.0, 0.0], [10.0, 10.0, 10.0]])
    mesh.points = np.array([[1_000_000.0, 0.0, 0.0]])

    assert mesh.far
    assert np.abs(mesh.vertices - [[0, 0, 0], [10, 10, 10]]).max() < 0.1


def test_far_data_centred_on_home_still_counts_as_far():
    """Its origin is (0, 0, 0), which is no reason for the next array
    to go and choose another."""
    mesh = _mesh_of([[-1_000_000.0, 0.0, 0.0], [1_000_000.0, 0.0, 0.0]])
    assert mesh.far and np.array_equal(mesh.origin, np.zeros(3))

    mesh.points = np.array([[1_000_000.0, 5.0, 0.0]])
    assert np.array_equal(mesh.origin, np.zeros(3))
    assert np.abs(mesh.vertices[:, 0]).max() == 1_000_000.0


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
    """Not bit for bit any more: the display keeps float32 offsets from
    the mesh's own origin, which out here holds a tenth of a nanometre.
    Far better than the micron anything is drawn or measured to, and
    half the memory of carrying doubles this far."""
    dm = mesh_to_display(_far_mesh_shape())
    assert dm.local.dtype == np.float32
    assert np.abs(dm.vertices - _far_mesh_shape().vertices).max() < 1e-7


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


def test_a_dashed_far_edge_is_dashed_where_the_mesh_keeps_it():
    """Linetypes rebuild the edge segments, so they are a second way in:
    the buffers take offsets, and the world's numbers here would put a
    far object twice as far out as it is."""
    mesh = tessellate(_far_box())
    segs = vp._dashed_edge_segments(mesh, (2.0, 1.0), 1.0)

    assert np.asarray(segs).dtype == np.float32
    assert np.abs(np.asarray(segs)).max() <= REVEAL * 1.001
    world = mesh.to_world(np.asarray(segs).reshape(-1, 3))
    assert np.abs(world - FAR).max() <= REVEAL * 1.001
