"""DXF import/export via ezdxf.

Model export: curves as splines/polylines, surfaces/solids as MESH
entities, layers with true colours. Layout export: the drawn sheet
(HLR linework + annotations) at paper millimetre coordinates.
"""

from __future__ import annotations

import math

import ezdxf
from ezdxf import units as ezdxf_units
import numpy as np

from ..core import geometry, linetype
from ..core.layout import measured_text
from ..core.tessellate import tessellate


# $INSUNITS by document unit.
_INSUNITS = {"mm": ezdxf_units.MM, "cm": ezdxf_units.CM, "m": ezdxf_units.M,
             "in": ezdxf_units.IN, "ft": ezdxf_units.FT}


def _true_color(rgb) -> int:
    r, g, b = (int(c * 255) for c in rgb)
    return (r << 16) | (g << 8) | b


def export_dxf(scene, path: str, only_ids: list | None = None):
    # Told, or ezdxf labels the drawing metres whatever it holds (#101).
    doc = ezdxf.new("R2010", units=_INSUNITS[scene.units])
    msp = doc.modelspace()
    for layer in scene.layers.all():
        if layer.name == "Default":
            continue
        dxf_layer = doc.layers.add(layer.name)
        dxf_layer.true_color = _true_color(layer.color)

    objs = scene.all()
    if only_ids:
        objs = [o for o in objs if o.id in only_ids]
    for obj in objs:
        layer_name = scene.layers.get(obj.layer_id).name
        if layer_name == "Default":
            layer_name = "0"
        attribs = {"layer": layer_name}
        if obj.kind == "hatch":
            _write_hatch(msp, obj.shape, attribs)
            continue
        if obj.kind == "curve":
            for edge in geometry.edges_of(obj.shape):
                pts = geometry.sample_curve(edge, 64)
                closed = geometry.is_closed_curve(edge)
                if _is_straight(pts):
                    msp.add_line(pts[0], pts[-1], dxfattribs=attribs)
                else:
                    msp.add_spline(fit_points=pts, dxfattribs=attribs)
                    if closed:
                        pass
        else:
            mesh = tessellate(obj.shape)
            if not mesh.has_faces:
                continue
            m = msp.add_mesh(dxfattribs=attribs)
            with m.edit_data() as data:
                data.vertices = [tuple(map(float, v))
                                 for v in mesh.vertices]
                data.faces = [tuple(int(i) for i in t)
                              for t in mesh.triangles]
    doc.saveas(path)


def _write_hatch(msp, hatch, attribs):
    """A model hatch as a DXF HATCH in its own plane: its loops as
    polyline paths, its pattern as the lines it is drawn with."""
    from ezdxf.math import OCS
    from ..core.hatch import _rings
    frame = hatch.frame
    normal = frame[:3, 2]
    ocs = OCS(tuple(normal))
    out = msp.add_hatch(dxfattribs=dict(attribs, extrusion=tuple(normal)))
    elevation = ocs.from_wcs(tuple(frame[:3, 3])).z
    out.dxf.elevation = (0.0, 0.0, float(elevation))
    rings = []
    for ring in _rings(hatch.region, frame):
        world = [frame @ np.array([u, v, 0.0, 1.0]) for u, v in ring]
        rings.append([tuple(ocs.from_wcs(tuple(p[:3])))[:2] for p in world])

    def area(r):
        a = np.asarray(r)
        return abs(float(np.dot(a[:, 0], np.roll(a[:, 1], -1))
                         - np.dot(np.roll(a[:, 0], -1), a[:, 1]))) / 2

    rings.sort(key=area, reverse=True)
    for i, ring in enumerate(rings):
        out.paths.add_polyline_path(ring, is_closed=True,
                                    flags=1 if i == 0 else 0)
    if hatch.solid:
        out.set_solid_fill()
        return
    a = math.radians(hatch.angle)
    d = math.cos(a) * frame[:3, 0] + math.sin(a) * frame[:3, 1]
    d_ocs = ocs.from_wcs(tuple(d))
    base = math.degrees(math.atan2(d_ocs.y, d_ocs.x))
    if hatch.definition is not None:
        centre = ocs.from_wcs(tuple(frame[:3, 3]))
        definition = _dxf_definition(hatch.definition, base, hatch.spacing,
                                     (centre.x, centre.y))
        scale = hatch.spacing / hatch.definition.row_spacing
        name = hatch.pattern
    else:
        # Lines and Cross lie centred on the region rather than through
        # its origin, so each family is written through one of the lines
        # it draws: the file then draws them where they are drawn here.
        def line(turn):
            local = [np.asarray(r) @ np.array(
                [[math.cos(turn), -math.sin(turn)],
                 [math.sin(turn), math.cos(turn)]]) for r in rings2d]
            y0 = min(float(r[:, 1].min()) for r in local)
            on = (y0 + hatch.spacing / 2) * np.array(
                [-math.sin(turn), math.cos(turn)])
            point = ocs.from_wcs(tuple(
                (frame @ np.array([on[0], on[1], 0.0, 1.0]))[:3]))
            deg = base + math.degrees(turn - a)
            r = math.radians(deg)
            return [deg, (point.x, point.y),
                    (-math.sin(r) * hatch.spacing,
                     math.cos(r) * hatch.spacing), []]

        rings2d = _rings(hatch.region, frame)
        definition = [line(a)] + ([line(a + math.pi / 2)]
                                  if hatch.pattern == "cross" else [])
        scale, name = 1.0, f"SERP_{hatch.pattern.upper()}"
    out.set_pattern_fill(name, angle=0.0, scale=1.0, pattern_type=2,
                         definition=definition)
    # The lines are written turned and scaled already, as a DXF has them;
    # the angle and scale are what AutoCAD's own dialog shows for them.
    out.dxf.pattern_angle = base % 360.0
    out.dxf.pattern_scale = scale


