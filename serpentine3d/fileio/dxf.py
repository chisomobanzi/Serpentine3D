"""DXF import/export via ezdxf.

Model export: curves as splines/polylines, surfaces/solids as MESH
entities, layers with true colours. Layout export: the drawn sheet
(HLR linework + annotations) at paper millimetre coordinates.
"""

from __future__ import annotations

import math

import ezdxf
import numpy as np

from ..core import geometry
from ..core.tessellate import tessellate


def _true_color(rgb) -> int:
    r, g, b = (int(c * 255) for c in rgb)
    return (r << 16) | (g << 8) | b


def export_dxf(scene, path: str, only_ids: list | None = None):
    doc = ezdxf.new("R2010")
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
                c = tuple(e.dxf.center)
                major = np.asarray(tuple(e.dxf.major_axis))
                r1 = float(np.linalg.norm(major))
                r2 = r1 * e.dxf.ratio
                shape = geometry.make_ellipse(c, r1, r2)
        except geometry.GeometryError:
            continue
        if shape is not None:
            scene.add(shape, layer_id=layer_for(e))
            n += 1
    return n


def export_layout_dxf(window, layout, path: str):
    """The composed sheet as 2D DXF at paper-mm coordinates."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    doc.layers.add("VISIBLE")
    doc.layers.add("HIDDEN")
    hidden_lt = "DASHED"
    if hidden_lt not in doc.linetypes:
        doc.linetypes.add(hidden_lt, pattern=[2.5, 1.5, -1.0])
    doc.layers.get("HIDDEN").dxf.linetype = hidden_lt
    doc.layers.add("ANNOT")

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

        for poly in data["visible"]:
            msp.add_lwpolyline(to_paper(poly),
                               dxfattribs={"layer": "VISIBLE"})
        if detail.display_mode == "hidden":
            for poly in data["hidden"]:
                msp.add_lwpolyline(to_paper(poly),
                                   dxfattribs={"layer": "HIDDEN"})
        msp.add_lwpolyline(
            [(detail.x, detail.y), (detail.x + detail.w, detail.y),
             (detail.x + detail.w, detail.y + detail.h),
             (detail.x, detail.y + detail.h)],
            close=True, dxfattribs={"layer": "ANNOT"})

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
        measured = length * dim.scale_denom
        text = dim.text or window.scene.format_length(measured)
        mid = (a + b) / 2 + nvec * (dim.offset + 2)
        msp.add_text(text, height=3.2, dxfattribs={
            "layer": "ANNOT"}).set_placement((mid[0], mid[1]))
    doc.saveas(path)
