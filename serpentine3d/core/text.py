"""Text as curves, via Qt font outlines."""

from __future__ import annotations

from .text_object import TextShape


def text_path(text: str, height: float, font_family: str = "sans",
              bold: bool = False, *, font_style: str = "",
              alignment: str = "left"):
    """Font outlines in model units, with the first baseline at the origin.

    The returned Qt path uses downward-positive Y. Each line aligns its font
    advance to the origin, and ``height`` is the font's capital-letter height.
    Rendering and modelling can share these exact outlines and metrics.
    """
    import math
    from PySide6.QtGui import (QFont, QFontDatabase, QFontMetricsF,
                              QGuiApplication, QPainterPath, QTransform)
    from . import geometry

    if not text.strip():
        raise geometry.GeometryError("Empty text")
    if not math.isfinite(height) or height <= 0:
        raise geometry.GeometryError("Text height must be positive and finite")
    if alignment not in ("left", "center", "right"):
        raise geometry.GeometryError("Text alignment must be left, center or right")
    if QGuiApplication.instance() is None:      # headless/scripting use
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        text_path._app = QGuiApplication([])
    if font_style:
        font = QFontDatabase.font(font_family, font_style, 12)
    else:
        font = QFont(font_family)
        font.setBold(bold)
    # Use enough resolution to keep font metric rounding below model precision.
    font.setPixelSize(2048)
    metrics = QFontMetricsF(font)
    cap_height = metrics.capHeight()
    if cap_height <= 0:
        raise geometry.GeometryError("Font has no capital-letter height")

    path = QPainterPath()
    factor = {"left": 0.0, "center": 0.5, "right": 1.0}[alignment]
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for row, line in enumerate(lines):
        path.addText(-factor * metrics.horizontalAdvance(line),
                     row * metrics.lineSpacing(), font, line)
    if path.isEmpty():
        raise geometry.GeometryError("Font produced no outlines")
    scale = float(height) / cap_height
    return QTransform().scale(scale, scale).map(path)


def text_curves(text: str, height: float, font_family: str = "sans",
                bold: bool = False, *, font_style: str = "",
                alignment: str = "left") -> list:
    """Closed line/Bezier glyph contours on XY, preserving separate counters.

    The first baseline is at the origin, positive Y points up, and subsequent
    lines extend down. ``height`` specifies the font's capital-letter height.
    """
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire
    from OCP.Geom import Geom_BezierCurve
    from OCP.Precision import Precision
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.gp import gp_Pnt
    from PySide6.QtGui import QPainterPath
    from . import geometry

    path = text_path(text, height, font_family, bold,
                     font_style=font_style, alignment=alignment)
    tolerance = Precision.Confusion_s()

    curves = []
    wire = None
    start = current = None

    def point(index):
        element = path.elementAt(index)
        return gp_Pnt(element.x, -element.y, 0.0)

    def finish_contour():
        if wire is None or not wire.IsDone():
            return
        if not current.IsEqual(start, tolerance):
            wire.Add(BRepBuilderAPI_MakeEdge(current, start).Edge())
        if not wire.IsDone():
            raise geometry.GeometryError("Unable to close a text outline")
        curves.append(wire.Wire())

    index = 0
    while index < path.elementCount():
        element = path.elementAt(index)
        if element.type == QPainterPath.ElementType.MoveToElement:
            finish_contour()
            wire = BRepBuilderAPI_MakeWire()
            start = current = point(index)
        elif element.type == QPainterPath.ElementType.LineToElement:
            end = point(index)
            if not current.IsEqual(end, tolerance):
                wire.Add(BRepBuilderAPI_MakeEdge(current, end).Edge())
            current = end
        elif element.type == QPainterPath.ElementType.CurveToElement:
            poles = TColgp_Array1OfPnt(1, 4)
            poles.SetValue(1, current)
            for offset in range(3):
                poles.SetValue(offset + 2, point(index + offset))
            wire.Add(BRepBuilderAPI_MakeEdge(Geom_BezierCurve(poles)).Edge())
            current = point(index + 2)
            index += 2
        index += 1
    finish_contour()
    if not curves:
        raise geometry.GeometryError("No text outlines produced")
    return curves