def _dxf_definition(pattern, turn: float, spacing: float, origin) -> list:
    """A pattern from a .pat file as a DXF HATCH spells its lines, drawn
    turned `turn` degrees and at `spacing` about `origin`: a DXF pattern
    is written already turned and scaled, its offsets in the hatch's own
    plane rather than along each line as a .pat file has them (#92)."""
    scale = spacing / pattern.row_spacing
    t = math.radians(turn)
    out = []
    for ln in pattern.lines:
        ox, oy = ln.origin[0] * scale, ln.origin[1] * scale
        phi = math.radians(ln.angle + turn)
        dx, dy = ln.offset[0] * scale, ln.offset[1] * scale
        out.append([
            ln.angle + turn,
            (origin[0] + ox * math.cos(t) - oy * math.sin(t),
             origin[1] + ox * math.sin(t) + oy * math.cos(t)),
            (dx * math.cos(phi) - dy * math.sin(phi),
             dx * math.sin(phi) + dy * math.cos(phi)),
            [d * scale for d in ln.dashes]])
    return out


def _is_straight(pts, tol=1e-7) -> bool:
    if len(pts) < 3:
        return True
    a = np.asarray(pts[0])
    b = np.asarray(pts[-1])
    d = b - a
    n = np.linalg.norm(d)
    if n < tol:
        return False
    d = d / n
    for p in pts[1:-1]:
        v = np.asarray(p) - a
        if np.linalg.norm(v - np.dot(v, d) * d) > max(n * 1e-6, tol):
            return False
    return True


