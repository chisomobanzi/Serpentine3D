"""Compact, keyboard-accessible connection cards for the Assistant pane."""

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import QPushButton

from .workspace_icons import workspace_icon


class ConnectionChoice(QPushButton):
    def __init__(self, title, subtitle, icon, parent=None):
        super().__init__(title, parent)
        self.subtitle = subtitle
        self.setIcon(workspace_icon(icon, color="#a9b8b4", active_color="#a6d4c4"))
        self.setAccessibleName(title)
        self.setAccessibleDescription(subtitle)
        self.setToolTip(f"{title} · {subtitle}")
        self.setCheckable(True)
        self.setMinimumWidth(96)
        self.setFixedHeight(58)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self):
        return QSize(140, 58)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        active = self.isChecked()
        hover = self.underMouse() or self.hasFocus()
        painter.setPen(QPen(QColor("#628e80" if active else "#50595a" if hover else "#393f40")))
        painter.setBrush(QColor("#2e3b36" if active else "#2d3132" if hover else "#282b2d"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 5, 5)
        self.icon().paint(painter, QRect(10, 10, 15, 15), Qt.AlignmentFlag.AlignCenter,
                          QIcon.Mode.Normal, QIcon.State.On if active else QIcon.State.Off)
        font = self.font()
        font.setPixelSize(12)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#b7dfcf" if active else "#d0d8d5"))
        title = painter.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideRight,
                                                max(0, self.width() - 41))
        painter.drawText(QRect(31, 8, self.width() - 41, 19),
                         Qt.AlignmentFlag.AlignVCenter, title)
        font.setPixelSize(10)
        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QColor("#9aa9a4" if active else "#8c9596"))
        subtitle = painter.fontMetrics().elidedText(self.subtitle, Qt.TextElideMode.ElideRight,
                                                   max(0, self.width() - 20))
        painter.drawText(QRect(10, 31, self.width() - 20, 17),
                         Qt.AlignmentFlag.AlignVCenter, subtitle)
