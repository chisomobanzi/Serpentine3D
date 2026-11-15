"""A Rhino file's layout pages as sheets.

Rhino keeps a layout's title block, notes, dimensions and detail viewports
in page space, in paper units, and our import used to drop all of it into
the model at paper coordinates. Each page with something on it comes in
here as a `Layout` instead: its curves as paper linework, its text as
notes, its leaders, hatches and linear dimensions as their sheet kinds,
and its details as detail views looking where Rhino's do.

rhino3dm 8 does not wrap a detail viewport (it reads as a bare
GeometryBase), nor say which detail a page dimension measures through.
Both are in the object's own encoding, and both are read from there: a
detail's camera is the viewport chunk inside it, handed back to rhino3dm
to decode, and a page dimension carries the detail's id and then its scale.
"""
from __future__ import annotations

import base64
import math
import re
import struct
import uuid

import numpy as np
import rhino3dm as r3

from ..core import geometry
from ..core.layout import (DetailView, HATCH_PATTERNS, Hatch, Layout, Leader,
                           LinearDim, PaperObject, TextNote)
from ..utils.units import TO_MM

# openNURBS chunk codes (opennurbs_3dm.h)
_SHORT, _CRC = 0x80000000, 0x8000
_SETTINGS_TABLE, _OBJECT_TABLE = 0x10000015, 0x10000013
_VIEW_LIST, _VIEW_RECORD = 0x20008037, 0x2000803B
_VIEW_ATTRIBUTES = 0x20008C3B
# TCODE_VIEW_VIEWPORT: the camera chunk inside an ON_3dmView, and inside a
# detail's encoding
_VIEWPORT_CHUNK = 0x2000823B
_CLASS_CHUNK = 0x2FFFC
_PAGE_VIEW = 1                     # ON::view_type::page_view_type

# Paper a page is put on: the smallest of these, either way up, that holds
# what is on it (Rhino keeps the page size where rhino3dm cannot read it).
PAPER_SIZES = (
    ("A4", 210.0, 297.0), ("Letter", 215.9, 279.4), ("Legal", 215.9, 355.6),
    ("A3", 297.0, 420.0), ("Tabloid", 279.4, 431.8), ("A2", 420.0, 594.0),
    ("ANSI C", 431.8, 558.8), ("A1", 594.0, 841.0), ("ANSI D", 558.8, 863.6),
    ("A0", 841.0, 1189.0), ("ANSI E", 863.6, 1117.6))
_FITS_WITHIN = 1.0              # mm a page's content may run past its paper

# line pitch of a sheet note, in heights (see layout.annotation_bounds)
_NOTE_LINE_PITCH = 1.6


def detail_viewport(geo, template):
    """A Rhino detail's camera as a rhino3dm ViewportInfo, or None.

    The detail's viewport chunk is put in place of another viewport's own
    and the result decoded, so rhino3dm reads it exactly as it reads any
    view. `template` is any viewport from the same file."""
    try:
        data = base64.b64decode(geo.Encode()["data"])
        enc = template.Encode()
        tdata = base64.b64decode(enc["data"])
    except Exception:                                           # noqa: BLE001
        return None
    for i in range(56, len(data) - 12):
        code, size = struct.unpack_from("<IQ", data, i)
        if code != _VIEWPORT_CHUNK or i + 12 + size > len(data):
            continue
        body = data[i + 12:i + 12 + size]
        tsize = struct.unpack_from("<Q", tdata, 48)[0]
        head = bytearray(tdata[:44])
        struct.pack_into("<Q", head, 4, 32 + 12 + size + 12)
        spliced = (bytes(head) + struct.pack("<IQ", _CLASS_CHUNK, size)
                   + body + tdata[56 + tsize:])
        try:
            return r3.ViewportInfo.Decode(
                dict(enc, data=base64.b64encode(spliced).decode()))
        except Exception:                                       # noqa: BLE001
            return None
    return None


def measured_through(data: bytes, details: dict):
    """(our detail id, scale) for a page dimension Rhino measured through
    a detail, from the object's encoded bytes: the detail's id, as a GUID
    in Rhino's byte order, followed by its scale. None for one measured on
    the paper itself. `details` maps Rhino detail ids to ours."""
    for rhino_id, ours in details.items():
        key = uuid.UUID(rhino_id).bytes_le
        at = data.find(key)
        if at >= 0 and at + 24 <= len(data):
            scale = struct.unpack_from("<d", data, at + 16)[0]
            if math.isfinite(scale) and scale > 0:
                return ours, scale
    return None


