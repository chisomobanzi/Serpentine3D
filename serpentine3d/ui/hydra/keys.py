"""The keys Hydra answers wherever the keyboard is."""

from __future__ import annotations

from PySide6.QtCore import Qt


def undo_key(event):
    """"undo" for Ctrl+Z, "redo" for Ctrl+Y or Ctrl+Shift+Z."""
    ctrl = Qt.KeyboardModifier.ControlModifier
    shift = Qt.KeyboardModifier.ShiftModifier
    mods = event.modifiers()
    if event.key() == Qt.Key.Key_Z:
        return {ctrl: "undo", ctrl | shift: "redo"}.get(mods)
    if event.key() == Qt.Key.Key_Y and mods == ctrl:
        return "redo"
    return None


def save_key(event):
    """"save" for Ctrl+S, "as" for Ctrl+Shift+S, None for anything else."""
    if event.key() != Qt.Key.Key_S:
        return None
    ctrl = Qt.KeyboardModifier.ControlModifier
    shift = Qt.KeyboardModifier.ShiftModifier
    return {ctrl: "save", ctrl | shift: "as"}.get(event.modifiers())


MODIFIER_OF = {Qt.Key.Key_Shift: Qt.KeyboardModifier.ShiftModifier,
                Qt.Key.Key_Control: Qt.KeyboardModifier.ControlModifier}


def wiring_mode(modifiers):
    """"add" with Shift, a wire beside the ones already in; "remove" with
    Ctrl, taking a wire away; None otherwise, a wire in place of the old."""
    shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
    ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
    if shift and not ctrl:
        return "add"
    if ctrl and not shift:
        return "remove"
    return None


def hide_key(event):
    """"hide" for Ctrl+H, "show" for Ctrl+Shift+H, as in the model."""
    if event.key() != Qt.Key.Key_H:
        return None
    ctrl = Qt.KeyboardModifier.ControlModifier
    shift = Qt.KeyboardModifier.ShiftModifier
    return {ctrl: "hide", ctrl | shift: "show"}.get(event.modifiers())
