"""Shape tessellation: TopoDS_Shape -> numpy arrays for the GL viewport."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field

import numpy as np

from ..utils.math3d import offsets_from, origin_between
from . import occ, geometry
from .occ import (
    BRepMesh_IncrementalMesh, TopExp_Explorer, TopLoc_Location,
    GCPnts_TangentialDeflection, TopAbs_Orientation,
)
from .spatial import build_index

_UNINDEXED = object()

_LOCALS = ("local", "local_edges", "local_isos", "local_points")


def _extent(*arrays) -> tuple:
    """(lo, hi) over every point in `arrays`, without joining them."""
    lows, highs = [], []
    for a in arrays:
        if len(a):
            flat = a.reshape(-1, 3)
            lows.append(np.asarray(flat.min(axis=0), np.float64))
            highs.append(np.asarray(flat.max(axis=0), np.float64))
    if not lows:
        return None, None
    return np.min(lows, axis=0), np.max(highs, axis=0)

# Serial numbers for display meshes; see DisplayMesh.uid. next() on a count
# is a single bytecode, so the tessellation workers can share one.
_uids = itertools.count(1)


@dataclass
class DisplayMesh:
    """GPU-ready geometry for one scene object.

    Coordinates are kept as float32 offsets from `origin`, the point this
    mesh sits at. Four bytes hold a offset of a few hundred units to a
    fraction of a micron, so a survey mesh is drawn as exactly as one at
    home and costs no more memory than it: a million vertices are 12MB
    either way, where keeping doubles for the far one made it 24.

    The arrays a caller sees, `vertices` and the rest, are the world's own
    coordinates, worked out on the way out. Anything asking for them by
    the frame or by the click asks `local` and `origin` instead and does
    its arithmetic there, where the numbers are small: the viewport
    uploads offsets and folds the origin into the matrix, and a pick
    moves the ray rather than the mesh.
    """
    origin: np.ndarray = field(
        default_factory=lambda: np.zeros(3), compare=False)
    local: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 3), np.float32))
    normals: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 3), np.float32))
    triangles: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 3), np.uint32))
    # edge polylines flattened to GL_LINES segment pairs: (K, 2, 3)
    local_edges: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 2, 3), np.float32))
    # isoparametric curves on curved faces (display only, not pickable)
    local_isos: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 2, 3), np.float32))
    # signed mean curvature per vertex (for curvature analysis display)
    curvature: np.ndarray = field(
        default_factory=lambda: np.zeros(0, np.float32))
    # sub-object topology maps: segment -> edge index, triangle -> face index
    edge_of_segment: np.ndarray = field(
        default_factory=lambda: np.zeros(0, np.int32))
    face_of_triangle: np.ndarray = field(
        default_factory=lambda: np.zeros(0, np.int32))
    # free-standing point objects (vertex shapes): (N, 3)
    local_points: np.ndarray = field(
        default_factory=lambda: np.zeros((0, 3), np.float32))
    # A point cloud (core/pointcloud.py) shows as vertices with no faces:
    # the same bounds, culling and box-picking as everything else, and a
    # points draw of its own. cloud_colors is (N, 3) uint8 or None;
    # cloud_levels the cumulative point counts per LOD level, or None.
    is_cloud: bool = False
    cloud_colors: object = field(default=None, repr=False, compare=False)
    cloud_levels: tuple | None = field(default=None, repr=False,
                                       compare=False)

    has_curvature: bool = False
    # A serial number for this mesh, for caches that have to answer "is this
    # still the mesh I was given?" after the mesh in question may be gone.
    # id() cannot answer that: it is an address, and a freed one is handed
    # straight back out — a new mesh lands on a dead one's address 49 times
    # out of 50 — so a cache keyed on it goes on serving what it built from
    # geometry that no longer exists. Never reused, and out of the equality
    # comparison, since two meshes of the same geometry are still equal.
    uid: int = field(default_factory=lambda: next(_uids),
                     repr=False, compare=False)
    _far: bool = field(default=False, repr=False, compare=False)
    _bounds: tuple | None = field(default=None, repr=False, compare=False)
    # spatial indexes for picking, built on first click and kept: None means
    # "not looked at yet", _UNINDEXED means "looked at, not worth indexing"
    _tri_index: object = field(default=None, repr=False, compare=False)
    _seg_index: object = field(default=None, repr=False, compare=False)

    # -- the world's coordinates, and this mesh's own ---------------------

    def to_world(self, local) -> np.ndarray:
        """Offsets from this mesh's origin, as world coordinates."""
        if not self.far:
            return np.asarray(local)
        return np.asarray(local, np.float64) + self.origin

    def place(self, *, vertices=None, edge_segments=None, iso_segments=None,
              points=None) -> None:
        """Store world coordinates, deciding once where the mesh sits.

        The origin is chosen from everything the mesh holds, what it is
        given here and what it was given before, so faces at home and a
        stray point far out share one origin rather than the faces being
        measured from where the point is.
        """
        given = {name: np.asarray(pts) for name, pts in (
            ("local", vertices), ("local_edges", edge_segments),
            ("local_isos", iso_segments), ("local_points", points))
            if pts is not None}
        if not self.far:
            held = {name: getattr(self, name) for name in _LOCALS
                    if name not in given and len(getattr(self, name))}
            found = origin_between(*_extent(
                *given.values(), *held.values()))
            if found is not None:
                self.origin = found
                self._far = True
                given.update(held)
                self._bounds = self._tri_index = self._seg_index = None
        for name, pts in given.items():
            setattr(self, name, self._offsets(pts))

    def _offsets(self, pts) -> np.ndarray:
        if not len(pts) or not self.far:
            return np.ascontiguousarray(pts, np.float32)
        flat = offsets_from(pts.reshape(-1, 3), self.origin)
        return flat.reshape(pts.shape)

    @property
    def far(self) -> bool:
        """Whether this mesh keeps its coordinates relative to an origin."""
        return self._far

    @property
    def vertices(self) -> np.ndarray:
        return self.to_world(self.local)

    @vertices.setter
    def vertices(self, points):
        self.place(vertices=points)

    @property
    def edge_segments(self) -> np.ndarray:
        return self.to_world(self.local_edges)

    @edge_segments.setter
    def edge_segments(self, points):
        self.place(edge_segments=points)

    @property
    def iso_segments(self) -> np.ndarray:
        return self.to_world(self.local_isos)

    @iso_segments.setter
    def iso_segments(self, points):
        self.place(iso_segments=points)

    @property
    def points(self) -> np.ndarray:
        return self.to_world(self.local_points)

    @points.setter
    def points(self, points):
        self.place(points=points)

    @property
    def has_faces(self) -> bool:
        return len(self.triangles) > 0

    def triangle_index(self):
        """Spatial index over the triangles, or None to test them all.

        Built lazily: a mesh only pays for this if it is ever picked in,
        and most objects in a drawing never are. In the mesh's own
        coordinates, like everything else about picking: a ray is three
        numbers and a mesh is millions, so the ray is the one that moves.
        """
        if self._tri_index is None:
            self._tri_index = (build_index(self.local[self.triangles])
                               or _UNINDEXED)
        return None if self._tri_index is _UNINDEXED else self._tri_index

    def segment_index(self):
        """Spatial index over the edge segments, in the mesh's own
        coordinates; see triangle_index."""
        if self._seg_index is None:
            self._seg_index = build_index(self.local_edges) or _UNINDEXED
        return None if self._seg_index is _UNINDEXED else self._seg_index

    def bounds(self) -> tuple | None:
        """Cached (min_xyz, max_xyz) over vertices, edge and point data.

        Reduced source by source rather than over one concatenation of them
        all: concatenating copies every vertex in the mesh to read six
        numbers off it, and on a scanned survey the vertices are the file.
        Read off the offsets and moved out to the world at the end, so a
        far mesh is not built in doubles just to be measured.
        """
        if self._bounds is None:
            los, his = [], []
            for p in (self.local, self.local_edges.reshape(-1, 3),
                      self.local_points):
                if len(p):
                    los.append(p.min(axis=0))
                    his.append(p.max(axis=0))
            if not los:
                return None
            self._bounds = (np.min(los, axis=0) + self.origin,
                            np.max(his, axis=0) + self.origin)
        return self._bounds


