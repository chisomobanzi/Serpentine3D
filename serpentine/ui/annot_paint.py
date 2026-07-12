"""Layout annotation rendering, shared by the viewport overlay and the PDF
exporter. All functions take a `to_dev(x_mm, y_mm) -> (X, Y)` mapper and
`k` = device units per paper millimetre."""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF

from ..core.layout import hatch_lines

INK = QColor(25, 25, 30)
DIM_INK = QColor(45, 70, 130)
HATCH_INK = QColor(70, 72, 80)


def _font(k: float, height_mm: float) -> QFont:
    f = QFont("sans")
    f.setPixelSize(max(int(height_mm * k), 4))
    return f


def _line(painter, to_dev, a, b):
    painter.drawLine(QPointF(*to_dev(a[0], a[1])),
                     QPointF(*to_dev(b[0], b[1])))


def _arrow(painter, to_dev, tip, direction, size=2.2):
    d = np.asarray(direction, float)
    n = np.linalg.norm(d)
    if n < 1e-12:
        return
    d = d / n
    perp = np.array([-d[1], d[0]])
    tip = np.asarray(tip, float)
    _line(painter, to_dev, tip, tip + d * size + perp * size * 0.32)
    _line(painter, to_dev, tip, tip + d * size - perp * size * 0.32)


def draw_note(painter, to_dev, k, note):
    painter.setPen(QPen(INK))
    painter.setFont(_font(k, note.height))
    x, y = to_dev(note.x, note.y)
    painter.drawText(int(x), int(y), note.text)


def draw_leader(painter, to_dev, k, leader):
    pts = leader.points
    if len(pts) < 2:
        return
    painter.setPen(QPen(INK, max(0.18 * k, 1.0)))
    for a, b in zip(pts[:-1], pts[1:]):
        _line(painter, to_dev, a, b)
    _arrow(painter, to_dev, pts[0],
           (pts[1][0] - pts[0][0], pts[1][1] - pts[0][1]))
    painter.setFont(_font(k, leader.height))
    tx, ty = to_dev(pts[-1][0] + 1.5, pts[-1][1])
    painter.drawText(int(tx), int(ty), leader.text)


def draw_hatch(painter, to_dev, k, hatch):
    pts = hatch.points
    if len(pts) < 3:
        return
    poly = QPolygonF([QPointF(*to_dev(p[0], p[1])) for p in pts])
    if hatch.pattern == "solid":
        painter.setPen(QPen(HATCH_INK, 0))
        painter.setBrush(QColor(120, 122, 130, 120))
        painter.drawPolygon(poly)
        painter.setBrush(QColor(0, 0, 0, 0))
        return
    painter.setPen(QPen(HATCH_INK, max(0.15 * k, 1.0)))
    painter.setBrush(QColor(0, 0, 0, 0))
    painter.drawPolygon(poly)
    angles = [hatch.angle]
    if hatch.pattern == "cross":
        angles.append(hatch.angle + 90)
    for ang in angles:
        for a, b in hatch_lines(pts, ang, hatch.spacing):
            _line(painter, to_dev, a, b)


def draw_lin_dim(painter, to_dev, k, dim, scene=None):
    a = np.array([dim.x1, dim.y1])
    b = np.array([dim.x2, dim.y2])
    d = b - a
    length = np.linalg.norm(d)
    if length < 1e-9:
        return
    d = d / length
    n = np.array([-d[1], d[0]])
    ao, bo = a + n * dim.offset, b + n * dim.offset
    painter.setPen(QPen(DIM_INK, max(0.18 * k, 1.0)))
    _line(painter, to_dev, a, ao + n * 2)
    _line(painter, to_dev, b, bo + n * 2)
    _line(painter, to_dev, ao, bo)
    _arrow(painter, to_dev, ao, d)
    _arrow(painter, to_dev, bo, -d)
    measured = length * dim.scale_denom
    text = dim.text or (scene.format_length(measured) if scene
                        else f"{measured:g}")
    mid = (a + b) / 2 + n * (dim.offset + 2.2)
    painter.setFont(_font(k, 3.2))
    tx, ty = to_dev(mid[0], mid[1])
    painter.drawText(int(tx) - len(text) * int(k), int(ty), text)