def import_dxf(scene, path: str) -> int:
    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    layer_map = {}

    def layer_for(entity):
        name = entity.dxf.layer
        if name in ("0", ""):
            return None
        if name not in layer_map:
            existing = scene.layers.find_by_name(name)
            layer_map[name] = (existing or scene.layers.create(name)).id
        return layer_map[name]

    n = 0
    for e in msp:
        kind = e.dxftype()
        shape = None
        try:
            if kind == "LINE":
                shape = geometry.make_line(tuple(e.dxf.start),
                                           tuple(e.dxf.end))
            elif kind == "CIRCLE":
                c = e.dxf.center
                normal = tuple(e.dxf.extrusion)
                shape = geometry.make_circle(tuple(c), e.dxf.radius,
                                             normal=normal)
            elif kind == "ARC":
                c = np.asarray(tuple(e.dxf.center))
                r = e.dxf.radius
                a0 = math.radians(e.dxf.start_angle)
                a1 = math.radians(e.dxf.end_angle)
                if a1 <= a0:
                    a1 += 2 * math.pi
                am = (a0 + a1) / 2
                p = [tuple(c + np.array([math.cos(a) * r,
                                         math.sin(a) * r, 0]))
                     for a in (a0, am, a1)]
                shape = geometry.make_arc_3pt(*p)
            elif kind in ("LWPOLYLINE", "POLYLINE"):
                if kind == "LWPOLYLINE":
                    z = float(e.dxf.elevation or 0)
                    pts = [(p[0], p[1], z) for p in e.get_points()]
                    closed = bool(e.closed)
                else:
                    pts = [tuple(v.dxf.location) for v in e.vertices]
                    closed = bool(e.is_closed)
                if len(pts) >= 2:
                    shape = geometry.make_polyline(pts, closed=closed)
            elif kind == "SPLINE":
                cps = [tuple(p) for p in e.control_points]
                if len(cps) >= 2:
                    # a conic written as a NURBS carries its shape in the
                    # weights and its parameterisation in the knots; with
                    # neither, an ellipse reads as a blob (issue #28)
                    try:
                        shape = geometry.make_nurbs_curve(
                            cps, degree=e.dxf.degree,
                            knots=[float(k) for k in e.knots],
                            weights=[float(w) for w in e.weights])
                    except (geometry.GeometryError, AttributeError,
                            ValueError, RuntimeError):
                        shape = geometry.make_control_curve(
                            cps, degree=e.dxf.degree)
                else:
                    fit = [tuple(p) for p in e.fit_points]
                    if len(fit) >= 2:
                        shape = geometry.make_interp_curve(fit)
            elif kind == "MESH":
                from .obj import _shell_from_triangles
                verts = np.asarray([tuple(v) for v in e.vertices], float)
                tris = []
                for face in e.faces:
                    f = list(face)
                    for k in range(1, len(f) - 1):
                        tris.append((f[0], f[k], f[k + 1]))
                shape = _shell_from_triangles(verts, tris)
            elif kind == "ELLIPSE":
                # the major axis is a vector, and only its length was being
                # read: every ellipse came back lying flat in world XY with
                # its long axis along world X, and an arc came back whole
                c = tuple(e.dxf.center)
                major = np.asarray(tuple(e.dxf.major_axis), float)
                r1 = float(np.linalg.norm(major))
                r2 = r1 * e.dxf.ratio
                shape = geometry.make_ellipse_axis(
                    c, tuple(major), r1, r2,
                    normal=tuple(e.dxf.extrusion),
                    start=float(e.dxf.start_param),
                    end=float(e.dxf.end_param))
            elif kind == "HATCH":
                shape = _hatches_from(e)
        except geometry.GeometryError:
            continue
        for part in (shape if isinstance(shape, list)
                     else [] if shape is None else [shape]):
            from . import adopt_hatch_pattern
            adopt_hatch_pattern(scene, part)
            scene.add(part, layer_id=layer_for(e))
            n += 1
    return n


def _hatches_from(entity) -> list:
    """A DXF HATCH as hatch objects, one for each island it fills (#33),
    drawn with the lines AutoCAD draws it with (#92).

    The boundary paths come back from ezdxf as lines and Bezier spans in
    world coordinates, arcs and ellipses already as Beziers, and are built
    as exact edges; nesting decides which loops are holes.

    A DXF writes its pattern already turned by the hatch's angle and scaled
    by its scale, every line through a point and stepping by an offset in
    the entity's own plane. Those lines are taken back to the pattern they
    were made from, and the hatch draws that pattern at the same angle and
    scale about the plane's origin, which lays every line where the file
    has it. A file that names its pattern without writing it out gets the
    one ezdxf knows by that name, as AutoCAD would.
    """
    from ezdxf import path as dxfpath
    from ezdxf.math import OCS
    from ..core.hatch import HatchShape
    wires = []
    for path in dxfpath.from_hatch(entity):
        wire = _wire_from_path(path)
        if wire is not None:
            wires.append(wire)
    if not wires:
        return []
    regions = geometry.planar_regions(wires)
    ocs = OCS(entity.dxf.extrusion)
    frame = np.eye(4)
    frame[:3, 0] = tuple(ocs.ux)
    frame[:3, 1] = tuple(ocs.uy)
    frame[:3, 2] = tuple(ocs.uz)
    name, angle, spacing, definition, at = _dxf_pattern(entity)
    frame[:3, 3] = tuple(ocs.to_wcs((at[0], at[1], _elevation(entity))))
    out = []
    for region in regions:
        try:
            out.append(HatchShape._from_parts(region, name, angle, spacing,
                                              frame, definition))
        except geometry.GeometryError:
            continue
    return out