def page_sizes(path: str) -> dict:
    """{viewport id bytes: (width, height)} in mm for each layout page, as
    the file's view settings keep them. rhino3dm does not offer a page's
    size, and what lies on a page says little about it: notes are parked
    off the paper. The settings table comes before any object in a .3dm,
    so only that much of the file is read. Empty for a file older than
    version 5 or one this cannot follow."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if not head.startswith(b"3D Geometry File Format ") or \
                    int(head[24:32]) < 5:
                return {}
            while True:
                hdr = f.read(12)
                if len(hdr) < 12:
                    return {}
                code, value = struct.unpack("<IQ", hdr)
                if code == _SETTINGS_TABLE:
                    settings = f.read(value)
                    break
                if code == _OBJECT_TABLE:
                    return {}
                if not code & _SHORT:
                    f.seek(value, 1)
    except (OSError, ValueError, struct.error):
        return {}
    sizes = {}
    for code, body in _chunks(settings, 0):
        if code != _VIEW_LIST or body is None:
            continue
        for rcode, record in _chunks(body, 4):
            if rcode != _VIEW_RECORD or record is None:
                continue
            viewport = attrs = None
            for scode, sub in _chunks(record, 0):
                if scode == _VIEWPORT_CHUNK:
                    viewport = sub
                elif scode == _VIEW_ATTRIBUTES:
                    attrs = sub
            if viewport is None or attrs is None or len(attrs) < 21:
                continue
            kind, width, height = struct.unpack_from("<idd", attrs, 1)
            if kind == _PAGE_VIEW and width > 0 and height > 0:
                sizes[bytes(viewport)] = (width, height)
    return sizes


def _chunks(data: bytes, start: int):
    """(code, body) for each chunk in `data` from `start`; a short chunk's
    body is None, and a CRC'd one's has its CRC taken off."""
    i = start
    while i + 12 <= len(data):
        code, value = struct.unpack_from("<IQ", data, i)
        if code & _SHORT:
            yield code, None
            i += 12
            continue
        if i + 12 + value > len(data):
            return
        body = data[i + 12:i + 12 + value]
        yield code, (body[:-4] if code & _CRC else body)
        i += 12 + value


_FIELD = re.compile(
    r'%<\s*(\w+)\s*(?:\(\s*(?:"([^"]*)")?[^)]*\))?\s*>%')


def fill_fields(text: str, page: str, doc_text: dict) -> str:
    """`text` with the Rhino text fields a title block uses worked out:
    %<PageName()>% as the page's name and %<DocumentText("key")>% from the
    file's document user text, names and keys matched whatever their case,
    as Rhino matches them. Anything else is left as written."""
    keys = {k.lower(): v for k, v in doc_text.items()}

    def worked_out(match):
        name, arg = match.group(1).lower(), match.group(2)
        if name == "pagename":
            return page
        if name == "documenttext" and arg is not None \
                and arg.lower() in keys:
            return keys[arg.lower()]
        return match.group(0)
    return _FIELD.sub(worked_out, text)


def _document_text(model) -> dict:
    out = {}
    try:
        for i in range(len(model.Strings)):
            key, value = model.Strings[i]
            out[str(key)] = str(value)
    except Exception:                                           # noqa: BLE001
        pass
    return out


def _size_of(view, sizes: dict):
    key = uuid.UUID(str(view.Viewport.Id)).bytes_le
    return next((size for body, size in sizes.items() if key in body), None)


def read_pages(model, units: str = "mm", path: str | None = None) -> list:
    """The file's layout pages as sheets, in the order Rhino lists them.

    Paper is in millimetres whatever the page units; what a detail shows,
    and what a dimension through one measures, is in the scene's `units`.
    `path` is the file `model` was read from, for its pages' sizes."""
    from . import rhino

    page_mm = _to_mm(model.Settings.PageUnitSystem)
    model_to_scene = _to_mm(model.Settings.ModelUnitSystem) / TO_MM.get(
        units, 1.0)
    views = [v for v in model.Views]
    if not views:
        return []
    template = views[0].Viewport
    by_page: dict = {}
    for obj in model.Objects:
        attrs = obj.Attributes
        if attrs.IsInstanceDefinitionObject or not rhino.on_a_page(attrs):
            continue
        by_page.setdefault(str(attrs.ViewportId), []).append(obj)
    if not by_page:
        return []

    layers = rhino.read_layers(model)
    materials = rhino.read_materials(model)
    blocks = rhino.read_blocks(model)
    styles = {str(s.Id): s for s in model.DimStyles}
    patterns = rhino._HATCH_PATTERNS
    reader = _PageReader(page_mm, model_to_scene, styles, patterns, template,
                         _document_text(model))
    sizes = page_sizes(path) if path else {}

    # every detail first: a dimension on one page can measure through it
    sheets = []
    for view in views:
        objs = by_page.get(str(view.Viewport.Id))
        if not objs:
            continue
        sheet = Layout(name=view.Name or "Layout")
        reader.page = sheet.name
        for obj in objs:
            if type(obj.Geometry).__name__ == "GeometryBase":
                meta = rhino.object_appearance(obj.Attributes, layers,
                                               materials)
                if _shown(meta):
                    reader.detail(sheet, obj)
        sheets.append((sheet, objs, _size_of(view, sizes)))
    for sheet, objs, size in sheets:
        reader.page = sheet.name
        for obj in objs:
            geo = obj.Geometry
            if type(geo).__name__ == "GeometryBase":
                continue
            meta = rhino.object_appearance(obj.Attributes, layers, materials)
            if not _shown(meta):
                continue
            if isinstance(geo, r3.InstanceReference):
                for member, attrs, matrix, _text in rhino.flatten_instance(
                        geo, blocks):
                    inner = rhino.object_appearance(attrs, layers, materials,
                                                    parent=meta)
                    if _shown(inner):
                        placed = member.Duplicate()
                        placed.Transform(_xform(matrix))
                        reader.content(sheet, placed, inner)
                continue
            reader.content(sheet, geo, meta)
        sheet.paper_w, sheet.paper_h = size or _paper_for(sheet)
    return [sheet for sheet, _objs, _size in sheets]


