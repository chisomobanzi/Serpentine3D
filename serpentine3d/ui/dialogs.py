"""Making a dialog a window in its own right.

GNOME ships attach-modal-dialogs on: a DIALOG-type window is fixed to the
middle of its parent, cannot be dragged anywhere else, and takes the parent
with it if you try. That is tolerable for a two-line confirmation and not
for anything you want to read next to the drawing it is about — a file
picker, a settings panel.

Asking for a NORMAL window type opts out of it. Doing so also gives up the
free placement over the parent that came with being attached, so this hands
that back rather than leaving the window manager to guess.
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget


def untether(dialog: QWidget, *, over: QWidget | None = None) -> None:
    """Let `dialog` be moved independently of the window that opened it.

    Only Linux is touched. Elsewhere nothing attaches dialogs, and a
    DIALOG-type window is what a dialog should be — dropping the type would
    cost it its stay-above-the-parent behaviour in exchange for nothing.
    """
    if sys.platform.startswith("linux"):
        dialog.setWindowFlags(Qt.WindowType.Window)
    if over is not None:
        dialog.adjustSize()
        frame = dialog.frameGeometry()
        frame.moveCenter(over.frameGeometry().center())
        dialog.move(frame.topLeft())
