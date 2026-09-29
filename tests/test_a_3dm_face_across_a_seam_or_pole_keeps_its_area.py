"""A .3dm face that runs round a seam or to a pole keeps its area (#34).

Reported: some Rhino files arrive with materially less surface area than
they hold, silently. v4_TreeFrog, one closed 83-face solid, came in as an
open surface at 76% of its area, with the eye domes gone.

No face was dropped. Three things were wrong, stacked:

  A pole. Where a surface pinches to a point, the loop runs along the
  pinched side with a trim that has no 3D edge at all, and the file says
  so with an edge index of -1. The loop builder took that for a trim it
  could not follow and gave the whole face up to the guessing paths, which
  built the untrimmed surface or the wrong side of it.

  A seam. On a surface closed round like a tube, the loop walks the seam
  edge twice, once on each side. Rebuilt from 3D edges alone that is not a
  boundary at all, and the frog's body skin came out at 2.5% of its size.
  The face is now built from its trims in the surface's own (u, v), where
  each side of the seam is a different place, settled by continuity with
  the trims either side; poles become edges of no length there.

  A solid. A shell that is watertight came back open anyway, because its
  closed flag, which sewing does not always set, was trusted over asking.

The files that showed it are openNURBS samples that cannot be shipped
here, so the faces below are made the same way from a drilled sphere: a
hole along Y leaves both poles and the seam, and a hole along X crosses
the seam as well, which is the frog's body skin.
"""

from __future__ import annotations

import math

import pytest
import rhino3dm as r3
from OCP.BRep import BRep_Tool
from OCP.BRepBuilderAPI import BRepBuilderAPI_NurbsConvert
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
from OCP.TopAbs import TopAbs_FORWARD, TopAbs_REVERSED, TopAbs_WIRE
from OCP.TopExp import TopExp, TopExp_Explorer
from OCP.TopoDS import TopoDS

from serpentine3d.core import geometry as g
from serpentine3d.fileio import rhino as R

RADIUS = 10.0


# --- a face described the way rhino3dm describes one ------------------------

class _P:
    def __init__(self, p):
        self.X, self.Y, self.Z = p.X(), p.Y(), p.Z()


class _Vertex:
    def __init__(self, v):
        self.Location = _P(BRep_Tool.Pnt_s(v))


class _Trim:
    def __init__(self, edge_index, reversed_, start, end):
        self.EdgeIndex = edge_index
        self.IsReversed = reversed_
        self.StartVertexIndex = start
        self.EndVertexIndex = end


class _Loop:
    def __init__(self, outer, trims):
        self.LoopType = "BrepLoopType.Outer" if outer else "BrepLoopType.Inner"
        self.Trims = trims
        self.TrimCount = len(trims)


class _Face:
    def __init__(self, loops):
        self.Loops = loops


def _as_rhino(face):
    """(rface, table, vertices) for an OCC face: trims in loop order, a pole
    as an edge index of -1, a seam as one edge index walked twice."""
    face = TopoDS.Face_s(face.Oriented(TopAbs_FORWARD))
    edges, verts = [], []

    def index(shape, pool):
        for i, s in enumerate(pool):
            if s.IsSame(shape):
                return i
        pool.append(shape)
        return len(pool) - 1

    outer = BRepTools.OuterWire_s(face)
    loops = []
    exp = TopExp_Explorer(face, TopAbs_WIRE)
    while exp.More():
        wire = TopoDS.Wire_s(exp.Current())
        trims = []
        we = BRepTools_WireExplorer(wire, face)
        while we.More():
            e = we.Current()
            start = index(TopExp.FirstVertex_s(e, True), verts)
            end = index(TopExp.LastVertex_s(e, True), verts)
            if BRep_Tool.Degenerated_s(e):
                trims.append(_Trim(-1, False, start, start))
            else:
                ei = index(TopoDS.Edge_s(e.Oriented(TopAbs_FORWARD)), edges)
                trims.append(_Trim(ei, e.Orientation() == TopAbs_REVERSED, start, end))
            we.Next()
        loops.append(_Loop(wire.IsSame(outer), trims))
        exp.Next()
    table = {i: e for i, e in enumerate(edges)}
    return _Face(loops), table, [_Vertex(TopoDS.Vertex_s(v)) for v in verts]


def _drilled_sphere_face(axis, periodic):
    """The sphere's face with a hole of radius 3 through it along `axis`,
    as a NURBS face; closed but not periodic, as Rhino writes one, unless
    asked otherwise. Returns (face, surface, true area)."""
    hole = g.make_cylinder(tuple(-15.0 * a for a in axis), 3.0, 30.0, axis=axis)
    cut = g.boolean_difference(g.make_sphere((0, 0, 0), RADIUS), hole)
    sphere = next(f for f in g.faces_of(cut)
                  if "Spher" in type(BRep_Tool.Surface_s(f)).__name__)
    area = g.surface_area(sphere)
    face = g.faces_of(BRepBuilderAPI_NurbsConvert(sphere, True).Shape())[0]
    surf = BRep_Tool.Surface_s(face)
    if not periodic:
        surf.SetUNotPeriodic()          # the face is ours alone to change
    return face, surf, area


