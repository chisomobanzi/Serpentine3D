"""DXF import/export via ezdxf.

Model export: curves as splines/polylines, surfaces/solids as MESH
entities, layers with true colours. Layout export: the drawn sheet
(HLR linework + annotations) at paper millimetre coordinates.
"""

from __future__ import annotations

import math
import os
import uuid
from dataclasses import dataclass

import ezdxf
from ezdxf import units as ezdxf_units
import numpy as np

from ..core import geometry, linetype
from ..core.dimension import DimensionShape
from ..core.layout import measured_text
from ..core.tessellate import tessellate


# $INSUNITS by document unit.
_INSUNITS = {"mm": ezdxf_units.MM, "cm": ezdxf_units.CM, "m": ezdxf_units.M,
             "in": ezdxf_units.IN, "ft": ezdxf_units.FT}


def _true_color(rgb) -> int:
    r, g, b = (round(c * 255) for c in rgb)
    return (r << 16) | (g << 8) | b


def _hatch_look_out(scene, obj, out):
    """A hatch's own colour and background, written as AutoCAD keeps
    them: the colour on the entity, the background as its
    HATCHBACKGROUNDCOLOR."""
    if out is None:
        return
    color, ground = scene.hatch_look_of(obj)
    style = obj.hatch_style or {}
    if style.get("color", "").startswith("#") and color is not None:
        out.rgb = tuple(round(c * 255) for c in color)
    if ground is not None:
        out.bgcolor = tuple(round(c * 255) for c in ground)


def _lineweight(mm: float) -> int:
    """A print width in mm as a DXF lineweight: the nearest of the widths
    DXF allows, in hundredths of a millimetre; 0 is the printer's, which
    DXF calls DEFAULT."""
    from ezdxf.lldxf.const import VALID_DXF_LINEWEIGHTS
    if mm <= 0:
        return _LW_DEFAULT
    return min(VALID_DXF_LINEWEIGHTS, key=lambda lw: abs(lw - mm * 100))


def _dxf_linetype(doc, name: str) -> str | None:
    """The DXF linetype one of the app's is written as, added to the file
    if it lacks it; None for Continuous, which every file has."""
    pattern = linetype.pattern_for(name)
    if not pattern:
        return None
    key = name.upper()
    if key not in doc.linetypes:
        # dashes positive, gaps negative, as DXF has them
        doc.linetypes.add(key, pattern=[sum(pattern)] + [
            v if i % 2 == 0 else -v for i, v in enumerate(pattern)])
    return key


def export_dxf(scene, path: str, only_ids: list | None = None):
    # Told, or ezdxf labels the drawing metres whatever it holds (#101).
    doc = ezdxf.new("R2010", units=_INSUNITS[scene.units])
    msp = doc.modelspace()
    for layer in scene.layers.all():
        if layer.name == "Default":
            continue
        # The layer's look, as the import reads it back: its colour, its
        # print width as a lineweight, its linetype and its switches.
        dxf_layer = doc.layers.add(layer.name)
        dxf_layer.rgb = tuple(round(c * 255) for c in layer.color)
        dxf_layer.dxf.lineweight = _lineweight(layer.print_width)
        kind = _dxf_linetype(doc, layer.linetype)
        if kind:
            dxf_layer.dxf.linetype = kind
        if not layer.visible:
            dxf_layer.off()
        if layer.locked:
            dxf_layer.lock()

    objs = scene.all()
    if only_ids:
        objs = [o for o in objs if o.id in only_ids]
    for obj in objs:
        layer_name = scene.layers.get(obj.layer_id).name
        if layer_name == "Default":
            layer_name = "0"
        attribs = {"layer": layer_name}
        if obj.color is not None:
            attribs["true_color"] = _true_color(obj.color)
        if obj.print_width is not None:
            attribs["lineweight"] = _lineweight(obj.print_width)
        if obj.linetype and obj.linetype != "ByLayer":
            attribs["linetype"] = (_dxf_linetype(doc, obj.linetype)
                                   or "CONTINUOUS")
        if obj.kind == "hatch":
            out = _write_hatch(msp, obj.shape, attribs)
            _hatch_look_out(scene, obj, out)
            continue
        if isinstance(obj.shape, DimensionShape):
            _write_dimension(msp, obj.shape, attribs)
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


