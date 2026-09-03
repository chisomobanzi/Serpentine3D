"""The little list that opens when several objects are under the cursor.

A click has always taken the nearest thing on the ray, which is right
almost every time and useless the rest of the time: the object you want is
behind a wall, and the only way through was to hide the wall. So holding
the button still for a moment offers everything under the cursor instead,
nearest first, and pointing at a row lights that object in the viewport so
you can see which one you are about to take.

The rows carry a swatch in the object's own colour and its kind on the
right, because a scene full of "Solid 04" tells you nothing on its own.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QMenu, QWidget, QWidgetAction

from . import theme

ROW_HEIGHT = 27
ROW_MIN_WIDTH = 190
ROW_MAX_WIDTH = 460
SWATCH = 9                  # diameter of the colour dot, in pixels
PAD_X = 11


def kind_label(kind: str) -> str:
    """What an object's kind is called in front of a person."""
    return "Point cloud" if kind == "pointcloud" else kind.capitalize()


@dataclass(frozen=True)
class ChoiceRow:
    """One line of the chooser: which object, and how to recognise it."""
    obj_id: str
    name: str
    kind: str
    color: tuple[float, float, float]


def chooser_rows(scene, ids) -> list[ChoiceRow]:
    """Rows for these object ids, in the order given.

    Anything that has left the scene since the pick is dropped rather than
    offered as a row that would pick nothing.
    """
    rows = []
    for obj_id in ids:
        obj = scene.get(obj_id)
        if obj is None:
            continue
        rows.append(ChoiceRow(obj_id=obj.id, name=obj.name,
                              kind=kind_label(obj.kind),
                              color=scene.color_of(obj)))
    return rows


def _qcolor(rgb) -> QColor:
    return QColor.fromRgbF(*(min(1.0, max(0.0, c)) for c in rgb[:3]))


class _RowWidget(QWidget):
    """Paints one row. Mouse events pass straight through to the menu, so
    the menu keeps doing its own hit-testing, highlighting and keyboard
    walking: this only draws what the menu has decided."""

    def __init__(self, row: ChoiceRow, parent=None):
        super().__init__(parent)
        self.row = row
        self.current = False
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        f = self.font()
        self._kind_font = QFont(f)
        self._kind_font.setPointSizeF(max(6.5, f.pointSizeF() - 1.0))

    def sizeHint(self) -> QSize:
        name_w = self.fontMetrics().horizontalAdvance(self.row.name)
        kind_w = self.fontMetrics().horizontalAdvance(self.row.kind)
        want = PAD_X + SWATCH + 9 + name_w + 22 + kind_w + PAD_X
        return QSize(max(ROW_MIN_WIDTH, min(ROW_MAX_WIDTH, want)), ROW_HEIGHT)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(3, 1, -3, -1)
        if self.current:
            p.setBrush(QColor("#4a3f28"))       # the same warm grey a menu
            p.setPen(Qt.PenStyle.NoPen)         # item uses when it is picked
            p.drawRoundedRect(r, 4, 4)

        # A dot, not a square: a square in the default near-white reads
        # as an unticked checkbox sitting next to the name.
        p.setBrush(_qcolor(self.row.color))
        p.setPen(QPen(QColor(0, 0, 0, 130), 1))
        p.drawEllipse(r.left() + PAD_X - 3, r.center().y() - SWATCH // 2,
                      SWATCH, SWATCH)

        text_x = r.left() + PAD_X - 3 + SWATCH + 9
        kind_w = self.fontMetrics().boundingRect(self.row.kind).width() + 4
        p.setPen(QColor("#f0d9a8" if self.current else "#e8e8ea"))
        p.drawText(
            r.adjusted(text_x - r.left(), 0, -(kind_w + PAD_X), 0),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            self.fontMetrics().elidedText(
                self.row.name, Qt.TextElideMode.ElideMiddle,
                r.width() - text_x + r.left() - kind_w - PAD_X))

        p.setFont(self._kind_font)
        p.setPen(QColor(theme.ACCENT_DIM if self.current
                        else theme.TEXT_MUTED))
        p.drawText(
            r.adjusted(0, 0, -PAD_X + 2, 0),
            int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter),
            self.row.kind)


class _HintWidget(QWidget):
    """The quiet line along the bottom saying which keys work."""

    TEXT = "↑↓ to walk   ↵ picks   Esc cancels"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        f = self.font()
        f.setPointSizeF(max(6.0, f.pointSizeF() - 1.5))
        self.setFont(f)

    def sizeHint(self) -> QSize:
        fm = self.fontMetrics()
        return QSize(fm.horizontalAdvance(self.TEXT) + 2 * PAD_X,
                     fm.height() + 9)

    def paintEvent(self, _ev):
        p = QPainter(self)
        top = self.rect().top() + 3
        p.setPen(QColor("#3d3e44"))
        p.drawLine(self.rect().left() + 7, top, self.rect().right() - 7, top)
        p.setPen(QColor(theme.TEXT_MUTED))
        p.drawText(self.rect().adjusted(PAD_X, 3, -PAD_X, 0),
                   int(Qt.AlignmentFlag.AlignCenter), self.TEXT)


class ObjectChooser(QMenu):
    """The objects under the cursor, offered nearest first.

    Emits `rowHovered` with the id the cursor (or the arrow keys) is on so
    the viewport can light it, and `None` on the way out. `objectChosen`
    carries the id that was taken.
    """

    rowHovered = Signal(object)
    objectChosen = Signal(str)

    STYLE = """
    QMenu {
        background: #26272b;
        border: 1px solid #15161a;
        border-radius: 7px;
        padding: 5px 0px;
    }
    """

    def __init__(self, rows: list[ChoiceRow], parent=None):
        super().__init__(parent)
        self.setStyleSheet(self.STYLE)
        self._widgets: dict = {}
        for row in rows:
            act = QWidgetAction(self)
            w = _RowWidget(row, self)
            act.setDefaultWidget(w)
            act.setData(row.obj_id)
            self._widgets[act] = w
            self.addAction(act)
        hint = QWidgetAction(self)
        hint.setDefaultWidget(_HintWidget(self))
        hint.setEnabled(False)          # so the arrow keys walk past it
        self.addAction(hint)

        self.hovered.connect(self._row_entered)
        self.triggered.connect(self._row_taken)
        self.aboutToHide.connect(lambda: self.rowHovered.emit(None))

    def showEvent(self, ev):
        """Open with the nearest one lit. That is the object a plain click
        would have taken, so you can see what you are choosing away from,
        and the arrow keys have somewhere to start walking from.

        On the way up rather than in `__init__`, because whoever opened it
        connects to `rowHovered` after building it.
        """
        super().showEvent(ev)
        if self._widgets and self.activeAction() is None:
            first = next(iter(self._widgets))
            self.setActiveAction(first)
            self._row_entered(first)

    def _row_entered(self, act):
        for a, w in self._widgets.items():
            if w.current != (a is act):
                w.current = a is act
                w.update()
        self.rowHovered.emit(act.data())

    def _row_taken(self, act):
        if act.data():
            self.objectChosen.emit(act.data())