def _pattern(rface):
    out = []
    for lp in rface.Loops:
        seen, kinds = set(), []
        for t in lp.Trims:
            kinds.append("pole" if t.EdgeIndex == -1 else
                         "seam" if t.EdgeIndex in seen or
                         sum(1 for u in lp.Trims if u.EdgeIndex == t.EdgeIndex) > 1
                         else "edge")
            seen.add(t.EdgeIndex)
        out.append(kinds)
    return out


# --- the fixtures really have the shape the reported files had --------------

def test_a_hole_along_y_leaves_the_poles_and_the_seam():
    face, _surf, _area = _drilled_sphere_face((0, 1, 0), periodic=False)
    rface, _t, _v = _as_rhino(face)
    outer = _pattern(rface)[0]
    assert outer.count("pole") == 2 and outer.count("seam") == 2
    assert len(rface.Loops) == 3, "two round holes"


def test_a_hole_along_x_crosses_the_seam_too():
    face, _surf, _area = _drilled_sphere_face((1, 0, 0), periodic=False)
    rface, _t, _v = _as_rhino(face)
    outer = _pattern(rface)[0]
    assert outer.count("pole") == 2
    assert outer.count("seam") == 4, "the hole cuts the seam into two, each walked twice"
    assert outer.count("edge") == 2


# --- the face comes back whole --------------------------------------------

# Closed but not periodic, as the importer builds every surface: of the
# 7,349 brep faces in the openNURBS samples, 968 are periodic in Rhino and
# none once imported, so a periodic surface never reaches this builder.
CASES = [((0, 1, 0), False), ((1, 0, 0), False)]
IDS = ["poles-and-seam", "hole-across-the-seam"]


@pytest.mark.parametrize("axis,periodic", CASES, ids=IDS)
def test_a_face_round_a_seam_and_through_its_poles_keeps_its_area(axis, periodic):
    face, surf, area = _drilled_sphere_face(axis, periodic)
    rface, table, verts = _as_rhino(face)

    built = R._face_from_loops(rface, surf, table, verts)

    assert built is not None, "the file's own loops describe this face"
    assert BRepCheck_Analyzer(built).IsValid()
    assert g.surface_area(built) == pytest.approx(area, rel=2e-3)


def test_the_holes_are_holes_not_the_face():
    """The wrong side of a round hole is a small disc: the size a face
    comes to when the builder keeps the wrong side of its boundary."""
    face, surf, area = _drilled_sphere_face((0, 1, 0), periodic=False)
    rface, table, verts = _as_rhino(face)

    built = R._face_from_loops(rface, surf, table, verts)

    disc = 2 * math.pi * RADIUS * (RADIUS - math.sqrt(RADIUS ** 2 - 9.0))
    assert g.surface_area(built) > 4 * math.pi * RADIUS ** 2 - 3 * disc


# --- and a closed brep arrives as a solid ---------------------------------

def test_a_rhino_sphere_arrives_as_a_solid_of_the_right_size():
    """rhino3dm's own sphere: one face, its loop pole, seam, pole, seam."""
    brep = r3.Brep.CreateFromSphere(r3.Sphere(r3.Point3d(0, 0, 0), 2.0))
    loop = brep.Faces[0].Loops[0]
    assert [loop.Trims[i].EdgeIndex for i in range(loop.TrimCount)].count(-1) == 2

    shapes = R._import_brep(brep)

    assert len(shapes) == 1
    assert g.shape_kind(shapes[0]) == "solid"
    assert g.volume(shapes[0]) == pytest.approx(4 / 3 * math.pi * 8, rel=2e-3)
    assert g.surface_area(shapes[0]) == pytest.approx(4 * math.pi * 4, rel=2e-3)


def test_a_watertight_shell_is_a_solid_whatever_its_flag_says():
    """Sewing does not always set a shell's closed flag; the frog came back
    open for that reason alone once its faces were right."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
    sew = BRepBuilderAPI_Sewing(1e-6)
    for f in g.faces_of(g.make_box((0, 0, 0), 10, 20, 30)):
        sew.Add(f)
    sew.Perform()
    shell = g.occ.to_shell(sew.SewedShape())
    shell.Closed(False)                          # as sewing sometimes leaves it

    out = R._shell_to_solid(shell)

    assert g.shape_kind(out) == "solid"
    assert g.volume(out) == pytest.approx(6000.0, rel=1e-6)


# --- what worked keeps working --------------------------------------------

def test_a_face_with_neither_keeps_the_path_it_had():
    """A plain trimmed face goes the way it always went."""
    face = next(f for f in g.faces_of(g.boolean_difference(
        g.make_box((0, 0, 0), 20, 20, 1), g.make_cylinder((10, 10, -1), 3.0, 3.0)))
        if g.face_normal(f)[2] > 0.9)
    rface, table, verts = _as_rhino(face)
    surf = BRep_Tool.Surface_s(face)

    built = R._face_from_loops(rface, surf, table, verts)

    assert built is not None
    assert g.surface_area(built) == pytest.approx(400 - math.pi * 9, rel=1e-6)