def _deflection_for(shape) -> float:
    (mn, mx) = geometry.bbox(shape)
    diag = float(np.linalg.norm(np.subtract(mx, mn)))
    return max(diag * 0.002, 1e-4)


def default_deflection(shape) -> float:
    """The adaptive mesh deflection tessellate() uses when none is given —
    exposed so callers (e.g. STL export) can scale off it for quality presets."""
    return _deflection_for(shape)


def _face_mesh(face) -> tuple | None:
    loc = TopLoc_Location()
    tri = occ.triangulation(face, loc)
    if tri is None:
        return None
    trsf = loc.Transformation()
    n = tri.NbNodes()
    verts = np.empty((n, 3), np.float64)
    for i in range(1, n + 1):
        p = tri.Node(i).Transformed(trsf)
        verts[i - 1] = (p.X(), p.Y(), p.Z())
    m = tri.NbTriangles()
    idx = np.empty((m, 3), np.uint32)
    for i in range(1, m + 1):
        t = tri.Triangle(i)
        idx[i - 1] = (t.Value(1) - 1, t.Value(2) - 1, t.Value(3) - 1)
    reversed_face = (face.Orientation()
                     == TopAbs_Orientation.TopAbs_REVERSED)
    if reversed_face:
        idx = idx[:, ::-1].copy()
    normals = _smooth_normals(verts, idx)
    # the per-vertex curvature loop is pure Python (~17% of tessellation)
    # and only the curvature display mode reads it — skip unless latched
    if _CURVATURE:
        curv = _vertex_curvature(face, tri, n, reversed_face)
    else:
        curv = np.zeros(n, np.float32)
    return verts, normals, idx, curv


