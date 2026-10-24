"""Kernel binding layer.

Serpentine3D talks to OpenCASCADE through this module only. It currently binds
via OCP (pip-installable pybind11 wheels); pythonocc-core uses the same class
names under OCC.Core.*, so porting means editing this file, not the app.
"""

from OCP.gp import (
    gp_Pnt, gp_Vec, gp_Dir, gp_Ax1, gp_Ax2, gp_Ax3, gp_Pln, gp_Trsf,
    gp_GTrsf, gp_Circ, gp_Elips, gp_XYZ, gp_Quaternion, gp_Mat,
)
from OCP.TopoDS import (
    TopoDS, TopoDS_Shape, TopoDS_Edge, TopoDS_Wire, TopoDS_Face,
    TopoDS_Shell, TopoDS_Solid, TopoDS_Compound, TopoDS_Vertex,
    TopoDS_Builder, TopoDS_Iterator,
)
from OCP.TopAbs import TopAbs_ShapeEnum, TopAbs_Orientation
from OCP.TopExp import TopExp_Explorer, TopExp
from OCP.TopTools import TopTools_IndexedMapOfShape
from OCP.BRep import BRep_Tool, BRep_Builder
from OCP.BRepLib import BRepLib, BRepLib_FindSurface
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeVertex, BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_Transform, BRepBuilderAPI_GTransform, BRepBuilderAPI_Copy,
    BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid, BRepBuilderAPI_NurbsConvert,
)
from OCP.BRepPrimAPI import (
    BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol, BRepPrimAPI_MakeBox,
    BRepPrimAPI_MakeSphere, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeCone,
    BRepPrimAPI_MakeTorus,
)
from OCP.BRepAlgoAPI import (
    BRepAlgoAPI_Fuse, BRepAlgoAPI_Cut, BRepAlgoAPI_Common,
    BRepAlgoAPI_Splitter,
)
from OCP.TopTools import TopTools_ListOfShape, TopTools_HSequenceOfShape
from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
from OCP.GeomConvert import GeomConvert
from OCP.BRepOffsetAPI import (
    BRepOffsetAPI_ThruSections, BRepOffsetAPI_MakePipe,
    BRepOffsetAPI_MakePipeShell, BRepOffsetAPI_MakeOffset,
)
from OCP.ChFi2d import ChFi2d_FilletAPI
from OCP.GeomAbs import GeomAbs_JoinType, GeomAbs_CurveType
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Curve2d, BRepAdaptor_Surface
from OCP.BRepTopAdaptor import BRepTopAdaptor_FClass2d
from OCP.TopAbs import TopAbs_State
from OCP.gp import gp_Pnt2d
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepGProp import (
    BRepGProp, BRepGProp_Domain, BRepGProp_Face, BRepGProp_Sinert, BRepGProp_Vinert,
)
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepTools import BRepTools
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.Bnd import Bnd_Box
from OCP.GProp import GProp_GProps
from OCP.GC import GC_MakeArcOfCircle, GC_MakeSegment, GC_MakeCircle
from OCP.GeomAPI import GeomAPI_Interpolate, GeomAPI_PointsToBSpline
from OCP.Geom import (
    Geom_BSplineCurve, Geom_Circle, Geom_TrimmedCurve, Geom_Plane,
    Geom_Ellipse, Geom_Line,
)
from OCP.GeomAbs import GeomAbs_Shape, GeomAbs_C2, GeomAbs_SurfaceType
from OCP.GCPnts import GCPnts_TangentialDeflection, GCPnts_UniformDeflection
from OCP.TColgp import TColgp_Array1OfPnt, TColgp_HArray1OfPnt
from OCP.TColStd import TColStd_Array1OfReal, TColStd_Array1OfInteger
from OCP.TopLoc import TopLoc_Location
from OCP.Poly import Poly_Triangulation
from OCP.BinTools import BinTools
from OCP.STEPControl import (
    STEPControl_Reader, STEPControl_Writer, STEPControl_StepModelType,
)
from OCP.IFSelect import IFSelect_ReturnStatus
from OCP.Interface import Interface_Static
from OCP.ShapeFix import ShapeFix_Shape
from OCP.ShapeUpgrade import ShapeUpgrade_ShapeDivideContinuity