def _to_mm(unit_system) -> float:
    from .rhino import _OUR_UNITS
    name = str(unit_system).rsplit(".", 1)[-1]
    return TO_MM.get(_OUR_UNITS.get(name, "mm"), 1.0)


def _shown(meta) -> bool:
    return meta.get("visible", True) and meta.get("layer_visible", True)


def _xform(matrix):
    t = r3.Transform(1.0)
    for i in range(4):
        for j in range(4):
            setattr(t, f"M{i}{j}", float(matrix[i][j]))
    return t


class _PageReader:
    """Turns one page object at a time into what a sheet holds."""

    def __init__(self, page_mm, model_to_scene, styles, patterns, template,
                 doc_text=None):
        self.mm = page_mm
        self.doc_text = doc_text or {}
        self.page = ""
        self.model_to_scene = model_to_scene
        self.styles = styles
        self.patterns = patterns
        self.template = template
        self.details: dict = {}          # Rhino detail id -> our detail id

    # -- details ----------------------------------------------------------

    def detail(self, sheet, obj):
        geo = obj.Geometry
        vp = detail_viewport(geo, self.template)
        if vp is None:
            return
        box = geo.GetBoundingBox()
        x, y = box.Min.X * self.mm, box.Min.Y * self.mm
        w = (box.Max.X - box.Min.X) * self.mm
        h = (box.Max.Y - box.Min.Y) * self.mm
        if w <= 0 or h <= 0:
            return
        f = vp.GetFrustum()
        ux, uy = _vec(vp.CameraX), _vec(vp.CameraY)
        d = _unit(_vec(vp.CameraDirection))
        target = _vec(vp.TargetPoint) + ux * (f["left"] + f["right"]) / 2 \
            + uy * (f["bottom"] + f["top"]) / 2
        width = f["right"] - f["left"]
        if vp.IsPerspectiveProjection and f["near"] > 0:
            width *= float(vp.TargetDistance(True)) / f["near"]
        azimuth, elevation = _view_angles(d, _vec(vp.CameraUp))
        det = DetailView(
            x=x, y=y, w=w, h=h, azimuth=azimuth, elevation=elevation,
            target=[float(v) * self.model_to_scene for v in target],
            perspective=bool(vp.IsPerspectiveProjection),
            scale_denom=width * self.model_to_scene / w)
        sheet.details.append(det)
        self.details[str(obj.Attributes.Id)] = det.id

    # -- everything else --------------------------------------------------

    def content(self, sheet, geo, meta):
        if isinstance(geo, r3.Text):
            self.text(sheet, geo)
        elif isinstance(geo, r3.Leader):
            self.leader(sheet, geo)
        elif isinstance(geo, r3.Dimension):
            self.dimension(sheet, geo)
        elif isinstance(geo, r3.Hatch):
            self.hatch(sheet, geo, meta)
        elif isinstance(geo, r3.Curve):
            self.curve(sheet, geo, meta)

    def _height(self, geo, default=2.5) -> float:
        style = self.styles.get(str(getattr(geo, "DimensionStyleId", "")))
        height = float(style.TextHeight) if style is not None else default
        return (height if height > 0 else default) * self.mm

    def _font(self, geo) -> str:
        style = self.styles.get(str(getattr(geo, "DimensionStyleId", "")))
        try:
            return str(style.Font.FamilyName or "")
        except Exception:                                       # noqa: BLE001
            return ""

    def _said(self, geo) -> str:
        return fill_fields(_plain(geo.PlainText), self.page, self.doc_text)

    def text(self, sheet, geo):
        said = self._said(geo)
        if not said.strip():
            return
        height = self._height(geo)
        at = geo.Plane.Origin
        # Rhino hangs text from the bottom of its last line; a note from
        # the baseline of its first
        lines = said.count("\n")
        sheet.notes.append(TextNote(
            x=at.X * self.mm, y=at.Y * self.mm + lines * height
            * _NOTE_LINE_PITCH, text=said, height=height,
            font_family=self._font(geo)))

    def leader(self, sheet, geo):
        points = [[p.X * self.mm, p.Y * self.mm] for p in geo.Points]
        if len(points) < 2:
            return
        sheet.leaders.append(Leader(points=points, text=self._said(geo),
                                    height=self._height(geo, 3.5)))

    def dimension(self, sheet, geo):
        from . import rhino
        kind = str(geo.AnnotationType).rsplit(".", 1)[-1]
        if kind not in ("Rotated", "Aligned"):
            return
        found = rhino._linear_points(geo)
        if found is None:
            return
        (x2, _y2), (xl, yl) = found
        plane = geo.Plane
        o = _vec(plane.Origin)[:2]
        ux, uy = _vec(plane.XAxis)[:2], _vec(plane.YAxis)[:2]
        p1 = o * self.mm
        # measured along the plane's x, where Rhino measures it
        p2 = (o + ux * x2) * self.mm
        line = (o + ux * xl + uy * yl) * self.mm
        along = p2 - p1
        if not np.linalg.norm(along):
            return
        along = along / np.linalg.norm(along)
        offset = float(np.dot(line - p1, (-along[1], along[0])))
        through = measured_through(base64.b64decode(geo.Encode()["data"]),
                                   self.details)
        dim = LinearDim(x1=float(p1[0]), y1=float(p1[1]),
                        x2=float(p2[0]), y2=float(p2[1]), offset=offset,
                        text=_plain(geo.PlainText))
        if through is None:
            dim.measures_paper = True
        else:
            dim.scale_denom = through[1] * self.model_to_scene / self.mm
        sheet.dims.append(dim)

    def hatch(self, sheet, geo, meta):
        from . import rhino
        for shape in rhino.hatch_to_shapes(geo, self.patterns):
            for face in geometry.faces_of(shape.region):
                rings = _rings(face, self.mm)
                if not rings or len(rings[0]) < 3:
                    continue
                name = shape.pattern.lower()
                pattern = ("solid" if shape.solid else name
                           if name in HATCH_PATTERNS else "lines")
                sheet.hatches.append(Hatch(
                    points=rings[0], holes=rings[1:], pattern=pattern,
                    angle=float(shape.angle),
                    spacing=max(float(shape.spacing) * self.mm, 0.2),
                    color=_colour_list(meta)))

    def curve(self, sheet, geo, meta):
        from . import rhino
        try:
            shapes = rhino.object_to_shapes(geo)
        except Exception:                                       # noqa: BLE001
            return
        size = np.diag([self.mm, self.mm, self.mm, 1.0])
        for shape in shapes:
            if shape is None or shape.IsNull():
                continue
            if self.mm != 1.0:
                shape = geometry.apply_matrix(shape, size)
            sheet.objects.append(PaperObject(
                shape=shape, color=_colour(meta),
                lineweight=_lineweight(meta)))


