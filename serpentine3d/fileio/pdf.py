"""Layout -> PDF export.

Technical/hidden/wireframe details export as true vector linework;
shaded details are rendered to an image via an offscreen framebuffer.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QSizeF, Qt
from PySide6.QtGui import (
    QColor, QFont, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen,
)


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

    from ..ui import annot_paint
    scene = window.scene
    idx = 1
    for i, l in enumerate(scene.layouts):
        if l.id == layout.id:
            idx = i + 1
    annot_paint.draw_all(painter, pt, k, layout, scene, sheet_index=idx,
                         sheet_count=max(len(scene.layouts), 1))


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
    draw_polys(data["visible"], QPen(QColor(15, 15, 18), 0.3 * k))
    cut = data.get("cut") or []
    if cut:
        from ..core.layout import hatch_lines
        from PySide6.QtCore import QPointF
        painter.setPen(QPen(QColor(60, 62, 70), 0.15 * k))
        for poly in cut:
            paper = [(cx + px * s, cy + py * s) for px, py in poly]
            for a, b in hatch_lines(paper, 45.0, 2.5):
                painter.drawLine(
                    QPointF(a[0] * k, (layout.paper_h - a[1]) * k),
                    QPointF(b[0] * k, (layout.paper_h - b[1]) * k))
        painter.setPen(QPen(QColor(10, 10, 12), 0.5 * k))
        for poly in cut:
            pts = [QPointF((cx + px * s) * k,
                           (layout.paper_h - (cy + py * s)) * k)
                   for px, py in poly]
            from PySide6.QtGui import QPolygonF
            painter.drawPolyline(QPolygonF(pts))
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