def _write_dimension(msp, dim, attribs):
    """A model dimension as a DXF linear DIMENSION, measuring the same
    points along the same direction and looking as it does here."""
    from ezdxf.math import OCS
    _origin, along, _across, normal = dim.frame()
    ocs = OCS(tuple(normal))
    x = np.asarray(tuple(ocs.from_wcs(tuple(dim.direction))), float)
    angle = math.degrees(math.atan2(x[1], x[0]))
    override = {"dimtxt": dim.text_height, "dimasz": dim.arrow_size,
                "dimdec": int(dim.decimals), "dimlfac": dim.length_factor,
                "dimpost": "<> " + dim.suffix if dim.suffix else "",
                "dimtad": 1, "dimzin": 8 if dim.decimals else 0,
                "dimexo": dim.sizes()[2], "dimexe": dim.sizes()[3],
                "dimgap": dim.sizes()[4], "dimdsep": ord(".")}
    if dim.arrow == "tick":
        override["dimtsz"] = dim.arrow_size / 2
    out = msp.add_linear_dim(
        base=tuple(ocs.from_wcs(dim.at)), p1=tuple(ocs.from_wcs(dim.p1)),
        p2=tuple(ocs.from_wcs(dim.p2)), angle=angle, text=dim.text or "<>",
        dxfattribs=dict(attribs, extrusion=tuple(normal)), override=override)
    out.render()
    return out.dimension


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
    # ezdxf's fills set the colour as they go, to white unless told: told
    # BYLAYER, the hatch keeps the colour its attributes gave it.
    if hatch.solid:
        out.set_solid_fill(color=_BYLAYER_ACI)
        return out
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
    out.set_pattern_fill(name, color=_BYLAYER_ACI, angle=0.0, scale=1.0,
                         pattern_type=2, definition=definition)
    # The lines are written turned and scaled already, as a DXF has them;
    # the angle and scale are what AutoCAD's own dialog shows for them.
    out.dxf.pattern_angle = base % 360.0
    out.dxf.pattern_scale = scale
    return out


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


def import_dxf(scene, path: str, progress=None, units: str | None = None,
               notes: list | None = None) -> int:
    """The model space of a DXF as objects in the scene.

    Each object is drawn as the file draws it: on its layer, which comes
    in with its colour, its lineweight as a print width, its linetype and
    whether it is on, and in its own colour, lineweight and linetype where
    it overrides the layer's (`_Look`). A block reference comes in as the
    pieces its block is made of, where the reference places them and
    grouped so a click takes the lot, as a Rhino block does; a piece that
    leaves its look to the block (BYBLOCK, or layer 0) takes the
    reference's. A hatch keeps its colour and its background colour, a
    text its words, height, turn and anchor. A dimension comes in as the
    lines, arrows and text its file draws it with, grouped the same way.

    A file that says what unit it is in ($INSUNITS) arrives at its real
    size in `units`, the scene's unless given; `notes` hears that it was.
    """
    from .progress import Progress
    report = progress or Progress()
    report(0.0, f"Reading {os.path.basename(path)}…")
    doc = ezdxf.readfile(path)
    entities = list(doc.modelspace())
    looks = _Looks(doc, scene)
    looks.factor = _unit_factor(doc, units or scene.units, notes)
    convert = report.part(0.15, 1.0)
    total = len(entities) or 1
    n = 0
    for index, entity in enumerate(entities):
        if index % 250 == 0:
            convert(index / total,
                    f"Converting object {index + 1} of {total}")
        kind = entity.dxftype()
        if kind == "INSERT" or (kind in _DIMENSIONS
                                and not _is_linear(entity)):
            group = uuid.uuid4().hex[:12]
            name = str(entity.dxf.name) if kind == "INSERT" else "Dimension"
            for member, look in _exploded(entity, looks.of(entity), looks):
                n += _add_entity(scene, member, look, looks, name=name,
                                 group=group)
        else:
            n += _add_entity(scene, entity, looks.of(entity), looks)
    convert.done()
    return n