def _vec(p) -> np.ndarray:
    return np.array([p.X, p.Y, p.Z], float)


def _unit(v):
    n = float(np.linalg.norm(v))
    return v / n if n else v


def _view_angles(direction, up) -> tuple:
    """(azimuth, elevation) of a camera looking along `direction`, as our
    views have them. Looking straight up or down, the azimuth is what puts
    Rhino's up at the top of the window."""
    elevation = math.asin(max(-1.0, min(1.0, -direction[2])))
    if abs(direction[2]) > 0.999:
        return (math.atan2(-up[1], -up[0]),
                math.copysign(math.radians(89.9), elevation))
    return math.atan2(-direction[1], -direction[0]), elevation


def _plain(text) -> str:
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def _colour(meta):
    c = meta.get("color") or meta.get("layer_color")
    return tuple(float(v) for v in c[:3]) if c else None


def _colour_list(meta):
    c = _colour(meta)
    return list(c) if c else None


def _lineweight(meta) -> float:
    for key in ("print_width", "layer_print_width"):
        value = meta.get(key)
        if value and value > 0:
            return float(value)
    return 0.25


def _rings(face, scale: float) -> list:
    """A face's boundary as [[x, y], ...] rings, the outer one first, each
    edge followed in the wire's order and its curved ones sampled."""
    from OCP.BRepTools import BRepTools, BRepTools_WireExplorer
    from OCP.GeomAbs import GeomAbs_Line
    from OCP.TopAbs import TopAbs_REVERSED, TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer

    from ..core import occ
    outer = BRepTools.OuterWire_s(face)
    wires = [outer]
    ex = TopExp_Explorer(face, TopAbs_WIRE)
    while ex.More():
        wire = occ.to_wire(ex.Current())
        if not wire.IsSame(outer):
            wires.append(wire)
        ex.Next()
    rings = []
    for wire in wires:
        pts = []
        walk = BRepTools_WireExplorer(wire)
        while walk.More():
            edge = walk.Current()
            curve = occ.edge_adaptor(edge)
            n = 2 if curve.GetType() == GeomAbs_Line else 17
            t0, t1 = curve.FirstParameter(), curve.LastParameter()
            ts = [t0 + (t1 - t0) * i / (n - 1) for i in range(n)]
            if edge.Orientation() == TopAbs_REVERSED:
                ts.reverse()
            for t in ts[:-1]:
                p = curve.Value(t)
                pts.append([p.X() * scale, p.Y() * scale])
            walk.Next()
        if len(pts) >= 3:
            rings.append(pts)
    return rings


