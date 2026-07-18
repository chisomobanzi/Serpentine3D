"""Startup splash screen — shown while the main window builds.

A frameless, translucent panel in the app's dark/amber identity: the gold
serpentine mark, the wordmark, a drafting-style footer stamp, and a status
line + progress hairline that advance as the app initialises. Closes the
moment the main window appears.
"""

from __future__ import annotations

import os

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication, QWidget

# The brand mark, kept in sync with assets/logo-mark.svg. Embedded rather
# than loaded from a file so it works identically in source and packaged
# builds without touching every packaging config.
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

# palette (matches the app tile + theme)
_BG_TOP = QColor("#232428")
_BG_BOT = QColor("#161719")
_BORDER = QColor("#3a3b40")
_TICK = QColor("#4a4b50")
_GOLD = QColor("#d8b44a")
_WORDMARK = QColor("#ececee")
_MUTED = QColor("#85868a")

_W, _H = 480, 320


class SplashScreen(QWidget):
    def __init__(self, version: str = "0.3.1"):
        super().__init__(None, Qt.WindowType.SplashScreen
                         | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(_W, _H)
        self._mark = QSvgRenderer(QByteArray(_MARK_SVG))
        self._status = ""
        self._progress = 0.0
        self._footer = f"v{version}  ·  MIT  ·  OPEN SOURCE"
        self._center_on_screen()

    def _center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen is not None:
            geo = screen.availableGeometry()
            self.move(geo.center().x() - _W // 2, geo.center().y() - _H // 2)

    def message(self, text: str, progress: float | None = None):
        """Update the status line (and optional 0..1 progress), repaint now."""
        self._status = text
        if progress is not None:
            self._progress = max(0.0, min(1.0, progress))
        self.repaint()
        QApplication.processEvents()

    def finish(self, window):
        self.close()
        self.deleteLater()

    # -- painting --
    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing
                         | QPainter.RenderHint.TextAntialiasing)
        r = QRectF(1, 1, _W - 2, _H - 2)

        panel = QPainterPath()
        panel.addRoundedRect(r, 18, 18)
        grad = QLinearGradient(0, 0, 0, _H)
        grad.setColorAt(0, _BG_TOP)
        grad.setColorAt(1, _BG_BOT)
        p.fillPath(panel, grad)
        p.setPen(QPen(_BORDER, 1.2))
        p.drawPath(panel)

        self._draw_ticks(p)

        # mark, centred in the upper third; nudged left so the S body reads
        # centred (the tangent handle otherwise pulls it right)
        mw, mh = 130, 121
        self._mark.render(p, QRectF((_W - mw) / 2 - 7, 40, mw, mh))

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

        # short gold rule under the wordmark (drafting accent)
        p.setPen(QPen(_GOLD, 2))
        p.drawLine(int(_W / 2 - 22), 214, int(_W / 2 + 22), 214)

        # status line
        sf = QFont()
        sf.setPointSizeF(10.5)
        p.setFont(sf)
        p.setPen(_MUTED)
        p.drawText(QRectF(0, 236, _W, 20),
                   Qt.AlignmentFlag.AlignHCenter, self._status)

        # footer stamp (mono, spaced, uppercase)
        ff = QFont("monospace")
        ff.setStyleHint(QFont.StyleHint.Monospace)
        ff.setPointSizeF(8.5)
        ff.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 112)
        p.setFont(ff)
        p.setPen(_MUTED)
        p.drawText(QRectF(0, _H - 40, _W, 18),
                   Qt.AlignmentFlag.AlignHCenter, self._footer)

        # progress hairline along the bottom edge
        if self._progress > 0:
            y = _H - 3
            x0, x1 = 20, _W - 20
            p.setPen(QPen(QColor(_GOLD.red(), _GOLD.green(), _GOLD.blue(), 90),
                          2))
            p.drawLine(x0, y, x1, y)
            p.setPen(QPen(_GOLD, 2))
            p.drawLine(x0, y, int(x0 + (x1 - x0) * self._progress), y)
        p.end()

    def _draw_ticks(self, p: QPainter):
        """Registration ticks in the corners — echoes the drafting identity."""
        p.setPen(QPen(_TICK, 1))
        m, t = 14, 9          # margin, tick length
        for cx, cy, dx, dy in ((m, m, 1, 1), (_W - m, m, -1, 1),
                               (m, _H - m, 1, -1), (_W - m, _H - m, -1, -1)):
            p.drawLine(cx, cy, cx + dx * t, cy)
            p.drawLine(cx, cy, cx, cy + dy * t)


def should_show() -> bool:
    """Skip the splash for headless/automation runs."""
    if os.environ.get("SERP3D_NO_SPLASH") == "1":
        return False
    if QApplication.platformName() in ("offscreen", "minimal", "vnc"):
        return False
    return True