# what DXF draws as an anonymous block of its own, *D1, *D2 and on
_DIMENSIONS = ("DIMENSION", "ARC_DIMENSION", "LARGE_RADIAL_DIMENSION")


def _add_entity(scene, entity, look, looks, name: str = "",
                group: str | None = None) -> int:
    """Put what one entity converts to into the scene, looking as `look`
    says. Returns how many objects it made."""
    from . import adopt_hatch_pattern
    try:
        shape = _shape_of(entity)
    except (geometry.GeometryError, ValueError, AttributeError):
        return 0
    parts = shape if isinstance(shape, list) else \
        [] if shape is None else [shape]
    if not parts:
        return 0
    if looks.factor != 1.0:
        size = np.diag([looks.factor] * 3 + [1.0])
        parts = [geometry.apply_matrix(part, size) for part in parts]
        # a dimension still says what it said in the file's unit
        parts = [part.edited(length_factor=part.length_factor / looks.factor)
                 if isinstance(part, DimensionShape) else part
                 for part in parts]
    layer_id = looks.layer_id(look.layer)
    for part in parts:
        adopt_hatch_pattern(scene, part)
        obj = scene.add(part, name=name or None, layer_id=layer_id)
        fields = {}
        if look.color is not None:
            fields["color"] = look.color
        if look.width is not None:
            fields["print_width"] = look.width
        if look.linetype is not None:
            fields["linetype"] = look.linetype
        if group is not None:
            fields["group_id"] = group
        if obj.kind == "hatch":
            style = {"color": (_hex(look.color) if look.color is not None
                               else "layer")}
            ground = _hatch_background(entity)
            if ground is not None:
                style["background"] = _hex(ground)
            fields["hatch_style"] = style
        if fields:
            scene.update(obj.id, **fields)
    return len(parts)


def _shape_of(e):
    """The shape, or shapes, one DXF entity converts to, or None."""
    kind = e.dxftype()
    if kind == "LINE":
        return geometry.make_line(tuple(e.dxf.start), tuple(e.dxf.end))
    # a circle, an arc and a 2D polyline are written in their own plane's
    # coordinates (OCS); one mirrored in AutoCAD has its plane facing down,
    # and read as world coordinates it lands mirrored, far from the rest
    if kind == "CIRCLE":
        return geometry.make_circle(tuple(e.ocs().to_wcs(e.dxf.center)),
                                    e.dxf.radius,
                                    normal=tuple(e.dxf.extrusion))
    if kind == "ARC":
        c = np.asarray(tuple(e.dxf.center))
        r = e.dxf.radius
        a0 = math.radians(e.dxf.start_angle)
        a1 = math.radians(e.dxf.end_angle)
        if a1 <= a0:
            a1 += 2 * math.pi
        am = (a0 + a1) / 2
        ocs = e.ocs()
        p = [tuple(ocs.to_wcs(tuple(
                 c + np.array([math.cos(a) * r, math.sin(a) * r, 0]))))
             for a in (a0, am, a1)]
        return geometry.make_arc_3pt(*p)
    if kind == "LWPOLYLINE":
        z = float(e.dxf.elevation or 0)
        return _polyline_of([(p[0], p[1], z, p[2])
                             for p in e.get_points("xyb")],
                            bool(e.closed), e.ocs())
    if kind == "POLYLINE":
        if e.is_2d_polyline:
            return _polyline_of(
                [(*tuple(v.dxf.location), float(v.dxf.get("bulge", 0)))
                 for v in e.vertices], bool(e.is_closed), e.ocs())
        if e.is_3d_polyline:
            pts = [tuple(v.dxf.location) for v in e.vertices]
            return geometry.make_polyline(pts, closed=bool(e.is_closed)) \
                if len(pts) >= 2 else None
        return None
    if kind == "SPLINE":
        cps = [tuple(p) for p in e.control_points]
        if len(cps) >= 2:
            # a conic written as a NURBS carries its shape in the weights
            # and its parameterisation in the knots; with neither, an
            # ellipse reads as a blob (issue #28)
            try:
                return geometry.make_nurbs_curve(
                    cps, degree=e.dxf.degree,
                    knots=[float(k) for k in e.knots],
                    weights=[float(w) for w in e.weights])
            except (geometry.GeometryError, AttributeError,
                    ValueError, RuntimeError):
                return geometry.make_control_curve(cps, degree=e.dxf.degree)
        fit = [tuple(p) for p in e.fit_points]
        return geometry.make_interp_curve(fit) if len(fit) >= 2 else None
    if kind == "MESH":
        from .obj import _shell_from_triangles
        verts = np.asarray([tuple(v) for v in e.vertices], float)
        tris = []
        for face in e.faces:
            f = list(face)
            for k in range(1, len(f) - 1):
                tris.append((f[0], f[k], f[k + 1]))
        return _shell_from_triangles(verts, tris)
    if kind == "ELLIPSE":
        # the major axis is a vector, and only its length was being read:
        # every ellipse came back lying flat in world XY with its long
        # axis along world X, and an arc came back whole
        major = np.asarray(tuple(e.dxf.major_axis), float)
        r1 = float(np.linalg.norm(major))
        return geometry.make_ellipse_axis(
            tuple(e.dxf.center), tuple(major), r1, r1 * e.dxf.ratio,
            normal=tuple(e.dxf.extrusion),
            start=float(e.dxf.start_param), end=float(e.dxf.end_param))
    if kind == "HATCH":
        return _hatches_from(e)
    if kind in ("TEXT", "MTEXT", "ATTRIB"):
        return _text_of(e)
    if kind in ("SOLID", "TRACE"):
        return _filled_of(e)
    if kind == "DIMENSION" and _is_linear(e):
        return _dimension_of(e)
    return None