BACKEND = "OCP"

# --- downcasts -------------------------------------------------------------

def to_edge(shape) -> TopoDS_Edge:
    return TopoDS.Edge_s(shape)

def to_wire(shape) -> TopoDS_Wire:
    return TopoDS.Wire_s(shape)

def to_face(shape) -> TopoDS_Face:
    return TopoDS.Face_s(shape)

def to_shell(shape) -> TopoDS_Shell:
    return TopoDS.Shell_s(shape)

def to_solid(shape) -> TopoDS_Solid:
    return TopoDS.Solid_s(shape)

def to_vertex(shape) -> TopoDS_Vertex:
    return TopoDS.Vertex_s(shape)

def to_compound(shape) -> TopoDS_Compound:
    return TopoDS.Compound_s(shape)

# --- static wrappers (OCP uses Method_s naming) -----------------------------

def triangulation(face, loc: TopLoc_Location):
    return BRep_Tool.Triangulation_s(face, loc)

def edge_adaptor(edge) -> BRepAdaptor_Curve:
    """Parametric access to an edge's curve (Value/FirstParameter/LastParameter)."""
    return BRepAdaptor_Curve(edge)

def point_of_vertex(vertex) -> gp_Pnt:
    return BRep_Tool.Pnt_s(vertex)

def bbox_add(shape, box: Bnd_Box):
    # Triangulation carries its meshing deflection as an isotropic gap, so a
    # shape's reported bounds used to grow after it had first been drawn.
    # Geometry bounds must stay tied to the B-rep and independent of display.
    # Include the B-rep's own modelling tolerance so mathematically exact
    # extents do not land a fraction below their boundary through conversion.
    BRepBndLib.AddOptimal_s(shape, box, False, True)

def ensure_curves3d(shape):
    """Materialize pcurve-only edges before a native consumer reads them.

    HLR can leave projected B-splines without a 3D curve. OCCT's linear
    properties then dereference a null curve instead of raising an error.
    Build from the existing pcurves, preserving their projected geometry.
    Degenerate edges at sphere poles legitimately have no curve to build.
    """
    if BRepLib.BuildCurves3d_s(shape):
        return
    explorer = TopExp_Explorer(shape, EDGE)
    while explorer.More():
        edge = to_edge(explorer.Current())
        if (not BRep_Tool.Degenerated_s(edge)
                and BRep_Tool.Curve_s(edge, 0., 0.) is None):
            raise ValueError("A curve has no 3D geometry and could not be reconstructed")
        explorer.Next()


def linear_properties(shape) -> GProp_GProps:
    # Also protect projected curves saved by older versions, which bypass
    # the repaired HLR output when their drawing is reopened.
    ensure_curves3d(shape)
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(shape, props)
    return props

# --- area, volume and centre --------------------------------------------------
#
# OpenCascade's default integration lays one Gauss rule across a whole face in
# each direction, never split at a knot and never more than 61 points. Its
# volume integral takes the count from the face's edges and the surface's V
# direction, never U, so a bow limb from Rhino got 8 points across 16 spans
# and read 0.8% light (#104). The adaptive integration places its points span
# by span instead. Each face gets the default only where every curve it
# integrates along is one smooth piece, and the adaptive integration
# everywhere else.
#
# The adaptive integration refines along a face's edges, but takes its points
# across each span from its tolerance alone (6 for a cubic at 1e-6, 8 at 1e-8)
# and never refines there. So its tolerance is set by what the face is:
#
#                                      volume   area
#   up to _FEW_SPANS spans              1e-6    1e-8
#   up to _MANY_SPANS                   1e-6    1e-6
#   more                                1e-4    1e-4
#   a sweep made NURBS, up to _MANY     1e-8    as its spans
#
# A volume's integrand is a polynomial on a polynomial surface, which 6
# points take exactly; a sweep made NURBS is rational, in 120-degree arcs,
# and read a vase 3e-6 out at 1e-6. An area's integrand is a square root,
# which 6 points left 4e-4 out on a two-span strip; on a face of more spans
# each span is smaller and 6 do, while 1e-8 sent the integration bisecting
# a bottle's 36-span face for six seconds, chasing an error across the
# spans it cannot reduce. Past _MANY_SPANS its time grows with every span
# it crosses, and a mug's body of 204 took four seconds at 1e-6. (At 1e-3 or
# looser it takes each span once with no error estimate, twice as fast, but
# read a head's area 4e-4 out.)

