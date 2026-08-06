"""The command line, printed onto the frame.

What separates a Serpentine timelapse from every other CAD timelapse is
that the recipe is visible: the watcher sees `box`, `fillet 2`, `sweep2`
land as the shapes appear, and can type the same words themselves.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QImage, QPainter

_BAND = QColor(16, 17, 19, 216)
_CMD = QColor(216, 180, 74)             # the typed command, in the gold
_ECHO = QColor(180, 182, 186)


def caption(img: QImage, command: str, echo: str = ""):
    """Draw the caption band onto `img` in place."""
    w, h = img.width(), img.height()
    unit = min(w, h)
    line = max(14, int(unit * 0.032))
    pad = int(line * 0.7)
    band_h = pad * 2 + line + (int(line * 1.3) if echo else 0)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.fillRect(0, h - band_h, w, band_h, _BAND)
    mono = QFont("monospace")
    mono.setStyleHint(QFont.StyleHint.Monospace)
    mono.setPixelSize(line)
    p.setFont(mono)
    p.setPen(_CMD)
    p.drawText(QRectF(pad, h - band_h + pad * 0.6, w - 2 * pad, line * 1.3),
               Qt.AlignmentFlag.AlignLeft, command)
    if echo:
        p.setPen(_ECHO)
        p.drawText(QRectF(pad, h - band_h + pad * 0.6 + line * 1.3,
                          w - 2 * pad, line * 1.3),
                   Qt.AlignmentFlag.AlignLeft, echo)
    p.end()
