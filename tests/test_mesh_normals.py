"""The normals a mesh is shaded with.

Rhino stores a mesh unwelded — every face owning its own corners. Averaging
face normals per vertex index then averages exactly one face: one Rhino mesh
came out with 23,870 distinct normals across 23,369 triangles, so every
triangle got its own and the whole thing shaded flat. Only 3.9% of them
pointed within a degree of what Rhino asked for, and the worst pointed the
opposite way.

The file does carry Rhino's own answer, but rhino3dm hands normals over one
attribute at a time: 239 seconds for the 6.6 million of one survey object, on
top of the 313 its vertices already cost. So they are worked out from the
geometry — which means the working out has to keep the edges the modeller
made hard, or every box in the drawing turns into a pillow.
"""

import numpy as np
import pytest
import rhino3dm as r3

from serpentine3d.core.mesh import MeshShape, merge, mesh_to_display


def _unwelded_roof():
    """Two triangles meeting along a ridge, each owning its own corners —
    the shape of every mesh that comes out of a .3dm."""
    verts = np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0],      # flat half
                      [0., 0, 0], [1, 1, 0], [0, 1, 0]])     # its own copies
    tris = np.arange(6, dtype=np.uint32).reshape(2, 3)
    return verts, tris


def test_a_mesh_shades_with_the_normals_it_was_given():
    verts, tris = _unwelded_roof()
    # Deliberately not the face normals: this is what the modeller asked for.
    given = np.tile([0.6, 0.0, 0.8], (6, 1))
    dm = mesh_to_display(MeshShape(verts, tris, given))
    assert np.allclose(dm.normals, given, atol=1e-5)


def test_a_mesh_with_no_normals_still_works_them_out():
    """OBJ, STL and our own tessellation supply none, and must keep shading."""
    verts, tris = _unwelded_roof()
    dm = mesh_to_display(MeshShape(verts, tris))
    assert len(dm.normals) == len(verts)
    assert np.allclose(np.linalg.norm(dm.normals, axis=1), 1.0, atol=1e-4)


def test_normals_arrive_unit_length():
    """Rhino's are stored as unit vectors, but a mesh may be handed anything."""
    verts, tris = _unwelded_roof()
    given = np.tile([0.0, 0.0, 7.0], (6, 1))
    dm = mesh_to_display(MeshShape(verts, tris, given))
    assert np.allclose(np.linalg.norm(dm.normals, axis=1), 1.0, atol=1e-5)


def test_normals_turn_with_the_mesh():
    """A block placed in a drawing is transformed after it is read. Normals
    are directions, so they turn but do not travel."""
    verts, tris = _unwelded_roof()
    given = np.tile([1.0, 0.0, 0.0], (6, 1))
    quarter_turn = np.array([[0., -1, 0, 5],                 # about Z, moved
                             [1., 0, 0, 5],
                             [0., 0, 1, 5],
                             [0., 0, 0, 1]])
    moved = MeshShape(verts, tris, given).transformed(quarter_turn)
    assert np.allclose(moved.normals, np.tile([0., 1, 0], (6, 1)), atol=1e-6)


def test_a_mirrored_mesh_turns_its_normals_round():
    """Reflecting flips the winding, so the normals have to follow or the
    surface lights from inside."""
    verts, tris = _unwelded_roof()
    given = np.tile([0.0, 0.0, 1.0], (6, 1))
    mirror = np.diag([1.0, 1.0, -1.0])
    moved = MeshShape(verts, tris, given).transformed(mirror)
    assert np.allclose(moved.normals, np.tile([0., 0, 1], (6, 1)), atol=1e-6)


def test_merging_keeps_each_piece_its_own_normals():
    verts, tris = _unwelded_roof()
    up = np.tile([0.0, 0.0, 1.0], (6, 1))
    side = np.tile([1.0, 0.0, 0.0], (6, 1))
    both = merge([MeshShape(verts, tris, up), MeshShape(verts, tris, side)])
    assert len(both.normals) == 12
    assert np.allclose(both.normals[:6], up)
    assert np.allclose(both.normals[6:], side)


def test_merging_a_mesh_that_has_none_does_not_shift_the_others():
    """A piece with no normals still occupies its vertices, so the pieces
    that do have them must not slide onto the wrong rows."""
    verts, tris = _unwelded_roof()
    side = np.tile([1.0, 0.0, 0.0], (6, 1))
    both = merge([MeshShape(verts, tris), MeshShape(verts, tris, side)])
    assert len(both.normals) == 12
    assert np.allclose(both.normals[6:], side)


def test_a_copy_carries_them():
    verts, tris = _unwelded_roof()
    given = np.tile([0.0, 1.0, 0.0], (6, 1))
    assert np.allclose(MeshShape(verts, tris, given).copy().normals, given)


def test_normals_survive_the_trip_between_processes():
    """Meshes are read in spawned interpreters and pickled home."""
    import pickle
    verts, tris = _unwelded_roof()
    given = np.tile([0.0, 1.0, 0.0], (6, 1))
    there_and_back = pickle.loads(pickle.dumps(MeshShape(verts, tris, given)))
    assert np.allclose(there_and_back.normals, given)