def _is_linear(e) -> bool:
    """A DIMENSION that measures a length along a direction: rotated,
    horizontal and vertical (type 0) or aligned (type 1)."""
    try:
        return e.dxftype() == "DIMENSION" and (int(e.dimtype) & 7) in (0, 1)
    except Exception:                                      # noqa: BLE001
        return False


# AutoCAD's names for a tick, rather than an arrow, at a dimension's ends
_TICKS = {"ARCHTICK", "_ARCHTICK", "OBLIQUE", "_OBLIQUE", "INTEGRAL",
          "_INTEGRAL"}


def _dimension_of(e):
    """A linear DIMENSION as a model dimension: the points it measures, the
    direction it measures along, where its line is, and its look from its
    dimension style and the overrides it carries."""
    from ezdxf.math import OCS
    style = e.override()

    def get(name, default):
        try:
            value = style.get(name, default)
        except Exception:                                  # noqa: BLE001
            value = default
        return default if value is None else value

    scale = float(get("dimscale", 1.0) or 1.0)
    normal = np.asarray(tuple(e.dxf.extrusion), float)
    if (int(e.dimtype) & 7) == 1:
        direction = np.subtract(tuple(e.dxf.defpoint3), tuple(e.dxf.defpoint2))
    else:
        turn = math.radians(float(e.dxf.get("angle", 0.0)))
        ocs = OCS(tuple(normal))
        direction = np.asarray(tuple(ocs.to_wcs(
            (math.cos(turn), math.sin(turn), 0.0))), float)
    post = str(get("dimpost", "") or "")
    prefix, _, suffix = post.partition("<>") if "<>" in post else ("", "", "")
    typed = str(e.dxf.get("text", "") or "")
    if typed == "<>":
        typed = ""
    if prefix and not typed:
        typed = prefix + "<>"
    blocks = {str(get(name, "") or "").upper()
              for name in ("dimblk", "dimblk1", "dimblk2")}
    tick = float(get("dimtsz", 0.0) or 0.0) > 0 or bool(blocks & _TICKS)
    height = float(get("dimtxt", 2.5)) * scale
    arrow = float(get("dimasz", 2.5)) * scale
    return DimensionShape(
        tuple(e.dxf.defpoint2), tuple(e.dxf.defpoint3), tuple(e.dxf.defpoint),
        direction=tuple(direction), normal=tuple(normal),
        text_height=height,
        arrow_size=(float(get("dimtsz", 0.0)) * scale * 2
                    if float(get("dimtsz", 0.0) or 0.0) > 0 else arrow),
        arrow="tick" if tick else "arrow",
        decimals=int(get("dimdec", 2)), suffix=suffix, text=typed,
        font_family=_dim_font(e, str(get("dimtxsty", "Standard"))),
        length_factor=float(get("dimlfac", 1.0) or 1.0),
        extension_offset=float(get("dimexo", 0.625)) * scale,
        extension_beyond=float(get("dimexe", 1.25)) * scale,
        text_gap=abs(float(get("dimgap", 0.625))) * scale)


