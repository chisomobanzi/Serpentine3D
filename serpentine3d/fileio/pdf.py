"""Layout -> PDF export.

Technical/hidden/wireframe details export as true vector linework;
shaded details are rendered to an image via an offscreen framebuffer.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QSizeF, Qt
from PySide6.QtGui import (
    QColor, QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen,
    QPolygonF,
)

from ..core import linetype as _lt


def export_layout_pdf(window, layout, path: str):
    export_layouts_pdf(window, [layout], path)


def export_layouts_pdf(window, layouts: list, path: str):
    """One PDF with a page per layout (sizes may differ per page)."""
    if not layouts:
        raise ValueError("No layouts to export")
    writer = QPdfWriter(path)
    writer.setResolution(600)
    first = layouts[0]
    writer.setPageSize(QPageSize(QSizeF(first.paper_w, first.paper_h),
                                 QPageSize.Unit.Millimeter, name="",
                                 matchPolicy=QPageSize.SizeMatchPolicy.ExactMatch))
    painter = QPainter(writer)
    try:
        for i, lay in enumerate(layouts):
            if i > 0:
                writer.setPageSize(QPageSize(
                    QSizeF(lay.paper_w, lay.paper_h),
                    QPageSize.Unit.Millimeter, name="",
                    matchPolicy=QPageSize.SizeMatchPolicy.ExactMatch))
                writer.newPage()
            _paint_layout(painter, window, lay,
                          writer.resolution() / 25.4)
    finally:
        painter.end()


def _paint_layout(painter: QPainter, window, layout, k: float):
    """k = device dots per millimetre. Paper y-up -> device y-down."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    def pt(x, y):
        return (x * k, (layout.paper_h - y) * k)

    lv = window.viewport.layout_view

    for detail in layout.details:
        if detail.display_mode in ("shaded", "ghosted"):
            _paint_detail_raster(painter, window, detail, layout, k)
        else:
            _paint_detail_vector(painter, lv, detail, layout, k)
        if detail.show_border:
            painter.setPen(QPen(QColor(60, 65, 75), 0.25 * k))
            x0, y0 = pt(detail.x, detail.y + detail.h)
            painter.drawRect(int(x0), int(y0),
                             int(detail.w * k), int(detail.h * k))
        if detail.show_label:
            painter.setPen(QPen(QColor(90, 95, 105)))
            font = QFont("sans")
            font.setPixelSize(int(2.6 * k))
            painter.setFont(font)
            lx, ly = pt(detail.x + 1.5, detail.y + 1.5)
            painter.drawText(int(lx), int(ly), detail.scale_text())

    _paint_paper_objects(painter, layout, k, pt)

    from ..ui import annot_paint
    scene = window.scene
    idx = 1
    for i, l in enumerate(scene.layouts):
        if l.id == layout.id:
            idx = i + 1
    annot_paint.draw_all(painter, pt, k, layout, scene, sheet_index=idx,
                         sheet_count=max(len(scene.layouts), 1))


def _paint_paper_objects(painter, layout, k, pt):
    """Geometry drawn on the paper itself, in millimetres.

    Over the details, the way it is on screen: a border or a bubble drawn on top
    of a view is meant to be seen. Its lineweight is millimetres on the printed
    sheet, which is exactly what this is printing, so it needs no adjusting.
    """
    for obj in layout.objects:
        width = max(obj.lineweight, 0.01) * k
        pen = QPen(QColor(*[int(c * 255) for c in obj.color])
                   if obj.color else QColor(15, 15, 18), width)
        # Qt dash units are multiples of the pen width, so a paper-mm pattern
        # has to be divided by the weight it is drawn at
        pattern = _lt.pattern_for(obj.linetype)
        if pattern:
            pen.setDashPattern([max(v, 0.01) / max(obj.lineweight, 0.01)
                                for v in pattern])
        painter.setPen(pen)
        for poly in obj.polylines:
            painter.drawPolyline(QPolygonF(
                [QPointF(*pt(p[0], p[1])) for p in poly]))