# ------------------------------------------------------------- working it out


def _unwelded_box():
    """A unit cube whose faces share no vertex indices. Every one of its
    edges is one the modeller meant, and none of them may be smoothed."""
    faces = [((0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)),
             ((0, 0, 1), (0, 1, 1), (1, 1, 1), (1, 0, 1)),
             ((0, 0, 0), (0, 0, 1), (1, 0, 1), (1, 0, 0)),
             ((0, 1, 0), (1, 1, 0), (1, 1, 1), (0, 1, 1)),
             ((0, 0, 0), (0, 1, 0), (0, 1, 1), (0, 0, 1)),
             ((1, 0, 0), (1, 0, 1), (1, 1, 1), (1, 1, 0))]
    verts, tris = [], []
    for quad in faces:
        i = len(verts)
        verts.extend(quad)
        tris.append((i, i + 1, i + 2))
        tris.append((i, i + 2, i + 3))
    return np.array(verts, float), np.array(tris, np.uint32)


def _capped_tube(sides=24):
    """A tube with a lid, unwelded. The wall is meant to look round and the
    rim where it meets the lid is meant to stay sharp — the two demands meet
    at the same vertices, which is the whole difficulty."""
    ang = np.arange(sides) * 2 * np.pi / sides
    ring = np.column_stack([np.cos(ang), np.sin(ang), np.zeros(sides)])
    top = ring + [0, 0, 1.0]
    lid = np.array([0., 0, 1])
    verts, tris = [], []

    def add(*corners):
        i = len(verts)
        verts.extend(corners)
        tris.append((i, i + 1, i + 2))

    for i in range(sides):
        j = (i + 1) % sides
        add(ring[i], ring[j], top[j])
        add(ring[i], top[j], top[i])
    for i in range(sides):
        add(top[i], top[(i + 1) % sides], lid)
    wall = 6 * sides                             # vertices before the lid
    return np.array(verts, float), \
        np.array(tris, np.uint32), wall


def test_a_box_is_not_smoothed_into_a_pillow():
    """Welding the corners together and averaging would round every edge."""
    verts, tris = _unwelded_box()
    normals = np.asarray(mesh_to_display(MeshShape(verts, tris)).normals,
                         float)
    # Each face points straight down an axis, so every normal must too.
    assert np.abs(normals).max(axis=1).min() > 0.999, normals


def test_a_curved_wall_is_smoothed_across_corners_it_does_not_share():
    """The defect, in its own right: faces that touch must shade as one
    surface even though they hold separate copies of the same vertices.

    The tube has radius one about Z, so the answer is known — every wall
    normal points straight out from the axis. A facet normal instead points
    down the middle of its own quad, half a facet round from that."""
    verts, tris, wall = _capped_tube()
    normals = np.asarray(mesh_to_display(MeshShape(verts, tris)).normals,
                         float)
    radial = verts[:wall] * [1, 1, 0]
    radial /= np.linalg.norm(radial, axis=1, keepdims=True)
    off = np.degrees(np.arccos(
        np.clip(np.einsum("ij,ij->i", normals[:wall], radial), -1, 1)))
    assert off.max() < 2.0, f"wall normals off by up to {off.max():.1f} deg"


def test_a_sharp_rim_does_not_tilt_the_wall_below_it():
    """The wall's top corners are also the lid's. Averaging everything that
    meets there tips the wall's normals up towards the lid and draws a bright
    band round the top of every cylinder in the drawing."""
    verts, tris, wall = _capped_tube()
    normals = np.asarray(mesh_to_display(MeshShape(verts, tris)).normals,
                         float)
    assert np.abs(normals[:wall, 2]).max() < 0.02, \
        f"wall normals tilted by {np.abs(normals[:wall, 2]).max():.2f}"
    # And the lid stays flat rather than being dragged out to the side.
    assert normals[wall:, 2].min() > 0.999