def _dim_font(e, style_name: str) -> str:
    try:
        font = str(e.doc.styles.get(style_name).dxf.font or "")
    except Exception:                                      # noqa: BLE001
        return "sans"
    name, ext = os.path.splitext(os.path.basename(font))
    return name if name and ext.lower() in (".ttf", ".otf", ".ttc") \
        else "sans"


def _polyline_of(vertices, closed: bool, ocs):
    """A 2D polyline as one curve: straight between its vertices, and an
    arc where a vertex has a bulge, which is how a filleted corner is
    kept. `vertices` are (x, y, z, bulge) in the polyline's plane."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeWire
    pts = [v for i, v in enumerate(vertices)
           if i == 0 or math.dist(v[:2], vertices[i - 1][:2]) > 1e-12]
    if closed and len(pts) > 2 and math.dist(pts[0][:2], pts[-1][:2]) < 1e-12:
        pts.pop()
    if len(pts) < 2:
        return None
    if not any(abs(v[3]) > 1e-12 for v in pts):
        return geometry.make_polyline(
            [tuple(ocs.to_wcs(v[:3])) for v in pts], closed=closed)
    spans = list(zip(pts, pts[1:]))
    if closed:
        spans.append((pts[-1], pts[0]))
    wire = BRepBuilderAPI_MakeWire()
    for a, b in spans:
        start, end = tuple(ocs.to_wcs(a[:3])), tuple(ocs.to_wcs(b[:3]))
        if abs(a[3]) > 1e-12:
            # the bulge is the sagitta over half the chord, and a positive
            # one turns anticlockwise, so it bows out to the chord's right
            dx, dy = b[0] - a[0], b[1] - a[1]
            sag = a[3] / 2
            mid = (a[0] + dx / 2 + dy * sag, a[1] + dy / 2 - dx * sag, a[2])
            edge = geometry.make_arc_3pt(start, tuple(ocs.to_wcs(mid)), end)
        else:
            edge = geometry.make_line(start, end)
        for piece in geometry.edges_of(edge):
            wire.Add(piece)
    if not wire.IsDone():
        raise geometry.GeometryError("Polyline does not join up")
    return wire.Wire()


def _filled_of(e):
    """A SOLID or TRACE, a dimension's arrowhead most often, as a solid
    hatch over its three or four corners."""
    from ..core.hatch import HatchShape
    pts = []
    for p in e.wcs_vertices():
        p = tuple(float(v) for v in p)
        if not pts or np.linalg.norm(np.subtract(p, pts[-1])) > 1e-9:
            pts.append(p)
    if len(pts) > 2 and np.linalg.norm(np.subtract(pts[0], pts[-1])) < 1e-9:
        pts.pop()
    if len(pts) < 3:
        return None
    regions = geometry.planar_regions(
        [geometry.make_polyline(pts, closed=True)])
    return [HatchShape(region, "solid") for region in regions]


# --- text ---------------------------------------------------------------------

# MTEXT's attachment point, 1 to 9: top, middle and bottom rows, each left,
# centre and right. TEXT's (halign, valign) say the same in their own way.
_MTEXT_ANCHOR = {1: ("left", "top"), 2: ("center", "top"),
                 3: ("right", "top"), 4: ("left", "middle"),
                 5: ("center", "middle"), 6: ("right", "middle"),
                 7: ("left", "bottom"), 8: ("center", "bottom"),
                 9: ("right", "bottom")}
_TEXT_HALIGN = {0: "left", 1: "center", 2: "right", 3: "left", 4: "center",
                5: "left"}
_TEXT_VALIGN = {0: "baseline", 1: "bottom", 2: "middle", 3: "top"}


def _text_of(e):
    """A TEXT, MTEXT or ATTRIB as the app's editable text, placed, turned
    and stretched as the file has it, or None for one with nothing in it.

    The lettering is made at the origin and then moved so the point the
    file anchors it by lands on its insertion point: MTEXT's attachment
    point, TEXT's alignment. Its height is the file's: the height of a
    capital, as it is here. Wrapping at an MTEXT's width is not done, its
    own line breaks are.
    """
    from ..core.text_object import TextShape
    kind = e.dxftype()
    text = (e.plain_text(split=False) if kind == "MTEXT"
            else e.plain_text()).strip("\n")
    if not text.strip():
        return None
    font = _font_of(e)
    if kind == "MTEXT":
        height = float(e.dxf.char_height or 1.0)
        halign, valign = _MTEXT_ANCHOR.get(int(e.dxf.attachment_point or 1),
                                           ("left", "top"))
        normal = np.asarray(tuple(e.dxf.extrusion), float)
        turn = math.radians(e.get_rotation())
        at = np.asarray(tuple(e.dxf.insert), float)
        stretch = 1.0
        x_dir = None
    else:
        height = float(e.dxf.height or 1.0)
        halign = _TEXT_HALIGN.get(int(e.dxf.get("halign", 0)), "left")
        valign = _TEXT_VALIGN.get(int(e.dxf.get("valign", 0)), "baseline")
        normal = np.asarray(tuple(e.dxf.extrusion), float)
        turn = math.radians(float(e.dxf.get("rotation", 0.0)))
        anchored = (e.dxf.get("halign", 0) or e.dxf.get("valign", 0)) \
            and e.dxf.hasattr("align_point")
        ocs = e.ocs()
        at = np.asarray(tuple(ocs.to_wcs(
            e.dxf.align_point if anchored else e.dxf.insert)), float)
        stretch = float(e.dxf.get("width", 1.0) or 1.0)
        x_dir = np.asarray(tuple(ocs.to_wcs((math.cos(turn), math.sin(turn),
                                             0.0))), float)
        x_dir -= np.asarray(tuple(ocs.to_wcs((0.0, 0.0, 0.0))), float)
    try:
        lettering = TextShape(text, height, font, alignment=halign)
    except Exception:                                      # noqa: BLE001
        return None
    (x0, y0, _), (x1, y1, _) = geometry.bbox(lettering)
    dx = {"left": -x0, "center": -(x0 + x1) / 2, "right": -x1}[halign]
    dy = {"baseline": 0.0, "bottom": -y0, "middle": -(y0 + y1) / 2,
          "top": -y1}[valign]
    n = normal / (np.linalg.norm(normal) or 1.0)
    if x_dir is None:
        # MTEXT: turned about its normal from the normal's own x axis
        from ezdxf.math import OCS
        ocs = OCS(tuple(n))
        ux = np.asarray(tuple(ocs.ux), float)
        uy = np.asarray(tuple(ocs.uy), float)
        x_dir = math.cos(turn) * ux + math.sin(turn) * uy
    x_dir = x_dir / (np.linalg.norm(x_dir) or 1.0)
    y_dir = np.cross(n, x_dir)
    place = np.eye(4)
    place[:3, 0] = x_dir * stretch
    place[:3, 1] = y_dir
    place[:3, 2] = n
    place[:3, 3] = at
    shift = np.eye(4)
    shift[0, 3], shift[1, 3] = dx, dy
    return lettering.transformed(place @ shift)


def _font_of(e) -> str:
    """The font family a text is set in: its style's TrueType face, or the
    app's sans for a style set in one of AutoCAD's own SHX fonts."""
    try:
        style = e.doc.styles.get(e.dxf.get("style", "Standard"))
        font = str(style.dxf.font or "")
    except Exception:                                      # noqa: BLE001
        return "sans"
    name, ext = os.path.splitext(os.path.basename(font))
    if not name or ext.lower() not in (".ttf", ".otf", ".ttc"):
        return "sans"
    return name


# --- how an entity looks ------------------------------------------------------

# ACI 256 and 0: the colour is the layer's, or the block reference's
_BYLAYER_ACI, _BYBLOCK_ACI = 256, 0
# lineweights: the layer's, the block reference's, the drawing's default
_LW_BYLAYER, _LW_BYBLOCK, _LW_DEFAULT = -1, -2, -3


@dataclass(frozen=True)
class _Look:
    """What a DXF entity is drawn with, as the scene keeps it: its layer's
    name, and its own colour (r, g, b), print width in mm and linetype
    name, each None where it is the layer's."""
    layer: str
    color: tuple | None = None
    width: float | None = None
    linetype: str | None = None