_CURVATURE = False      # latched on by the first curvature-mode viewport


def set_curvature_enabled(on: bool):
    global _CURVATURE
    _CURVATURE = bool(on)


def curvature_enabled() -> bool:
    return _CURVATURE


def _vertex_curvature(face, tri, n: int, reversed_face: bool) -> np.ndarray:
    """Signed mean curvature at each triangulation vertex (0 on failure)."""
    curv = np.zeros(n, np.float32)
    if not tri.HasUVNodes():
        return curv
    try:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        from OCP.BRepLProp import BRepLProp_SLProps
        surf = BRepAdaptor_Surface(face)
        props = BRepLProp_SLProps(surf, 2, 1e-6)
        sign = -1.0 if reversed_face else 1.0
        for i in range(1, n + 1):
            uv = tri.UVNode(i)
            props.SetParameters(uv.X(), uv.Y())
            if props.IsCurvatureDefined():
                curv[i - 1] = sign * props.MeanCurvature()
    except Exception:
        pass
    return curv


def _smooth_normals(verts: np.ndarray, tris: np.ndarray) -> np.ndarray:
    """Area-weighted per-vertex normals."""
    normals = np.zeros_like(verts)
    if len(tris):
        v0, v1, v2 = (verts[tris[:, k]] for k in range(3))
        face_n = np.cross(v1 - v0, v2 - v0)
        for k in range(3):
            np.add.at(normals, tris[:, k], face_n)
    lens = np.linalg.norm(normals, axis=1, keepdims=True)
    lens[lens < 1e-12] = 1.0
    return (normals / lens).astype(np.float32)


def _edge_polyline(edge, deflection: float) -> np.ndarray | None:
    try:
        adaptor = occ.edge_adaptor(edge)
        disc = GCPnts_TangentialDeflection(adaptor, 0.25, deflection, 2)
        n = disc.NbPoints()
        if n < 2:
            return None
        pts = np.empty((n, 3), np.float64)
        for i in range(1, n + 1):
            p = disc.Value(i)
            pts[i - 1] = (p.X(), p.Y(), p.Z())
        return pts
    except Exception:
        return None


_ISO_FRACTIONS = (0.25, 0.5, 0.75)
_ISO_SAMPLES = 48