def test_a_welded_box_does_not_lose_four_of_its_sides():
    """A cube whose faces do share vertex indices asks one vertex to hold
    three different normals at once. It cannot, so the display mesh gives the
    corner a copy per face — otherwise five faces end up shading with the
    sixth's normal, which lies in their own plane, and they go black."""
    from itertools import product
    verts = np.array(list(product([0., 1], [0., 1], [0., 1])))
    quads = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1),
             (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    tris = np.array([t for q in quads
                     for t in ((q[0], q[1], q[2]), (q[0], q[2], q[3]))],
                    np.uint32)

    dm = mesh_to_display(MeshShape(verts, tris))
    v = np.asarray(dm.vertices, float)
    n = np.asarray(dm.normals, float)
    face = np.cross(v[dm.triangles[:, 1]] - v[dm.triangles[:, 0]],
                    v[dm.triangles[:, 2]] - v[dm.triangles[:, 0]])
    face /= np.linalg.norm(face, axis=1, keepdims=True)
    for t, want in zip(np.asarray(dm.triangles), face):
        assert np.allclose(n[t], want, atol=1e-6), \
            f"corners {t} shade {n[t]} on a face pointing {want}"


def test_a_flat_sheet_shades_the_same_welded_or_not():
    """However the file happens to store it, it is the same surface."""
    verts = np.array([[0., 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]])
    tris = np.array([[0, 1, 2], [0, 2, 3]], np.uint32)
    welded = mesh_to_display(MeshShape(verts, tris)).normals
    loose = verts[tris.ravel()]
    unwelded = mesh_to_display(
        MeshShape(loose, np.arange(6, dtype=np.uint32).reshape(2, 3))).normals
    assert np.allclose(np.asarray(welded), [0, 0, 1], atol=1e-6)
    assert np.allclose(np.asarray(unwelded), [0, 0, 1], atol=1e-6)


def test_a_survey_mesh_is_shaded_without_a_pause():
    """This runs the first time an object is drawn, so it is felt as the
    window not appearing. The cave's largest object is six and a half times
    the mesh below, and Rhino's own answer for it takes 239 seconds to read
    out of the file one normal at a time."""
    import time
    side = 400                                   # ~1M unwelded vertices
    xs, ys = np.meshgrid(np.arange(side), np.arange(side))
    verts = np.column_stack([xs.ravel(), ys.ravel(),
                             np.zeros(side * side)]).astype(float)
    idx = np.arange(side * side).reshape(side, side)
    a, b = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel()
    c, d = idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
    tris = np.concatenate([np.column_stack([a, b, c]),
                           np.column_stack([a, c, d])])
    loose = verts[tris.ravel()]
    mesh = MeshShape(loose, np.arange(len(loose), dtype=np.uint32)
                     .reshape(-1, 3))

    start = time.perf_counter()
    dm = mesh_to_display(mesh)
    elapsed = time.perf_counter() - start

    assert np.allclose(np.asarray(dm.normals), [0, 0, 1], atol=1e-4)
    # Loose on purpose: this catches comparing every face at a point with
    # every other by searching, not the tenths a loaded machine adds.
    assert elapsed < 6.0, f"{len(loose):,} vertices took {elapsed:.1f}s"


def test_a_vertex_no_triangle_uses_is_not_left_as_rubbish():
    """Uninitialised memory in a normal buffer shades as noise."""
    verts = np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0], [9, 9, 9]])
    tris = np.array([[0, 1, 2]], np.uint32)
    normals = np.asarray(mesh_to_display(MeshShape(verts, tris)).normals,
                         float)
    assert np.isfinite(normals).all()
    assert np.abs(normals[3]).max() <= 1.0


# ------------------------------------------------------------------- reading


def _mesh_3dm(path):
    """A .3dm holding one mesh with the normals Rhino computed for it."""
    model = r3.File3dm()
    rm = r3.Mesh()
    for v in ((0, 0, 0), (1, 0, 0), (1, 1, 1), (0, 1, 1)):
        rm.Vertices.Add(float(v[0]), float(v[1]), float(v[2]))
    rm.Faces.AddFace(0, 1, 2, 3)
    rm.Normals.ComputeNormals()
    model.Objects.AddMesh(rm, r3.ObjectAttributes())
    assert model.Write(str(path), 8)
    return str(path)


def test_reading_a_mesh_does_not_pay_for_its_normals(tmp_path):
    """rhino3dm hands them over one attribute at a time — 36 microseconds
    each, 239 seconds for one survey object, and an import already spends
    five minutes reading that object's vertices. They are left to the
    display stage, which works them out from the triangles in a moment."""
    from serpentine3d.fileio import rhino

    model = r3.File3dm.Read(_mesh_3dm(tmp_path / "one.3dm"))
    shape = rhino._r3_mesh_to_shape(model.Objects[0].Geometry)

    assert len(shape.vertices) == 4
    assert shape.normals is None, "the importer read normals it can compute"


def test_a_rhino_mesh_is_not_shaded_flat(tmp_path):
    """The defect itself: a curved Rhino mesh whose faces do not share a
    vertex index used to end up with one normal per triangle."""
    from serpentine3d.fileio import rhino

    model = r3.File3dm()
    rm = r3.Mesh()
    # A strip bent around a cylinder, unwelded the way Rhino writes them.
    for i in range(8):
        angle = i * np.pi / 12
        for j in range(2):
            rm.Vertices.Add(float(np.cos(angle)), float(np.sin(angle)),
                            float(j))
    for i in range(7):
        rm.Faces.AddFace(2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1)
    rm.Normals.ComputeNormals()
    model.Objects.AddMesh(rm, r3.ObjectAttributes())
    path = str(tmp_path / "curved.3dm")
    assert model.Write(path, 8)

    geo = r3.File3dm.Read(path).Objects[0].Geometry
    dm = mesh_to_display(rhino._r3_mesh_to_shape(geo))
    normals = np.asarray(dm.normals, float)

    # Along the length of the strip nothing bends, so the two ends of every
    # rung share a direction. Flat shading would give each triangle its own.
    distinct = len(np.unique(np.round(normals, 4), axis=0))
    assert distinct <= len(dm.triangles), \
        f"{distinct} normals for {len(dm.triangles)} triangles — shaded flat"