def _elevation(entity) -> float:
    try:
        return float(entity.dxf.elevation[2])
    except (AttributeError, IndexError, TypeError):
        return 0.0


def _wire_from_path(path):
    """One ezdxf boundary path as a closed wire of exact edges."""
    from ezdxf.path import Command
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.Geom import Geom_BezierCurve
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.gp import gp_Pnt

    def bezier(points):
        poles = TColgp_Array1OfPnt(1, len(points))
        for i, p in enumerate(points, 1):
            poles.SetValue(i, gp_Pnt(float(p.x), float(p.y), float(p.z)))
        return BRepBuilderAPI_MakeEdge(Geom_BezierCurve(poles)).Edge()

    edges = []
    start = path.start
    for cmd in path:
        end = cmd.end
        if cmd.type == Command.LINE_TO:
            if start.distance(end) > 1e-12:
                edges.append(geometry.make_line(tuple(start), tuple(end)))
        elif cmd.type == Command.CURVE3_TO:
            edges.append(bezier([start, cmd.ctrl, end]))
        elif cmd.type == Command.CURVE4_TO:
            edges.append(bezier([start, cmd.ctrl1, cmd.ctrl2, end]))
        start = end
    if start.distance(path.start) > 1e-9:
        edges.append(geometry.make_line(tuple(start), tuple(path.start)))
    if not edges:
        return None
    mk = BRepBuilderAPI_MakeWire()
    for edge in edges:
        mk.Add(geometry.occ.to_edge(edge))
    return mk.Wire() if mk.IsDone() else None


def _dxf_pattern(entity) -> tuple:
    """(name, angle in degrees, spacing, definition, origin) for a HATCH
    entity: the pattern it was made from, the angle and spacing that make
    it again exactly as it is written, and the point in the entity's plane
    it is laid from, the first of its lines' base points."""
    from ..core.hatch_patterns import HatchPattern, PatternLine, import_name
    if entity.dxf.solid_fill or getattr(entity, "gradient", None):
        return "solid", 0.0, 1.0, None, (0.0, 0.0)
    name = str(entity.dxf.pattern_name or "").strip() or "pattern"
    turn = float(entity.dxf.pattern_angle or 0.0)
    scale = float(entity.dxf.pattern_scale or 1.0) or 1.0
    lines = list(entity.pattern.lines) if entity.pattern else []
    if not lines:
        try:
            entity.set_pattern_fill(name, angle=turn, scale=scale)
            lines = list(entity.pattern.lines) if entity.pattern else []
        except Exception:                                   # noqa: BLE001
            lines = []
    if not lines:
        return "lines", 45.0, 3.175 * scale, None, (0.0, 0.0)
    at = (float(lines[0].base_point[0]), float(lines[0].base_point[1]))
    if name.upper() in ("SERP_LINES", "SERP_CROSS"):
        # this app's own, written centred on the region as it draws them
        first = lines[0]
        phi = math.radians(float(first.angle))
        spacing = abs(-float(first.offset[0]) * math.sin(phi)
                      + float(first.offset[1]) * math.cos(phi))
        return (name[5:].lower(), float(first.angle), spacing or 1.0, None,
                at)
    t = math.radians(turn)
    families = []
    for ln in lines:
        phi = math.radians(float(ln.angle))
        bx = float(ln.base_point[0]) - at[0]
        by = float(ln.base_point[1]) - at[1]
        ox, oy = float(ln.offset[0]), float(ln.offset[1])
        families.append(PatternLine(
            float(ln.angle) - turn,
            ((bx * math.cos(t) + by * math.sin(t)) / scale,
             (-bx * math.sin(t) + by * math.cos(t)) / scale),
            ((ox * math.cos(phi) + oy * math.sin(phi)) / scale,
             (-ox * math.sin(phi) + oy * math.cos(phi)) / scale),
            tuple(float(d) / scale for d in ln.dash_length_items)))
    pattern = HatchPattern(name, "", tuple(families))
    name, definition = import_name(pattern, "dxf")
    return name, turn, scale * pattern.row_spacing, definition, at


