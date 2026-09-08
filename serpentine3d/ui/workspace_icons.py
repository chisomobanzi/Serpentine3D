"""Small, consistent outline icons for the command workspace."""

from functools import lru_cache

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


# A 16px grid, rounded 1.25px strokes and generous space around each mark.
_SHAPES = {
    "assistant": '<path d="M8 1.5C8.8 5.8 10.2 7.2 14.5 8C10.2 8.8 8.8 10.2 8 14.5C7.2 10.2 5.8 8.8 1.5 8C5.8 7.2 7.2 5.8 8 1.5Z"/>',
    "script": '<path d="m4.5 4-3.5 4 3.5 4m7-8 3.5 4-3.5 4M9.5 2l-3 12"/>',
    "command": '<path d="m2.5 4 4 4-4 4m6.5 0h4.5"/>',
    "close": '<path d="m5 5 6 6m0-6-6 6"/>',
    "more": '<g fill="{color}" stroke="none"><circle cx="3" cy="8" r=".85"/><circle cx="8" cy="8" r=".85"/><circle cx="13" cy="8" r=".85"/></g>',
    "expand": '<path d="M2 6V2h4m4 0h4v4m0 4v4h-4m-4 0H2v-4"/>',
    "chevron-up": '<path d="m4 10 4-4 4 4"/>',
    "chevron-down": '<path d="m4 6 4 4 4-4"/>',
    "run": '<path d="m5 3 8 5-8 5Z"/>',
    "stop": '<rect x="4" y="4" width="8" height="8" rx=".8"/>',
    "send": '<path d="M8 13V3m-4 4 4-4 4 4"/>',
    "plus": '<path d="M8 3v10M3 8h10"/>',
    "settings": '<path d="M2 5h3m4 0h5M2 11h5m4 0h3"/><circle cx="7" cy="5" r="2"/><circle cx="9" cy="11" r="2"/>',
}


class _OutlineIcon(QIconEngine):
    def __init__(self, name, color, active_color):
        super().__init__()
        self.name, self.color, self.active_color = name, color, active_color
        self._renderers = {}

    def clone(self):
        return _OutlineIcon(self.name, self.color, self.active_color)

    def paint(self, painter, rect, mode, state):
        color = ("#626b70" if mode == QIcon.Mode.Disabled else
                 self.active_color if state == QIcon.State.On else
                 "#e0e6e5" if mode in (QIcon.Mode.Active, QIcon.Mode.Selected)
                 else self.color)
        if color not in self._renderers:
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16" '
                   f'fill="none" stroke="{color}" stroke-width="1.25" '
                   'stroke-linecap="round" stroke-linejoin="round">'
                   + _SHAPES[self.name].format(color=color) + '</svg>')
            self._renderers[color] = QSvgRenderer(svg.encode())
        painter.save()
        side = min(rect.width(), rect.height())
        bounds = QRectF(rect.x() + (rect.width() - side) / 2,
                        rect.y() + (rect.height() - side) / 2, side, side)
        self._renderers[color].render(painter, bounds)
        painter.restore()

    def pixmap(self, size, mode, state):
        pixmap = QPixmap(size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap

    def scaledPixmap(self, size, mode, state, scale):
        pixels = QSize(round(size.width() * scale), round(size.height() * scale))
        pixmap = self.pixmap(pixels, mode, state)
        pixmap.setDevicePixelRatio(scale)
        return pixmap


@lru_cache(maxsize=64)
def workspace_icon(name, color="#9ca6ad", active_color=None):
    """Render at the requested display scale, with explicit hover/checked states."""
    return QIcon(_OutlineIcon(name, color, active_color or color))
