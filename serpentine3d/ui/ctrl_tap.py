"""Telling a tap of Ctrl from Ctrl being used for something else."""

from __future__ import annotations

import time

from PySide6.QtCore import QEvent, QObject, Qt

# Longer than this and Ctrl was being held, whether or not anything came of it.
TAP_SECONDS = 0.35

_KEY_DOWN = (QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride)
_INTERRUPTS = (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonDblClick,
               QEvent.Type.Wheel, QEvent.Type.WindowDeactivate)
_WATCHED = frozenset((*_KEY_DOWN, *_INTERRUPTS, QEvent.Type.KeyRelease))

_OTHER_MODIFIERS = (Qt.KeyboardModifier.ShiftModifier
                    | Qt.KeyboardModifier.AltModifier
                    | Qt.KeyboardModifier.MetaModifier)


class CtrlTap(QObject):
    """Calls `on_tap` when Ctrl goes down and up with nothing in between.

    Installed on the application, not a widget. While a command runs the
    keyboard usually belongs to the command line, so a viewport would never
    hear the key. Nothing is consumed: Ctrl+Z and Ctrl+click carry on as
    they always did, and all this does is notice that they were not a tap.

    ShortcutOverride counts as a key going down because a key that fires a
    shortcut never arrives as a KeyPress, and Ctrl+S would read as a tap.
    """

    def __init__(self, on_tap, parent=None):
        super().__init__(parent)
        self._on_tap = on_tap
        self._pressed_at = None

    def eventFilter(self, obj, ev):
        kind = ev.type()
        if kind not in _WATCHED:
            return False
        if kind in _INTERRUPTS:
            self._pressed_at = None
        elif ev.isAutoRepeat():              # Windows repeats a held Ctrl
            pass
        elif ev.key() != Qt.Key.Key_Control:
            if kind != QEvent.Type.KeyRelease:
                self._pressed_at = None
        elif kind != QEvent.Type.KeyRelease:
            self._pressed_at = (None if ev.modifiers() & _OTHER_MODIFIERS
                                else time.monotonic())
        elif self._pressed_at is not None:
            held = time.monotonic() - self._pressed_at
            self._pressed_at = None
            if held < TAP_SECONDS:
                self._on_tap()
        return False
