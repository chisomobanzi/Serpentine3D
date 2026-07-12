"""Kernel binding layer.

Serpentine talks to OpenCASCADE through this module only. It currently binds
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
from OCP.BRepBuilderAPI import (
    BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace,
    BRepBuilderAPI_MakeVertex, BRepBuilderAPI_MakePolygon,
    BRepBuilderAPI_Transform, BRepBuilderAPI_GTransform, BRepBuilderAPI_Copy,
    BRepBuilderAPI_Sewing, BRepBuilderAPI_MakeSolid,
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
from OCP.GeomAbs import GeomAbs_JoinType
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
from OCP.BRepTopAdaptor import BRepTopAdaptor_FClass2d
from OCP.TopAbs import TopAbs_State
from OCP.gp import gp_Pnt2d
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepGProp import BRepGProp
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
from OCP.GeomAbs import GeomAbs_Shape, GeomAbs_C2
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
    BRepBndLib.Add_s(shape, box)

def linear_properties(shape) -> GProp_GProps:
    props = GProp_GProps()
    BRepGProp.LinearProperties_s(shape, props)
    return props

def surface_properties(shape) -> GProp_GProps:
    props = GProp_GProps()
    BRepGProp.SurfaceProperties_s(shape, props)
    return props

def volume_properties(shape) -> GProp_GProps:
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, props)
    return props

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
