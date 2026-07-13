"""SVG: import paths as curves; export layouts as vector SVG."""

from __future__ import annotations

from ..core import geometry


def import_svg(scene, path: str, scale: float = 1.0) -> int:
    """Import SVG paths/shapes as curves on the XY plane (y flipped so the
    drawing reads the right way up)."""
    import svgelements as se

    svg = se.SVG.parse(path)
    n = 0

    def add_curve(shape):
        nonlocal n
        try:
            scene.add(shape)
            n += 1
        except Exception:
            pass

    def pt(p):
        return (float(p.x) * scale, -float(p.y) * scale, 0.0)

    for element in svg.elements():
        if isinstance(element, se.Path):
            segs = []
            current = []          # polyline accumulation
            for seg in element.segments():
                if isinstance(seg, se.Move):
                    if len(current) >= 2:
                        segs.append(geometry.make_polyline(current))
                    current = [pt(seg.end)]
                elif isinstance(seg, se.Line):
                    if not current:
                        current = [pt(seg.start)]
                    current.append(pt(seg.end))
                elif isinstance(seg, (se.CubicBezier, se.QuadraticBezier,
                                      se.Arc)):
                    if len(current) >= 2:
                        segs.append(geometry.make_polyline(current))
                        current = []
                    if isinstance(seg, se.CubicBezier):
                        cps = [pt(seg.start), pt(seg.control1),
                               pt(seg.control2), pt(seg.end)]
                        segs.append(geometry.make_control_curve(
                            cps, degree=3))
                    elif isinstance(seg, se.QuadraticBezier):
                        cps = [pt(seg.start), pt(seg.control), pt(seg.end)]
                        segs.append(geometry.make_control_curve(
                            cps, degree=2))
                    else:
                        pts = [pt(seg.point(t / 24)) for t in range(25)]
                        segs.append(geometry.make_interp_curve(pts))
                elif isinstance(seg, se.Close):
                    if current and len(current) >= 2:
                        current.append(current[0])
                        segs.append(geometry.make_polyline(current))
                        current = []
            if len(current) >= 2:
                segs.append(geometry.make_polyline(current))
            if len(segs) == 1:
                add_curve(segs[0])
            elif segs:
                try:
                    add_curve(geometry.join_curves(segs))
                except geometry.GeometryError:
                    for s in segs:
                        add_curve(s)
        elif isinstance(element, se.Circle):
            add_curve(geometry.make_circle(
                (float(element.cx) * scale, -float(element.cy) * scale, 0),
                float(element.rx) * scale))
        elif isinstance(element, se.Rect):
            x, y = float(element.x) * scale, -float(element.y) * scale
            w, h = float(element.width) * scale, float(element.height) * scale
            add_curve(geometry.make_polyline(
                [(x, y, 0), (x + w, y, 0), (x + w, y - h, 0),
                 (x, y - h, 0)], closed=True))
    return n


def export_layout_svg(window, layout, path: str):
    """The composed sheet as an SVG (same renderer as the PDF export)."""
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QPainter
    from PySide6.QtSvg import QSvgGenerator
    from .pdf import _paint_layout

    gen = QSvgGenerator()
    gen.setFileName(path)
    k = 4.0                                  # device units per mm
    gen.setSize(QSize(int(layout.paper_w * k), int(layout.paper_h * k)))
    gen.setViewBox(0, 0, int(layout.paper_w * k), int(layout.paper_h * k))
    gen.setTitle(layout.name)
    painter = QPainter(gen)
    try:
        _paint_layout(painter, window, layout, k)
    finally:
        painter.end()