class _Looks:
    """The file's layers made in the scene, and each entity's look."""

    def __init__(self, doc, scene):
        self.doc = doc
        self.scene = scene
        self.factor = 1.0                  # the file's unit, in the scene's
        self._ids: dict = {}

    def layer_id(self, name: str):
        """The scene layer a DXF layer is, made the first time it is asked
        for with the file's colour, lineweight, linetype and switches.
        Layer 0 is the scene's default layer, as it always was."""
        if name in ("0", ""):
            return None
        if name in self._ids:
            return self._ids[name]
        layers = self.scene.layers
        found = layers.find_by_name(name)
        if found is None:
            dxf_layer = self.doc.layers.get(name) \
                if self.doc.layers.has_entry(name) else None
            color = _layer_rgb(dxf_layer) if dxf_layer is not None else None
            found = layers.create(name, color) if color is not None \
                else layers.create(name)
            if dxf_layer is not None:
                lw = int(dxf_layer.dxf.get("lineweight", _LW_DEFAULT))
                if lw >= 0:
                    layers.set_print_width(found.id, lw / 100.0)
                kind = _linetype(dxf_layer.dxf.get("linetype", "Continuous"))
                if kind:
                    layers.set_linetype(found.id, kind)
                if dxf_layer.is_off() or dxf_layer.is_frozen():
                    layers.set_visible(found.id, False)
                if dxf_layer.is_locked():
                    layers.set_locked(found.id, True)
        self._ids[name] = found.id
        return found.id

    def layer_rgb(self, name: str):
        if self.doc.layers.has_entry(name):
            return _layer_rgb(self.doc.layers.get(name))
        return None

    def of(self, entity, parent: _Look | None = None) -> _Look:
        """An entity's look, a block's piece taking what it leaves to the
        block from `parent`, the look of the reference that placed it."""
        layer = str(entity.dxf.get("layer", "0") or "0")
        if parent is not None and layer == "0":
            layer = parent.layer           # a block's layer 0 is the insert's
        return _Look(layer, self._color(entity, parent),
                     self._width(entity, parent),
                     self._linetype(entity, parent))

    def _color(self, entity, parent):
        rgb = entity.rgb if entity.dxf.hasattr("true_color") else None
        if rgb is not None:
            return tuple(c / 255.0 for c in rgb)
        aci = int(entity.dxf.get("color", _BYLAYER_ACI))
        if aci == _BYLAYER_ACI:
            return None
        if aci == _BYBLOCK_ACI:
            if parent is None:
                return None
            # the reference's own colour, or else its layer's
            return parent.color if parent.color is not None \
                else self.layer_rgb(parent.layer)
        return _aci_rgb(aci)

    @staticmethod
    def _width(entity, parent):
        lw = int(entity.dxf.get("lineweight", _LW_BYLAYER))
        if lw == _LW_BYLAYER:
            return None
        if lw == _LW_BYBLOCK:
            return None if parent is None else parent.width
        if lw == _LW_DEFAULT:
            return 0.0                     # the printer's, as Rhino's 0
        return lw / 100.0

    @staticmethod
    def _linetype(entity, parent):
        name = str(entity.dxf.get("linetype", "BYLAYER") or "BYLAYER")
        if name.upper() == "BYLAYER":
            return None
        if name.upper() == "BYBLOCK":
            return None if parent is None else parent.linetype
        return _linetype(name) or "Continuous"


