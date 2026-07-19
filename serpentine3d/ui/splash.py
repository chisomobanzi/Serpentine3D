"""Startup splash screen — shown while the geometry kernel and main window
load.

Built on Qt's QSplashScreen, which is designed for the "show, then do
blocking init" case and reliably paints its first frame on show — a custom
QWidget does not, because the ~2s kernel import is a pure C dlopen that
pumps no Qt events, so a custom splash would map but never paint.

The static art (dark drafting-sheet panel, gold serpentine mark, wordmark,
footer stamp, corner registration ticks) is baked into a pixmap once; the
status line and progress hairline are drawn live in drawContents().
"""

from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QSplashScreen

# Brand mark, kept in sync with assets/logo-mark.svg. Embedded so it works
# identically in source and packaged builds with no packaging changes.
_MARK_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="50 46 176 164">
  <defs><linearGradient id="gold" x1="0" y1="0" x2="0.4" y2="1">
    <stop offset="0" stop-color="#e8ca62"/><stop offset="0.55" stop-color="#d8b44a"/>
    <stop offset="1" stop-color="#c49b39"/></linearGradient></defs>
  <path d="M 74,192 C 148,204 154,150 124,128 C 94,108 106,56 178,66"
        fill="none" stroke="url(#gold)" stroke-width="27"
        stroke-linecap="round" stroke-linejoin="round"/>
  <g stroke="#7fb4e6" stroke-width="2.5">
    <line x1="178" y1="66" x2="208" y2="94"/>
    <rect x="67" y="185" width="12" height="12" fill="#7fb4e6" stroke="#3f6f9f" stroke-width="1.4"/>
    <rect x="172" y="60" width="12" height="12" fill="#7fb4e6" stroke="#3f6f9f" stroke-width="1.4"/>
    <rect x="202" y="88" width="12" height="12" fill="none"/>
  </g></svg>"""

_BG_TOP = QColor("#232428")
_BG_BOT = QColor("#161719")
_BORDER = QColor("#3a3b40")
_TICK = QColor("#4a4b50")
_GOLD = QColor("#d8b44a")
_WORDMARK = QColor("#ececee")
_MUTED = QColor("#85868a")

_W, _H = 480, 320


def _base_pixmap(version: str) -> QPixmap:
    screen = QApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen else 1.0
    pm = QPixmap(int(_W * dpr), int(_H * dpr))
    pm.setDevicePixelRatio(dpr)
    p = QPainter(pm)
    p.setRenderHints(QPainter.RenderHint.Antialiasing
                     | QPainter.RenderHint.TextAntialiasing)

    # opaque panel (rectangular — reads as a drafting sheet)
    grad = QLinearGradient(0, 0, 0, _H)
    grad.setColorAt(0, _BG_TOP)
    grad.setColorAt(1, _BG_BOT)
    p.fillRect(0, 0, _W, _H, grad)
    p.setPen(QPen(_BORDER, 1.4))
    p.drawRect(QRectF(0.7, 0.7, _W - 1.4, _H - 1.4))

    # corner registration ticks (drafting identity)
    p.setPen(QPen(_TICK, 1))
    m, t = 15, 10
    for cx, cy, dx, dy in ((m, m, 1, 1), (_W - m, m, -1, 1),
                           (m, _H - m, 1, -1), (_W - m, _H - m, -1, -1)):
        p.drawLine(cx, cy, cx + dx * t, cy)
        p.drawLine(cx, cy, cx, cy + dy * t)

    # mark, nudged left so the S body reads centred (the handle pulls right)
    mw, mh = 130, 121
    QSvgRenderer(QByteArray(_MARK_SVG)).render(
        p, QRectF((_W - mw) / 2 - 7, 40, mw, mh))

    # wordmark
    wf = QFont()
    wf.setStyleHint(QFont.StyleHint.SansSerif)
    wf.setPointSizeF(25)
    wf.setWeight(QFont.Weight.DemiBold)
    wf.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 100.5)
    p.setFont(wf)
    p.setPen(_WORDMARK)
    p.drawText(QRectF(0, 168, _W, 42),
               Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter,
               "Serpentine3D")

    # short gold rule under the wordmark
    p.setPen(QPen(_GOLD, 2))
    p.drawLine(int(_W / 2 - 22), 214, int(_W / 2 + 22), 214)

    # footer stamp
    ff = QFont("monospace")
    ff.setStyleHint(QFont.StyleHint.Monospace)
    ff.setPointSizeF(8.5)
    ff.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 112)
    p.setFont(ff)
    p.setPen(_MUTED)
    p.drawText(QRectF(0, _H - 40, _W, 18), Qt.AlignmentFlag.AlignHCenter,
               f"v{version}  ·  MIT  ·  OPEN SOURCE")
    p.end()
    return pm


class SplashScreen(QSplashScreen):
    def __init__(self, version: str = "0.4.0"):
        super().__init__(_base_pixmap(version))
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self._status = ""
        self._progress = 0.0

    def message(self, text: str, progress: float | None = None):
        """Update status line (+ optional 0..1 progress) and repaint now."""
        self._status = text
        if progress is not None:
            self._progress = max(0.0, min(1.0, progress))
        self.repaint()
        QApplication.processEvents()

    def drawContents(self, painter: QPainter):
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        sf = QFont()
        sf.setPointSizeF(10.5)
        painter.setFont(sf)
        painter.setPen(_MUTED)
        painter.drawText(QRectF(0, 236, _W, 20),
                         Qt.AlignmentFlag.AlignHCenter, self._status)
        if self._progress > 0:
            y, x0, x1 = _H - 4, 20, _W - 20
            painter.setPen(QPen(QColor(216, 180, 74, 90), 2))
            painter.drawLine(x0, y, x1, y)
            painter.setPen(QPen(_GOLD, 2))
            painter.drawLine(x0, y, int(x0 + (x1 - x0) * self._progress), y)


def mark_pixmap(width: int) -> QPixmap:
    """The gold serpentine mark as a transparent QPixmap (shared with the
    welcome screen)."""
    h = round(width * 164 / 176)
    pm = QPixmap(width, h)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(_MARK_SVG)).render(p)
    p.end()
    return pm


def should_show() -> bool:
    """Skip the splash for headless/automation runs."""
    if os.environ.get("SERP3D_NO_SPLASH") == "1":
        return False
    if QApplication.platformName() in ("offscreen", "minimal", "vnc"):
        return False
    return True
