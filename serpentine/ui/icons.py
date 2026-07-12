"""Vector toolbar icons drawn with QPainter — no asset files needed."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap,
)

_STROKE = QColor("#c8c9cc")
_FILL = QColor(200, 201, 204, 70)
_ACCENT = QColor("#d9a441")

SIZE = 22
_SCALE = 2  # draw at 2x for crisp hidpi


def _painter(pix: QPixmap) -> QPainter:
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(_STROKE, 1.7)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    return p


def _dot(p: QPainter, x, y, r=1.6, color=_ACCENT):
    p.save()
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QBrush(color))
    p.drawEllipse(QPointF(x, y), r, r)
    p.restore()


# each drawer paints into a 22x22 logical box
def _line(p):
    p.drawLine(4, 18, 18, 4)
    _dot(p, 4, 18)
    _dot(p, 18, 4)


def _polyline(p):
    path = QPainterPath(QPointF(3, 18))
    path.lineTo(8, 6)
    path.lineTo(13, 14)
    path.lineTo(19, 4)
    p.drawPath(path)


def _curve(p):
    path = QPainterPath(QPointF(3, 18))
    path.cubicTo(10, 20, 8, 4, 19, 5)
    p.drawPath(path)
    _dot(p, 3, 18)
    _dot(p, 19, 5)


def _circle(p):
    p.drawEllipse(QRectF(4, 4, 14, 14))


def _arc(p):
    p.drawArc(QRectF(3, 6, 16, 22), 30 * 16, 120 * 16)
    _dot(p, 4.6, 14.5)
    _dot(p, 17.4, 14.5)


def _rect(p):
    p.drawRect(QRectF(4, 6, 14, 10))


def _extrude(p):
    p.drawRect(QRectF(5, 12, 12, 6))
    p.drawLine(11, 10, 11, 3)
    p.drawLine(8, 6, 11, 3)
    p.drawLine(14, 6, 11, 3)


def _revolve(p):
    p.drawLine(11, 3, 11, 19)
    p.drawEllipse(QRectF(4, 12, 14, 5))
    path = QPainterPath(QPointF(15, 6))
    path.quadTo(18, 8, 16, 11)
    p.drawPath(path)
    p.drawLine(16, 11, 14.4, 9.4)


def _loft(p):
    path1 = QPainterPath(QPointF(4, 6))
    path1.quadTo(11, 3, 18, 6)
    path2 = QPainterPath(QPointF(4, 16))
    path2.quadTo(11, 13, 18, 16)
    p.drawPath(path1)
    p.drawPath(path2)
    p.drawLine(4, 6, 4, 16)
    p.drawLine(18, 6, 18, 16)


def _planar(p):
    path = QPainterPath(QPointF(6, 5))
    path.lineTo(18, 5)
    path.lineTo(16, 17)
    path.lineTo(4, 17)
    path.closeSubpath()
    p.fillPath(path, _FILL)
    p.drawPath(path)


def _sweep1(p):
    path = QPainterPath(QPointF(4, 17))
    path.cubicTo(8, 17, 12, 8, 18, 6)
    p.drawPath(path)
    p.drawEllipse(QRectF(2, 14.5, 5, 5))


def _sweep2(p):
    path1 = QPainterPath(QPointF(4, 19))
    path1.cubicTo(8, 19, 12, 10, 18, 8)
    path2 = QPainterPath(QPointF(4, 13))
    path2.cubicTo(8, 13, 12, 4, 18, 2.5)
    p.drawPath(path1)
    p.drawPath(path2)
    p.drawEllipse(QRectF(2.2, 13.4, 4.2, 6.5))


def _box(p):
    p.drawRect(QRectF(4, 8, 10, 10))
    p.drawLine(4, 8, 8, 4)
    p.drawLine(14, 8, 18, 4)
    p.drawLine(14, 18, 18, 14)
    p.drawLine(8, 4, 18, 4)
    p.drawLine(18, 4, 18, 14)


def _sphere(p):
    p.drawEllipse(QRectF(4, 4, 14, 14))
    p.drawArc(QRectF(4, 8.5, 14, 5), 180 * 16, 180 * 16)


def _cylinder(p):
    p.drawEllipse(QRectF(6, 3, 10, 4))
    p.drawLine(6, 5, 6, 17)
    p.drawLine(16, 5, 16, 17)
    p.drawArc(QRectF(6, 15, 10, 4), 180 * 16, 180 * 16)


def _torus(p):
    p.drawEllipse(QRectF(3, 6, 16, 10))
    p.drawEllipse(QRectF(8, 9.2, 6, 3.6))


def _move(p):
    p.drawLine(11, 4, 11, 18)
    p.drawLine(4, 11, 18, 11)
    for (a, b, c) in [((11, 4), (9, 6), (13, 6)), ((11, 18), (9, 16), (13, 16)),
                      ((4, 11), (6, 9), (6, 13)), ((18, 11), (16, 9), (16, 13))]:
        p.drawLine(*a, *b)
        p.drawLine(*a, *c)


def _copy(p):
    p.drawRect(QRectF(7, 7, 11, 11))
    p.save()
    pen = QPen(_STROKE, 1.4, Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.drawRect(QRectF(4, 4, 11, 11))
    p.restore()


def _rotate(p):
    p.drawArc(QRectF(4.5, 4.5, 13, 13), 40 * 16, 250 * 16)
    p.drawLine(15.5, 3.5, 15.8, 7.4)
    p.drawLine(15.8, 7.4, 12.0, 6.4)
    _dot(p, 11, 11, 1.4)


def _scale(p):
    p.drawRect(QRectF(4, 12, 6, 6))
    p.drawRect(QRectF(8, 4, 10, 10))
    p.drawLine(6, 16, 15, 7)


def _mirror(p):
    p.save()
    pen = QPen(_STROKE, 1.2, Qt.PenStyle.DashLine)
    p.setPen(pen)
    p.drawLine(11, 3, 11, 19)
    p.restore()
    path1 = QPainterPath(QPointF(8, 6))
    path1.lineTo(8, 16)
    path1.lineTo(3, 16)
    path1.closeSubpath()
    p.fillPath(path1, _FILL)
    p.drawPath(path1)
    path2 = QPainterPath(QPointF(14, 6))
    path2.lineTo(14, 16)
    path2.lineTo(19, 16)
    path2.closeSubpath()
    p.drawPath(path2)


def _union(p):
    path = QPainterPath()
    path.addEllipse(QRectF(3, 6, 11, 11))
    path2 = QPainterPath()
    path2.addEllipse(QRectF(8, 5, 11, 11))
    united = path.united(path2)
    p.fillPath(united, _FILL)
    p.drawPath(united)


def _difference(p):
    path = QPainterPath()
    path.addEllipse(QRectF(3, 6, 11, 11))
    path2 = QPainterPath()
    path2.addEllipse(QRectF(8, 5, 11, 11))
    diff = path.subtracted(path2)
    p.fillPath(diff, _FILL)
    p.drawPath(diff)
    p.save()
    p.setPen(QPen(_STROKE, 1.1, Qt.PenStyle.DotLine))
    p.drawPath(path2)
    p.restore()


def _intersection(p):
    path = QPainterPath()
    path.addEllipse(QRectF(3, 6, 11, 11))
    path2 = QPainterPath()
    path2.addEllipse(QRectF(8, 5, 11, 11))
    inter = path.intersected(path2)
    p.fillPath(inter, QBrush(QColor(217, 164, 65, 110)))
    p.save()
    p.setPen(QPen(_STROKE, 1.1, Qt.PenStyle.DotLine))
    p.drawPath(path)
    p.drawPath(path2)
    p.restore()
    p.drawPath(inter)


def _join(p):
    path = QPainterPath(QPointF(4, 18))
    path.lineTo(11, 11)
    p.drawPath(path)
    path2 = QPainterPath(QPointF(11, 11))
    path2.quadTo(14, 8, 18, 4)
    p.drawPath(path2)
    _dot(p, 11, 11)


def _delete(p):
    p.save()
    pen = QPen(QColor("#c95f5f"), 2.0)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    p.drawLine(6, 6, 16, 16)
    p.drawLine(16, 6, 6, 16)
    p.restore()


def _trim(p):
    path = QPainterPath(QPointF(3, 16))
    path.quadTo(11, 12, 19, 14)
    p.drawPath(path)
    p.drawLine(13, 4, 9, 19)
    p.save()
    p.setPen(QPen(QColor("#c95f5f"), 1.6, Qt.PenStyle.DotLine))
    p.drawLine(15, 8, 19, 7)
    p.restore()


def _split(p):
    p.drawLine(3, 15, 9, 13)
    p.drawLine(13, 12, 19, 10)
    p.save()
    p.setPen(QPen(_ACCENT, 1.5))
    p.drawLine(11, 4, 11, 19)
    p.restore()


def _offset(p):
    path = QPainterPath(QPointF(4, 17))
    path.quadTo(11, 9, 18, 12)
    p.drawPath(path)
    p.save()
    p.setPen(QPen(_STROKE, 1.3, Qt.PenStyle.DashLine))
    path2 = QPainterPath(QPointF(4, 12))
    path2.quadTo(11, 4, 18, 7)
    p.drawPath(path2)
    p.restore()


def _fillet(p):
    p.drawLine(4, 18, 4, 9)
    p.drawLine(9, 4, 18, 4)
    path = QPainterPath(QPointF(4, 9))
    path.quadTo(4, 4, 9, 4)
    p.save()
    p.setPen(QPen(_ACCENT, 1.7))
    p.drawPath(path)
    p.restore()


def _explode(p):
    p.drawRect(QRectF(8, 8, 6, 6))
    for (x0, y0, x1, y1) in [(8, 8, 4, 4), (14, 8, 18, 4),
                             (8, 14, 4, 18), (14, 14, 18, 18)]:
        p.drawLine(x0, y0, x1, y1)


def _points(p):
    path = QPainterPath(QPointF(3, 17))
    path.cubicTo(8, 8, 14, 8, 19, 15)
    p.drawPath(path)
    p.save()
    p.setPen(QPen(_STROKE, 1.0, Qt.PenStyle.DashLine))
    p.drawLine(3, 17, 8, 6)
    p.drawLine(8, 6, 15, 6)
    p.drawLine(15, 6, 19, 15)
    p.restore()
    _dot(p, 3, 17)
    _dot(p, 8, 6)
    _dot(p, 15, 6)
    _dot(p, 19, 15)


_DRAWERS = {
    "line": _line, "polyline": _polyline, "curve": _curve, "circle": _circle,
    "arc": _arc, "rectangle": _rect, "extrude": _extrude, "revolve": _revolve,
    "loft": _loft, "planarsrf": _planar, "sweep1": _sweep1, "sweep2": _sweep2,
    "box": _box, "sphere": _sphere, "cylinder": _cylinder, "torus": _torus,
    "move": _move, "copy": _copy, "rotate": _rotate, "scale": _scale,
    "mirror": _mirror, "booleanunion": _union,
    "booleandifference": _difference, "booleanintersection": _intersection,
    "join": _join, "delete": _delete, "trim": _trim, "split": _split,
    "offset": _offset, "fillet": _fillet, "explode": _explode,
    "pointson": _points,
}


def command_icon(name: str) -> QIcon | None:
    drawer = _DRAWERS.get(name)
    if drawer is None:
        return None
    pix = QPixmap(SIZE * _SCALE, SIZE * _SCALE)
    pix.setDevicePixelRatio(_SCALE)
    pix.fill(Qt.GlobalColor.transparent)
    p = _painter(pix)
    drawer(p)
    p.end()
    return QIcon(pix)
