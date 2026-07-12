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
    writer = QPdfWriter(path)
    writer.setPageSize(QPageSize(QSizeF(layout.paper_w, layout.paper_h),
                                 QPageSize.Unit.Millimeter,
                                 name="", matchPolicy=QPageSize.SizeMatchPolicy.ExactMatch))
    writer.setResolution(600)
    painter = QPainter(writer)
    try:
        _paint_layout(painter, window, layout,
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

    # notes
    for note in layout.notes:
        painter.setPen(QPen(QColor(25, 25, 30)))
        font = QFont("sans")
        font.setPixelSize(max(int(note.height * k), 4))
        painter.setFont(font)
        nx, ny = pt(note.x, note.y)
        painter.drawText(int(nx), int(ny), note.text)

    # dimensions
    for dim in layout.dims:
        _paint_dim(painter, dim, layout, k, pt)


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


def _paint_dim(painter, dim, layout, k, pt):
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
    text = dim.text or f"{length * dim.scale_denom:g}"
    font = QFont("sans")
    font.setPixelSize(int(3.2 * k))
    painter.setFont(font)
    tx, ty = pt(mid[0], mid[1])
    painter.drawText(int(tx) - int(6 * k / 3.2), int(ty), text)