_FEW_SPANS, _MANY_SPANS = 8, 64


def _faces(shape) -> list:
    out = []
    exp = TopExp_Explorer(shape, FACE)
    while exp.More():
        out.append(TopoDS.Face_s(exp.Current()))
        exp.Next()
    return out


def smooth_pieces(face) -> list:
    """`face` cut where its surface has a crease, as a list of faces.

    A surface built as a chain of patches meeting at creases (knots at full
    multiplicity, as Rhino writes a revolved profile) is not one smooth
    piece, and integrated whole a mug's body read 20% short, a synthetic one
    98% (#34). Cut at the creases, each piece is smooth.

    A NURBS face closed both ways stays whole, because the splitter cuts
    those wrong: a ring scaled to an oval read half its volume (#104). The
    adaptive integration copes with their creases whole, to a few parts in
    a million. A face with no crease is its own only piece and costs nothing.
    """
    surf = BRep_Tool.Surface_s(face)
    if surf is None or surf.Continuity() != GeomAbs_Shape.GeomAbs_C0:
        return [face]
    nurbs = BRepAdaptor_Surface(face).GetType() in (
        GeomAbs_SurfaceType.GeomAbs_BSplineSurface,
        GeomAbs_SurfaceType.GeomAbs_BezierSurface)
    if nurbs and surf.IsUClosed() and surf.IsVClosed():
        return [face]
    try:
        split = ShapeUpgrade_ShapeDivideContinuity(face)
        split.SetBoundaryCriterion(GeomAbs_Shape.GeomAbs_C1)
        split.SetPCurveCriterion(GeomAbs_Shape.GeomAbs_C1)
        split.SetSurfaceSegmentMode(True)
        split.Perform()
        out = split.Result()
    except Exception:                                       # noqa: BLE001
        return [face]
    if out is None or out.IsNull():
        return [face]
    return _faces(out) or [face]


_CONICS = (GeomAbs_CurveType.GeomAbs_Line, GeomAbs_CurveType.GeomAbs_Circle,
           GeomAbs_CurveType.GeomAbs_Ellipse, GeomAbs_CurveType.GeomAbs_Hyperbola,
           GeomAbs_CurveType.GeomAbs_Parabola)


def _one_piece(curve) -> bool:
    """Whether an adaptor curve is a line, a conic or a single span: one
    smooth piece, which one Gauss rule integrates."""
    kind = curve.GetType()
    if kind in _CONICS or kind == GeomAbs_CurveType.GeomAbs_BezierCurve:
        return True
    return (kind == GeomAbs_CurveType.GeomAbs_BSplineCurve
            and curve.BSpline().NbKnots() == 2)


def _edges_in_one_piece(face) -> bool:
    exp = TopExp_Explorer(face, EDGE)
    while exp.More():
        if not _one_piece(BRepAdaptor_Curve2d(TopoDS.Edge_s(exp.Current()), face)):
            return False
        exp.Next()
    return True