def _exploded(insert, look: _Look, looks: _Looks, depth: int = 0):
    """(entity, look) for every piece a block reference places, in the
    world, nested references opened up in turn, each piece taking what it
    leaves to the block from the reference that placed it."""
    if depth > 16:                         # a block that holds itself
        return
    if insert.dxftype() in _DIMENSIONS and \
            insert.get_geometry_block() is None:
        try:                               # one written without its drawing
            insert.render()
        except Exception:                                  # noqa: BLE001
            return
    try:
        pieces = list(insert.virtual_entities())
    except Exception:                                      # noqa: BLE001
        return
    for piece in pieces:
        piece_look = looks.of(piece, look)
        if piece.dxftype() == "INSERT" or (piece.dxftype() in _DIMENSIONS
                                           and not _is_linear(piece)):
            yield from _exploded(piece, piece_look, looks, depth + 1)
        else:
            yield piece, piece_look
    # a reference's attributes, its tag values, are its own text, already
    # where the reference put them
    for attrib in getattr(insert, "attribs", ()):
        if not attrib.is_invisible:
            yield attrib, looks.of(attrib, look)


def _unit_factor(doc, units: str, notes: list | None) -> float:
    """How many of the scene's units one of the file's is: 1 for a file
    that does not say ($INSUNITS 0), which is taken to be in the scene's."""
    from ..utils.units import converted_note
    source = int(doc.header.get("$INSUNITS", 0) or 0)
    if not source or units not in _INSUNITS:
        return 1.0
    try:
        factor = float(ezdxf_units.conversion_factor(source, _INSUNITS[units]))
    except Exception:                                      # noqa: BLE001
        return 1.0
    if not math.isfinite(factor) or factor <= 0 or \
            math.isclose(factor, 1.0, rel_tol=1e-12):
        return 1.0
    if notes is not None:
        name = {v: k for k, v in _INSUNITS.items()}.get(
            source, ezdxf_units.unit_name(source))
        notes.append(converted_note(name, units))
    return factor