def _paper_for(sheet) -> tuple:
    """(width, height) in mm: the smallest standard sheet, either way up,
    that holds the page's content from its origin; else the content's
    extent rounded up to the next centimetre."""
    xs, ys = [0.0], [0.0]
    for det in sheet.details:
        xs += [det.x, det.x + det.w]
        ys += [det.y, det.y + det.h]
    for obj in sheet.objects:
        try:
            (x0, y0, _z0), (x1, y1, _z1) = geometry.bbox(obj.shape)
        except Exception:                                       # noqa: BLE001
            continue
        xs += [x0, x1]
        ys += [y0, y1]
    for note in sheet.notes:
        xs.append(note.x)
        ys += [note.y, note.y + note.height]
    for item in sheet.leaders + sheet.hatches:
        for p in item.points:
            xs.append(p[0])
            ys.append(p[1])
    for dim in sheet.dims:
        xs += [dim.x1, dim.x2]
        ys += [dim.y1, dim.y2]
    low_x, low_y, high_x, high_y = min(xs), min(ys), max(xs), max(ys)
    if low_x >= -_FITS_WITHIN and low_y >= -_FITS_WITHIN:
        fits = [(w * h, w, h) for _name, a, b in PAPER_SIZES
                for w, h in ((a, b), (b, a))
                if w + _FITS_WITHIN >= high_x and h + _FITS_WITHIN >= high_y]
        if fits:
            _area, w, h = min(fits)
            return w, h
    return (math.ceil(max(high_x, 10.0) / 10.0) * 10.0,
            math.ceil(max(high_y, 10.0) / 10.0) * 10.0)
