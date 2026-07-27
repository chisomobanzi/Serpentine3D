"""Rhino .3dm import: mesh fallbacks must not reach OCC.

Regression: a set-design .3dm crashed on open with

    Add(): incompatible function arguments ...
    Invoked with: <BRep_Builder>, <TopoDS_Compound>, <MeshShape>

_import_brep falls back to a face's render mesh whenever the NURBS
conversion or trim recovery fails, then sewed the whole list — so one
unconvertible face in a brep poisoned every other face with it.
"""

import numpy as np
import pytest

from serpentine3d.core import geometry
from serpentine3d.core.mesh import MeshShape
from serpentine3d.fileio import rhino


def _face(z: float = 0.0):
    """A real OCC planar face to stand in for a converted Rhino face."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Pnt, gp_Dir, gp_Pln, gp_Ax3
    pln = gp_Pln(gp_Ax3(gp_Pnt(0, 0, z), gp_Dir(0, 0, 1)))
    return BRepBuilderAPI_MakeFace(pln, 0., 10., 0., 10.).Face()


def _mesh(x: float = 0.0):
    return MeshShape(np.array([[x, 0, 0], [x + 1., 0, 0], [x, 1., 0]]),
                     np.array([[0, 1, 2]], np.uint32))


def test_mixed_faces_and_meshes_do_not_reach_the_sewer():
    """The reported crash: OCC's compound builder rejects a MeshShape."""
    out = rhino._assemble_faces([_face(0.), _mesh()])
    assert out, "everything was dropped"
    assert any(isinstance(s, MeshShape) for s in out), "lost the mesh"
    assert any(not isinstance(s, MeshShape) for s in out), "lost the face"


def test_several_mesh_fallbacks_come_back_as_one_object():
    """A brep is one Rhino object; N unconvertible faces shouldn't explode
    into N scene objects."""
    out = rhino._assemble_faces([_mesh(0.), _mesh(5.), _mesh(10.)])
    meshes = [s for s in out if isinstance(s, MeshShape)]
    assert len(meshes) == 1
    assert len(meshes[0].triangles) == 3
    assert len(meshes[0].vertices) == 9


def test_faces_alone_still_sew_into_one_solid():
    """The normal path must be untouched: a closed box sews to one shape."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.TopExp import TopExp_Explorer
    box = BRepPrimAPI_MakeBox(10., 10., 10.).Shape()
    exp = TopExp_Explorer(box, geometry.occ.FACE)
    faces = []
    while exp.More():
        faces.append(geometry.occ.to_face(exp.Current()))
        exp.Next()
    assert len(faces) == 6
    out = rhino._assemble_faces(faces)
    assert len(out) == 1
    assert geometry.volume(out[0]) == pytest.approx(1000.0, rel=1e-3)


def test_meshes_alone_need_no_occ_at_all():
    out = rhino._assemble_faces([_mesh()])
    assert len(out) == 1 and isinstance(out[0], MeshShape)


def test_empty_and_null_input():
    assert rhino._assemble_faces([]) == []
    assert rhino._assemble_faces([None]) == []
    assert rhino._assemble_faces(
        [MeshShape(np.zeros((0, 3)), np.zeros((0, 3), np.uint32))]) == []
