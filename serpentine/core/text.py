"""Text as curves, via Qt font outlines."""

from __future__ import annotations


def text_curves(text: str, height: float, font_family: str = "sans",
                bold: bool = False) -> list:
    """Closed outline curves for a text string, cap height ~= `height`,
    baseline at the origin extending +X, on the world XY plane."""
    from PySide6.QtGui import QFont, QGuiApplication, QPainterPath, QTransform
    from . import geometry

    if not text.strip():
        raise geometry.GeometryError("Empty text")
    if QGuiApplication.instance() is None:      # headless/scripting use
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        text_curves._app = QGuiApplication([])
    font = QFont(font_family)
    font.setPixelSize(256)
    font.setBold(bold)
    path = QPainterPath()
    path.addText(0, 0, font, text)
    # scale so the glyph box height matches `height`
    bounds = path.boundingRect()
    if bounds.height() < 1e-9:
        raise geometry.GeometryError("Font produced no outlines")
    cap = 256 * 0.72                     # approx cap height of pixel size
    scale = float(height) / cap
    path = QTransform().scale(scale, -scale).map(path)   # flip y-up

    curves = []
    for poly in path.toSubpathPolygons():
        pts = [(p.x(), p.y(), 0.0) for p in poly]
        if len(pts) < 3:
            continue
        try:
            curves.append(geometry.make_polyline(pts, closed=True))
        except geometry.GeometryError:
            continue
    if not curves:
        raise geometry.GeometryError("No text outlines produced")
    return curves
