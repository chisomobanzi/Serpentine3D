from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication


def _ctrl_c(w):
    QApplication.sendEvent(w, QKeyEvent(
        QKeyEvent.Type.KeyPress, Qt.Key.Key_C,
        Qt.KeyboardModifier.ControlModifier, "\x03"))


def test_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "s.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    ev = w.command_line.echo_view
    w.command_line.echo("Created Curve 01 (r=25).")
    ev.selectAll()
    cb = QApplication.clipboard()
    cb.clear()
    _ctrl_c(ev)
    print("clipboard after ctrl+c:", repr(cb.text()))
    print("focusPolicy:", ev.focusPolicy())
    ev.setFocus()
    print("has focus after setFocus:", ev.hasFocus())
    print("focus widget:", QApplication.focusWidget())
    w.mark_saved()
    w.close()