def _is_flat(face, surf) -> bool:
    """Is this face flat, whatever OCCT files its surface under?

    Cheap answer first: a surface built as a plane is one, and a
    cylinder, cone, sphere or torus never is. Only the free-form
    spellings are worth fitting a plane to, and those are exactly the
    ones that arrive flat in practice: a wall swept from a NURBS
    profile, or any extrusion read out of a .3dm, where every face
    comes in as a BSpline no matter how straight it is.
    """
    from OCP.BRepLib import BRepLib_FindSurface
    from OCP.GeomAbs import GeomAbs_SurfaceType as T

    kind = surf.GetType()
    if kind == T.GeomAbs_Plane:
        return True
    if kind not in (T.GeomAbs_BSplineSurface, T.GeomAbs_BezierSurface,
                    T.GeomAbs_SurfaceOfExtrusion,
                    T.GeomAbs_SurfaceOfRevolution,
                    T.GeomAbs_OffsetSurface, T.GeomAbs_OtherSurface):
        return False
    if not _normals_agree(surf):
        return False        # provably bent, and far cheaper to prove
    try:
        return bool(BRepLib_FindSurface(face, 1e-7, True).Found())
    except Exception:                                      # noqa: BLE001
        return False


#: Where the flatness sampler looks, in parametric fractions.
_FLAT_SAMPLES = ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0), (1.0, 1.0), (0.5, 0.5))


def _normals_agree(surf, tol: float = 1e-6) -> bool:
    """Do a handful of sampled normals all point the same way?

    A fast reject, not a proof: normals that disagree mean the surface
    bends somewhere, which is enough to keep its isocurves without
    paying for a least-squares plane fit that was always going to
    fail. Normals that agree only earn the face the real test.

    Deliberately plain arithmetic. numpy on five three-vectors costs
    more than the plane fit this exists to avoid.
    """
    from ..core.occ import gp_Pnt, gp_Vec

    u0, u1 = surf.FirstUParameter(), surf.LastUParameter()
    v0, v1 = surf.FirstVParameter(), surf.LastVParameter()
    for t in (u0, u1, v0, v1):
        if t != t or t in (float("inf"), float("-inf")):
            return False
    p, du, dv = gp_Pnt(), gp_Vec(), gp_Vec()      # filled in place
    first = None
    for fu, fv in _FLAT_SAMPLES:
        try:
            surf.D1(u0 + (u1 - u0) * fu, v0 + (v1 - v0) * fv, p, du, dv)
        except Exception:                                  # noqa: BLE001
            return False
        ax, ay, az = du.X(), du.Y(), du.Z()
        bx, by, bz = dv.X(), dv.Y(), dv.Z()
        nx = ay * bz - az * by
        ny = az * bx - ax * bz
        nz = ax * by - ay * bx
        reach = (nx * nx + ny * ny + nz * nz) ** 0.5
        if reach < 1e-12:
            continue                      # degenerate corner, no opinion
        nx, ny, nz = nx / reach, ny / reach, nz / reach
        if first is None:
            first = (nx, ny, nz)
        else:
            fx, fy, fz = first
            if abs(abs(fx * nx + fy * ny + fz * nz) - 1.0) > tol:
                return False
    return first is not None


def _face_isocurves(face) -> list[np.ndarray]:
    """Isoparametric polylines on a curved face, clipped to its trims.

    A flat face gets none. Its isocurves would be straight lines lying
    in the plane of the edges already drawn around them, so they add
    nothing to read and plenty to look at.
    """
    from ..core.occ import (
        BRepAdaptor_Surface, BRepTopAdaptor_FClass2d, TopAbs_State, gp_Pnt2d,
    )

    surf = BRepAdaptor_Surface(face)
    if _is_flat(face, surf):
        return []
    u0, u1 = surf.FirstUParameter(), surf.LastUParameter()
    v0, v1 = surf.FirstVParameter(), surf.LastVParameter()
    if not all(np.isfinite([u0, u1, v0, v1])):
        return []
    classifier = BRepTopAdaptor_FClass2d(face, 1e-9)
    inside = (TopAbs_State.TopAbs_IN, TopAbs_State.TopAbs_ON)

    polylines = []
    for direction in ("u", "v"):
        for frac in _ISO_FRACTIONS:
            run = []
            for i in range(_ISO_SAMPLES + 1):
                t = i / _ISO_SAMPLES
                if direction == "u":
                    u = u0 + (u1 - u0) * frac
                    v = v0 + (v1 - v0) * t
                else:
                    u = u0 + (u1 - u0) * t
                    v = v0 + (v1 - v0) * frac
                if classifier.Perform(gp_Pnt2d(u, v)) in inside:
                    p = surf.Value(u, v)
                    run.append((p.X(), p.Y(), p.Z()))
                else:
                    if len(run) >= 2:
                        polylines.append(np.asarray(run, float))
                    run = []
            if len(run) >= 2:
                polylines.append(np.asarray(run, float))
    return polylines