def _layer_rgb(dxf_layer):
    """A DXF layer's colour as (r, g, b) in 0..1."""
    rgb = dxf_layer.rgb
    if rgb is not None:
        return tuple(c / 255.0 for c in rgb)
    return _aci_rgb(abs(int(dxf_layer.dxf.get("color", 7))) or 7)


def _aci_rgb(aci: int):
    from ezdxf.colors import aci2rgb
    return tuple(c / 255.0 for c in aci2rgb(int(aci)))


def _hex(rgb) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}"
                         for c in rgb[:3])


def _hatch_background(entity):
    """A hatch's background colour, AutoCAD's HATCHBACKGROUNDCOLOR, as
    (r, g, b) in 0..1, or None for none."""
    try:
        rgb = entity.bgcolor
    except AttributeError:
        return None
    return None if rgb is None else tuple(c / 255.0 for c in rgb)


# DXF linetypes by what their names say, in the languages AutoCAD ships
# in: VERDECKT is hidden, MITTE center, STRICHPUNKT dash-dot.
_LINETYPE_WORDS = (
    (("CONTINUOUS", "DURCHGEHEND", "SOLID"), "Continuous"),
    (("HIDDEN", "VERDECKT", "CACHE"), "Hidden"),
    (("CENTER", "CENTRE", "MITTE", "AXE"), "Center"),
    (("PHANTOM", "PHANTOM"), "Phantom"),
    (("BORDER", "GRENZE"), "Border"),
    (("DASHDOT", "DASH_DOT", "STRICHPUNKT", "DASHDOTDOT"), "DashDot"),
    (("DOT", "PUNKT"), "Dotted"),
    (("DASH", "STRICH", "TIRET"), "Dashed"),
)


def _linetype(name) -> str | None:
    """The app's linetype a DXF linetype name means, or None for one it
    cannot tell, which then draws as its layer's."""
    from ..core.linetype import LINETYPES
    text = str(name or "").strip()
    for known in LINETYPES:
        if known.lower() == text.lower():
            return known
    upper = text.upper().replace(" ", "")
    for words, known in _LINETYPE_WORDS:
        if any(word in upper for word in words):
            return known
    return None


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