def _integration(face, volume: bool):
    """How to integrate `face`: as (face, tolerance), the face perhaps made
    NURBS, the tolerance None for the default integration.

    The default stays where every curve it integrates along is one smooth
    piece: an elementary surface, a single span, or a sweep of one, bounded
    by edges that are. There it is as exact as it ever was. A sweep of a
    longer curve is made NURBS first: its spans are the curve's, and only a
    NURBS surface shows them to the adaptive integration, which read an
    extrusion kept as a sweep 1% to 12% out. Offsets and the rest have no
    spans to show it, and keep the default as before. The tolerance is the
    table's above.
    """
    T = GeomAbs_SurfaceType
    s = BRepAdaptor_Surface(face)
    kind = s.GetType()
    swept = False
    if kind in (T.GeomAbs_SurfaceOfExtrusion, T.GeomAbs_SurfaceOfRevolution):
        whole = _one_piece(s.BasisCurve())
        if not whole:
            try:
                face = TopoDS.Face_s(BRepBuilderAPI_NurbsConvert(face, True).Shape())
            except Exception:                               # noqa: BLE001
                return face, None
            s, swept = BRepAdaptor_Surface(face), True
    elif kind in (T.GeomAbs_Plane, T.GeomAbs_Cylinder, T.GeomAbs_Cone,
                  T.GeomAbs_Sphere, T.GeomAbs_Torus, T.GeomAbs_BezierSurface):
        whole = True
    elif kind == T.GeomAbs_BSplineSurface:
        whole = s.BSpline().NbUKnots() == 2 and s.BSpline().NbVKnots() == 2
    else:
        return face, None
    if whole and _edges_in_one_piece(face):
        return face, None
    spans = 1
    if s.GetType() == T.GeomAbs_BSplineSurface:
        spans = (s.BSpline().NbUKnots() - 1) * (s.BSpline().NbVKnots() - 1)
    if spans > _MANY_SPANS:
        return face, 1e-4
    if volume:
        return face, 1e-8 if swept else 1e-6
    return face, 1e-8 if spans <= _FEW_SPANS else 1e-6


def _middle(shape) -> gp_Pnt:
    """The mean of `shape`'s vertices, as BRepGProp's roughBaryCenter."""
    xyz, n = gp_XYZ(0, 0, 0), 0
    exp = TopExp_Explorer(shape, VERTEX)
    while exp.More():
        xyz.Add(BRep_Tool.Pnt_s(TopoDS.Vertex_s(exp.Current())).XYZ())
        n += 1
        exp.Next()
    return gp_Pnt(xyz.Divided(n)) if n else gp_Pnt(0, 0, 0)


def _integrated(shape, inertia) -> GProp_GProps:
    """`shape`'s area or volume properties, face by face, summed the way
    BRepGProp sums them: each face about the middle of the shape's
    vertices, into a system placed at the shape's origin."""
    volume = inertia is BRepGProp_Vinert
    origin = gp_Pnt(0, 0, 0).Transformed(shape.Location().Transformation())
    props = GProp_GProps(origin)
    faces = _faces(shape)
    if any(BRep_Tool.Surface_s(f) is None for f in faces):
        # a face with only a mesh, which BRepGProp measures from the mesh
        whole = BRepGProp.VolumeProperties_s if volume else BRepGProp.SurfaceProperties_s
        whole(shape, props)
        return props
    at = _middle(shape)
    for face in faces:
        if face.Orientation() not in (TopAbs_Orientation.TopAbs_FORWARD,
                                      TopAbs_Orientation.TopAbs_REVERSED):
            continue
        for piece in smooth_pieces(face):
            piece, eps = _integration(piece, volume)
            region = [BRepGProp_Face(piece)]
            if piece.NbChildren():
                region.append(BRepGProp_Domain(piece))
            if eps is None:
                props.Add(inertia(*region, at))
            else:
                props.Add(inertia(*region, at, eps))
    return props


def surface_properties(shape) -> GProp_GProps:
    return _integrated(shape, BRepGProp_Sinert)


def volume_properties(shape) -> GProp_GProps:
    return _integrated(shape, BRepGProp_Vinert)

def brep_write(shape, path: str):
    BinTools.Write_s(shape, path)

def brep_read(path: str) -> TopoDS_Shape:
    shape = TopoDS_Shape()
    BinTools.Read_s(shape, path)
    return shape

def map_shapes(shape, kind) -> TopTools_IndexedMapOfShape:
    m = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape, kind, m)
    return m

# shape-type enum shortcuts
VERTEX = TopAbs_ShapeEnum.TopAbs_VERTEX
EDGE = TopAbs_ShapeEnum.TopAbs_EDGE
WIRE = TopAbs_ShapeEnum.TopAbs_WIRE
FACE = TopAbs_ShapeEnum.TopAbs_FACE
SHELL = TopAbs_ShapeEnum.TopAbs_SHELL
SOLID = TopAbs_ShapeEnum.TopAbs_SOLID
COMPSOLID = TopAbs_ShapeEnum.TopAbs_COMPSOLID
COMPOUND = TopAbs_ShapeEnum.TopAbs_COMPOUND