def export_layout_dxf(window, layout, path: str):
    """The composed sheet as 2D DXF at paper-mm coordinates."""
    doc = ezdxf.new("R2010", units=ezdxf_units.MM)
    msp = doc.modelspace()
    doc.layers.add("VISIBLE")
    doc.layers.add("HIDDEN")
    hidden_lt = "DASHED"
    if hidden_lt not in doc.linetypes:
        doc.linetypes.add(hidden_lt, pattern=[2.5, 1.5, -1.0])
    doc.layers.get("HIDDEN").dxf.linetype = hidden_lt
    doc.layers.add("ANNOT")
    # paper geometry on its own layer, so a border can be turned off without
    # losing the drawing it frames
    doc.layers.add("PAPER")

    lv = window.viewport.layout_view
    for detail in layout.details:
        if detail.display_mode in ("shaded", "ghosted"):
            continue
        data = lv._detail_hlr(detail)
        cx = detail.x + detail.w / 2
        cy = detail.y + detail.h / 2
        s = 1.0 / detail.scale_denom

        def to_paper(poly):
            return [(cx + p[0] * s, cy + p[1] * s) for p in poly[:, :2]]

        # Visible edges plot at their layer's print width. DXF lineweight is in
        # 1/100mm; a layer left at the device default sets none, so the plot
        # stays the way it has always drawn (by-layer default).
        groups = data.get("visible_groups")
        if groups is None:
            groups = [(0.0, "Continuous", data["visible"])]
        for width_mm, _name, polys in groups:
            attribs = {"layer": "VISIBLE"}
            if width_mm > 0:
                attribs["lineweight"] = round(width_mm * 100)
            for poly in polys:
                msp.add_lwpolyline(to_paper(poly), dxfattribs=dict(attribs))
        if detail.display_mode == "hidden":
            for poly in data["hidden"]:
                msp.add_lwpolyline(to_paper(poly),
                                   dxfattribs={"layer": "HIDDEN"})
        msp.add_lwpolyline(
            [(detail.x, detail.y), (detail.x + detail.w, detail.y),
             (detail.x + detail.w, detail.y + detail.h),
             (detail.x, detail.y + detail.h)],
            close=True, dxfattribs={"layer": "ANNOT"})

    # geometry drawn on the paper itself: already in paper millimetres, which
    # is what a 2D DXF wants, so it goes out as it is
    for obj in layout.objects:
        attribs = {"layer": "PAPER",
                   "lineweight": round(obj.lineweight * 100)}   # DXF: 1/100mm
        if linetype.pattern_for(obj.linetype):
            attribs["linetype"] = hidden_lt
        if obj.color:
            attribs["true_color"] = _true_color(obj.color)
        for poly in obj.polylines:
            msp.add_lwpolyline([(p[0], p[1]) for p in poly],
                               dxfattribs=dict(attribs))

    for note in layout.notes:
        msp.add_text(note.text, height=note.height, dxfattribs={
            "layer": "ANNOT"}).set_placement((note.x, note.y))
    for dim in layout.dims:
        a = np.array([dim.x1, dim.y1])
        b = np.array([dim.x2, dim.y2])
        d = b - a
        length = np.linalg.norm(d)
        if length < 1e-9:
            continue
        d = d / length
        nvec = np.array([-d[1], d[0]])
        ao, bo = a + nvec * dim.offset, b + nvec * dim.offset
        for p, q in ((a, ao), (b, bo), (ao, bo)):
            msp.add_line((p[0], p[1]), (q[0], q[1]),
                         dxfattribs={"layer": "ANNOT"})
        text = dim.text or measured_text(dim, length, window.scene)
        mid = (a + b) / 2 + nvec * (dim.offset + 2)
        msp.add_text(text, height=3.2, dxfattribs={
            "layer": "ANNOT"}).set_placement((mid[0], mid[1]))
    doc.saveas(path)