def draw_radial_dim(painter, to_dev, k, dim, scene=None):
    c = np.array([dim.cx, dim.cy])
    p = np.array([dim.px, dim.py])
    d = p - c
    r = np.linalg.norm(d)
    if r < 1e-9:
        return
    d = d / r
    painter.setPen(QPen(DIM_INK, max(0.18 * k, 1.0)))
    start = c - d * r if dim.diameter else c
    _line(painter, to_dev, start, p + d * 4)
    _arrow(painter, to_dev, p, -d)
    if dim.diameter:
        _arrow(painter, to_dev, start, d)
    measured = r * dim.scale_denom * (2 if dim.diameter else 1)
    prefix = "Ø" if dim.diameter else "R"
    text = dim.text or (prefix + (scene.format_length(measured) if scene
                                  else f"{measured:g}"))
    label = p + d * 5
    painter.setFont(_font(k, 3.2))
    tx, ty = to_dev(label[0], label[1])
    painter.drawText(int(tx), int(ty), text)


def draw_angular_dim(painter, to_dev, k, dim):
    v = np.array([dim.vx, dim.vy])
    a1 = math.atan2(dim.y1 - dim.vy, dim.x1 - dim.vx)
    a2 = math.atan2(dim.y2 - dim.vy, dim.x2 - dim.vx)
    sweep = (a2 - a1) % (2 * math.pi)
    if sweep > math.pi:
        a1, a2 = a2, a1
        sweep = 2 * math.pi - sweep
    painter.setPen(QPen(DIM_INK, max(0.18 * k, 1.0)))
    r = dim.radius
    _line(painter, to_dev, v, v + np.array([math.cos(a1), math.sin(a1)]) * (r + 3))
    _line(painter, to_dev, v, v + np.array([math.cos(a2), math.sin(a2)]) * (r + 3))
    steps = max(int(math.degrees(sweep) / 5), 2)
    prev = None
    for i in range(steps + 1):
        ang = a1 + sweep * i / steps
        pt = v + np.array([math.cos(ang), math.sin(ang)]) * r
        if prev is not None:
            _line(painter, to_dev, prev, pt)
        prev = pt
    mid_ang = a1 + sweep / 2
    label = v + np.array([math.cos(mid_ang), math.sin(mid_ang)]) * (r + 3)
    painter.setFont(_font(k, 3.2))
    tx, ty = to_dev(label[0], label[1])
    painter.drawText(int(tx), int(ty), f"{math.degrees(sweep):.1f}°")


TITLE_FIELDS = ("project", "title", "author", "date", "scale", "sheet")


