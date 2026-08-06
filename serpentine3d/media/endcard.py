"""The card that signs a clip: Built with Serpentine3D.

Kept deliberately quiet — a dark ground, the name, the address, a fade.
It is the last thing a viewer sees, and the difference between a video
and an ad is about two seconds of restraint.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QImage, QPainter

SITE = "chisomobanzi.github.io/Serpentine3D"

_GROUND = QColor(24, 25, 28)
_NAME = QColor(226, 228, 232)
_DIM = QColor(133, 134, 138)
_ACCENT = QColor(216, 180, 74)          # the app's own gold


def endcard_frame(width: int, height: int, alpha: float) -> QImage:
    """One frame of the card, its text at `alpha` (0 = ground only)."""
    img = QImage(width, height, QImage.Format.Format_RGB888)
    img.fill(_GROUND)
    if alpha <= 0.0:
        return img
    a = max(0.0, min(1.0, alpha))
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    unit = min(width, height)

    def faded(color):
        c = QColor(color)
        c.setAlphaF(a)
        return c

    small = QFont()
    small.setPixelSize(max(12, int(unit * 0.030)))
    small.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 112)
    name = QFont()
    name.setPixelSize(max(18, int(unit * 0.075)))
    name.setWeight(QFont.Weight.DemiBold)

    mid = height * 0.5
    p.setFont(small)
    p.setPen(faded(_DIM))
    p.drawText(QRectF(0, mid - unit * 0.16, width, unit * 0.08),
               Qt.AlignmentFlag.AlignCenter, "BUILT WITH")
    p.setFont(name)
    p.setPen(faded(_NAME))
    p.drawText(QRectF(0, mid - unit * 0.07, width, unit * 0.14),
               Qt.AlignmentFlag.AlignCenter, "Serpentine3D")
    # the accent underline, drawn at the wordmark's measure
    fm_w = p.fontMetrics().horizontalAdvance("Serpentine3D")
    p.fillRect(QRectF((width - fm_w) / 2, mid + unit * 0.075,
                      fm_w, max(2.0, unit * 0.006)), faded(_ACCENT))
    p.setFont(small)
    p.setPen(faded(_DIM))
    p.drawText(QRectF(0, mid + unit * 0.10, width, unit * 0.08),
               Qt.AlignmentFlag.AlignCenter, SITE)
    p.end()
    return img


def endcard_frames(width: int, height: int, fps: int,
                   seconds: float = 2.0) -> list[QImage]:
    """The card as a clip tail: an ease-in fade, then it holds."""
    n = max(1, int(round(fps * seconds)))
    fade = max(1, int(round(fps * 0.6)))
    frames = []
    for k in range(n):
        t = min(1.0, (k + 1) / fade)
        frames.append(endcard_frame(width, height, t * t * (3 - 2 * t)))
    return frames