def _paint_detail_vector(painter, layout_view, detail, layout, k):
    data = layout_view._detail_hlr(detail)
    cx = detail.x + detail.w / 2
    cy = detail.y + detail.h / 2
    s = 1.0 / detail.scale_denom

    painter.save()
    painter.setClipRect(int(detail.x * k),
                        int((layout.paper_h - detail.y - detail.h) * k),
                        int(detail.w * k), int(detail.h * k))

    def draw_polys(polys, pen):
        painter.setPen(pen)
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPolygonF
        for poly in polys:
            qpoly = QPolygonF()
            for p in poly:
                x = (cx + p[0] * s) * k
                y = (layout.paper_h - (cy + p[1] * s)) * k
                qpoly.append(QPointF(x, y))
            painter.drawPolyline(qpoly)

    if detail.display_mode == "hidden":
        pen_h = QPen(QColor(110, 110, 120), 0.18 * k)
        pen_h.setDashPattern([4.0, 2.5])
        draw_polys(data["hidden"], pen_h)
    # Visible edges plot at their layer's print width; a layer left at the
    # device default plots the thin default line the detail has always used.
    # Ink stays near-black: a plot is black-on-white whatever the screen shows.
    # Qt dash units are multiples of pen width, so a paper-mm dash pattern is
    # divided by the width the pen is actually drawn at.
    from ..core import linetype as _lt
    groups = data.get("visible_groups")
    if groups is None:
        groups = [(0.0, "Continuous", data["visible"])] + \
                 [(0.0, n, p) for n, p in data.get("visible_lt", [])]
    for width_mm, name, polys in groups:
        mm = width_mm if width_mm > 0 else 0.3
        pen = QPen(QColor(15, 15, 18), mm * k)
        pattern = _lt.pattern_for(name)
        if pattern:
            pen.setDashPattern([max(v, 0.01) / mm for v in pattern])
        draw_polys(polys, pen)
    regions = data.get("cut") or []
    if regions:
        # The same answer the screen draws, so a bore that is open on
        # screen is open on paper.
        from ..core.layout import cut_hatching, cut_patterns
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QPolygonF
        fill, loops, solid = cut_hatching(regions, cx, cy, s,
                                          patterns=cut_patterns(data))
        painter.setPen(QPen(QColor(60, 62, 70), 0.15 * k))
        for a, b in fill:
            painter.drawLine(
                QPointF(a[0] * k, (layout.paper_h - a[1]) * k),
                QPointF(b[0] * k, (layout.paper_h - b[1]) * k))
        painter.setPen(QPen(QColor(10, 10, 12), 0.5 * k))
        for loop in loops:
            ring = list(loop) + [loop[0]]     # closed, or one side is missing
            painter.drawPolyline(QPolygonF(
                [QPointF(x * k, (layout.paper_h - y) * k) for x, y in ring]))
        # Over the outline, the way the hatching goes over it: what is
        # poched on a section is drawn behind its own edges.
        from ..ui import annot_paint
        annot_paint.fill_cut_solid(
            painter, lambda x, y: (x * k, (layout.paper_h - y) * k), solid)
    painter.restore()


def _paint_detail_raster(painter, window, detail, layout, k):
    px_w = max(int(detail.w * 12), 64)      # ~300 dpi
    px_h = max(int(detail.h * 12), 64)
    img = window.viewport.render_detail_image(detail, px_w, px_h)
    if img is None:
        return
    from PySide6.QtCore import QRectF
    target = QRectF(detail.x * k,
                    (layout.paper_h - detail.y - detail.h) * k,
                    detail.w * k, detail.h * k)
    painter.drawImage(target, img)


def _paint_dim(painter, dim, layout, k, pt, scene=None):
    a = np.array([dim.x1, dim.y1])
    b = np.array([dim.x2, dim.y2])
    d = b - a
    length = np.linalg.norm(d)
    if length < 1e-9:
        return
    d = d / length
    n = np.array([-d[1], d[0]])
    ao, bo = a + n * dim.offset, b + n * dim.offset
    pen = QPen(QColor(45, 70, 130), 0.18 * k)
    painter.setPen(pen)
    from PySide6.QtCore import QPointF

    def line(p, q):
        painter.drawLine(QPointF(*pt(p[0], p[1])), QPointF(*pt(q[0], q[1])))

    line(a, ao + n * 2)
    line(b, bo + n * 2)
    line(ao, bo)
    for tip, direction in ((ao, d), (bo, -d)):
        w = direction * 2.2
        perp = n * 0.7
        line(tip, tip + w + perp)
        line(tip, tip + w - perp)
    mid = (a + b) / 2 + n * (dim.offset + 2.0)
    measured = length * dim.scale_denom
    text = dim.text or (scene.format_length(measured) if scene
                        else f"{measured:g}")
    font = QFont("sans")
    font.setPixelSize(int(3.2 * k))
    painter.setFont(font)
    tx, ty = pt(mid[0], mid[1])
    painter.drawText(int(tx) - int(6 * k / 3.2), int(ty), text)