def _hatch_outline(shape):
    """The edges round a hatch's region, which are not drawn: a hatch is
    its fill, as in Rhino and AutoCAD, and its boundary is whatever curves
    were drawn round it (#92). None for anything that is not a hatch."""
    from .hatch import HatchShape
    if not isinstance(shape, HatchShape):
        return None
    from OCP.TopExp import TopExp
    from OCP.TopTools import TopTools_IndexedMapOfShape
    edges = TopTools_IndexedMapOfShape()
    TopExp.MapShapes_s(shape.region, occ.EDGE, edges)
    return edges


def tessellate(shape, deflection: float | None = None) -> DisplayMesh:
    from .mesh import MeshShape, mesh_to_display
    from .pointcloud import PointCloudShape, cloud_to_display
    if isinstance(shape, MeshShape):
        return mesh_to_display(shape)
    if isinstance(shape, PointCloudShape):
        return cloud_to_display(shape)
    if deflection is None:
        deflection = _deflection_for(shape)
    if geometry.shape_kind(shape) != "curve":
        BRepMesh_IncrementalMesh(shape, deflection, False, 0.35, True)

    all_verts, all_norms, all_tris, all_curv, isos = [], [], [], [], []
    tri_face_ids = []
    offset = 0
    face_index = -1
    exp = TopExp_Explorer(shape, occ.FACE)
    while exp.More():
        face = occ.to_face(exp.Current())
        face_index += 1
        fm = _face_mesh(face)
        exp.Next()
        if fm is None:
            continue
        verts, norms, tris, curv = fm
        all_verts.append(verts)
        all_norms.append(norms)
        all_tris.append(tris + offset)
        all_curv.append(curv)
        tri_face_ids.append(np.full(len(tris), face_index, np.int32))
        offset += len(verts)
        try:
            for pts in _face_isocurves(face):
                isos.append(np.stack([pts[:-1], pts[1:]], axis=1))
        except Exception:
            pass

    segments = []
    seg_edge_ids = []
    outline = _hatch_outline(shape)
    for edge_index, edge in enumerate(geometry.edges_of(shape)):
        if outline is not None and outline.Contains(edge):
            continue
        pts = _edge_polyline(edge, deflection)
        if pts is not None and len(pts) >= 2:
            seg = np.stack([pts[:-1], pts[1:]], axis=1)
            segments.append(seg)
            seg_edge_ids.append(np.full(len(seg), edge_index, np.int32))

    free_pts = geometry.free_points(shape)
    mesh = DisplayMesh()
    mesh.place(
        vertices=np.concatenate(all_verts) if all_verts else None,
        edge_segments=np.concatenate(segments) if segments else None,
        iso_segments=np.concatenate(isos) if isos else None,
        points=np.asarray(free_pts, float) if free_pts else None)
    if all_verts:
        mesh.normals = np.concatenate(all_norms)
        mesh.triangles = np.concatenate(all_tris)
        mesh.curvature = np.concatenate(all_curv).astype(np.float32)
        mesh.has_curvature = _CURVATURE
        mesh.face_of_triangle = np.concatenate(tri_face_ids)
    if segments:
        mesh.edge_of_segment = np.concatenate(seg_edge_ids)
    return mesh