def draw_title_block(painter, to_dev, k, layout, sheet_index=1,
                     sheet_count=1):
    tb = layout.title_block
    if not tb:
        return
    import datetime
    fields = dict(tb.get("fields", {}))
    fields.setdefault("date", datetime.date.today().isoformat())
    fields.setdefault("sheet", f"{sheet_index} / {sheet_count}")
    if not fields.get("scale") and layout.details:
        fields["scale"] = layout.details[0].scale_text()

    w, h = 92.0, 26.0
    m = layout.margin
    x0 = layout.paper_w - m - w
    y0 = m
    painter.setPen(QPen(INK, max(0.3 * k, 1.2)))
    painter.setBrush(QColor(255, 255, 255, 235))
    painter.drawRect(int(to_dev(x0, y0 + h)[0]), int(to_dev(x0, y0 + h)[1]),
                     int(w * k), int(h * k))
    painter.setBrush(QColor(0, 0, 0, 0))
    # rows: project (big), title, then author/date/scale/sheet grid
    _line(painter, to_dev, (x0, y0 + h - 8), (x0 + w, y0 + h - 8))
    _line(painter, to_dev, (x0, y0 + h - 15), (x0 + w, y0 + h - 15))
    _line(painter, to_dev, (x0 + w / 2, y0), (x0 + w / 2, y0 + h - 15))
    painter.setFont(_font(k, 4.2))
    painter.setPen(QPen(INK))
    painter.drawText(int(to_dev(x0 + 2, y0 + h - 2.2)[0]),
                     int(to_dev(x0 + 2, y0 + h - 2.2)[1]),
                     fields.get("project", ""))
    painter.setFont(_font(k, 3.4))
    painter.drawText(int(to_dev(x0 + 2, y0 + h - 9.7)[0]),
                     int(to_dev(x0 + 2, y0 + h - 9.7)[1]),
                     fields.get("title", ""))
    painter.setFont(_font(k, 2.6))
    cells = [
        (x0 + 2, y0 + 7.5, f"drawn: {fields.get('author', '')}"),
        (x0 + 2, y0 + 2.5, f"date: {fields.get('date', '')}"),
        (x0 + w / 2 + 2, y0 + 7.5, f"scale: {fields.get('scale', '')}"),
        (x0 + w / 2 + 2, y0 + 2.5, f"sheet: {fields.get('sheet', '')}"),
    ]
    for cx, cy, text in cells:
        painter.drawText(int(to_dev(cx, cy)[0]), int(to_dev(cx, cy)[1]),
                         text)


def draw_scale_bar(painter, to_dev, k, x, y, scale_denom, scene=None):
    """A labelled scale bar: five segments of a round model length."""
    # pick a nice model length per segment ~ 10mm of paper
    target_model = 10.0 * scale_denom
    mag = 10 ** math.floor(math.log10(max(target_model, 1e-9)))
    for mult in (1, 2, 5, 10):
        if mag * mult >= target_model:
            seg_model = mag * mult
            break
    else:
        seg_model = mag * 10
    seg_mm = seg_model / scale_denom
    painter.setPen(QPen(INK, max(0.25 * k, 1.0)))
    for i in range(5):
        x0 = x + i * seg_mm
        if i % 2 == 0:
            painter.setBrush(INK)
        else:
            painter.setBrush(QColor(255, 255, 255))
        painter.drawRect(int(to_dev(x0, y + 1.8)[0]),
                         int(to_dev(x0, y + 1.8)[1]),
                         int(seg_mm * k), int(1.8 * k))
    painter.setBrush(QColor(0, 0, 0, 0))
    painter.setFont(_font(k, 2.4))
    label0 = to_dev(x, y)
    painter.drawText(int(label0[0]), int(label0[1]), "0")
    end = to_dev(x + 5 * seg_mm, y)
    total = 5 * seg_model
    text = scene.format_length(total) if scene else f"{total:g}"
    painter.drawText(int(end[0]), int(end[1]), text)


def draw_all(painter, to_dev, k, layout, scene=None, sheet_index=1,
             sheet_count=1):
    """Every annotation for one layout, in drawing order."""
    for hatch in layout.hatches:
        draw_hatch(painter, to_dev, k, hatch)
    for note in layout.notes:
        draw_note(painter, to_dev, k, note)
    for leader in layout.leaders:
        draw_leader(painter, to_dev, k, leader)
    for dim in layout.dims:
        draw_lin_dim(painter, to_dev, k, dim, scene)
    for dim in layout.rdims:
        draw_radial_dim(painter, to_dev, k, dim, scene)
    for dim in layout.adims:
        draw_angular_dim(painter, to_dev, k, dim)
    draw_title_block(painter, to_dev, k, layout, sheet_index, sheet_count)
    for bar in getattr(layout, "scale_bars", []):
        draw_scale_bar(painter, to_dev, k, bar[0], bar[1], bar[2], scene)
