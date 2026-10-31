"""Lining up chosen components: a small bar at the canvas's top right,
shown while two or more are chosen, that aligns their edges or middles or
spaces them evenly."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QFrame, QHBoxLayout, QToolButton

from ..icons import align_icon

# what each button does, in the order the bar shows them; None a gap
ALIGNS = (
    ("left", "Align left edges"),
    ("center", "Align centres, one above the other"),
    ("right", "Align right edges"),
    None,
    ("top", "Align top edges"),
    ("middle", "Align middles, side by side"),
    ("bottom", "Align bottom edges"),
    None,
    ("across", "Space evenly from left to right"),
    ("down", "Space evenly from top to bottom"),
)
MARGIN = 8                  # screen pixels from the canvas's edges


def arranged(boxes, how):
    """Where each box goes, as its new top left corner, for `how`, one of
    ALIGNS; the boxes are (x, y, width, height)."""
    if how in ("left", "center", "right"):
        left = min(x for x, _y, _w, _h in boxes)
        right = max(x + w for x, _y, w, _h in boxes)
        middle = (left + right) / 2
        place = {"left": lambda w: left, "right": lambda w: right - w,
                 "center": lambda w: middle - w / 2}[how]
        return [(place(w), y) for x, y, w, h in boxes]
    if how in ("top", "middle", "bottom"):
        top = min(y for _x, y, _w, _h in boxes)
        bottom = max(y + h for _x, y, _w, h in boxes)
        middle = (top + bottom) / 2
        place = {"top": lambda h: top, "bottom": lambda h: bottom - h,
                 "middle": lambda h: middle - h / 2}[how]
        return [(x, place(h)) for x, y, w, h in boxes]
    # spaced evenly: the first and the last stay, the gaps between all the
    # boxes come out the same
    along = 0 if how == "across" else 1
    order = sorted(range(len(boxes)), key=lambda i: boxes[i][along])
    first, last = boxes[order[0]], boxes[order[-1]]
    span = last[along] + last[along + 2] - first[along]
    gap = ((span - sum(boxes[i][along + 2] for i in order))
           / max(len(boxes) - 1, 1))
    places = list(boxes)
    at = first[along]
    for i in order:
        box = boxes[i]
        places[i] = (at, box[1]) if along == 0 else (box[0], at)
        at += box[along + 2] + gap
    return [(p[0], p[1]) for p in places]


class AlignBar(QFrame):
    """The bar at the canvas's top right corner: shown while two or more
    components are chosen, gone otherwise."""

    def __init__(self, canvas):
        super().__init__(canvas.viewport())
        self.canvas = canvas
        self.setObjectName("hydraAlign")
        self.setStyleSheet(
            "#hydraAlign { background: #2b2d31; border: 1px solid #45484f;"
            " border-radius: 5px; }"
            "QToolButton { border: none; border-radius: 3px; padding: 3px; }"
            "QToolButton:hover { background: #3a3d43; }"
            "QToolButton:disabled { background: transparent; }")
        row = QHBoxLayout(self)
        row.setContentsMargins(4, 3, 4, 3)
        row.setSpacing(1)
        self.buttons = {}
        for entry in ALIGNS:
            if entry is None:
                line = QFrame()
                line.setFrameShape(QFrame.Shape.VLine)
                line.setStyleSheet("color: #45484f;")
                row.addWidget(line)
                continue
            how, tip = entry
            button = QToolButton()
            button.setIcon(align_icon(how))
            button.setIconSize(QSize(18, 18))
            button.setToolTip(tip)
            button.clicked.connect(lambda checked=False, how=how:
                                   canvas.editor.align(how))
            row.addWidget(button)
            self.buttons[how] = button
        self.hide()

    def follow(self):
        """At the canvas's top right corner while two or more are chosen,
        hidden otherwise."""
        chosen = self.canvas.chosen_items()
        if len(chosen) < 2:
            self.hide()
            return
        # spacing evenly needs one between the first and the last
        for how in ("across", "down"):
            self.buttons[how].setEnabled(len(chosen) > 2)
        self.adjustSize()
        self.move(self.canvas.viewport().width() - self.width() - MARGIN,
                  MARGIN)
        self.show()
        self.raise_()
