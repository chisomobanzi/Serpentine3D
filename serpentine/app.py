"""Serpentine main application."""

from __future__ import annotations

import os
import signal
import sys

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QMainWindow, QMessageBox,
    QToolBar,
)

from . import commands as cmd_pkg
from . import fileio
from .commands.base import (
    CommandContext, CommandProcessor, PointReq, SelectReq,
)
from .core.history import History
from .core.scene import Scene
from .core.selection import SelectionManager
from .ui import theme
from .ui.command_line import CommandLine
from .ui.layers_panel import LayersPanel
from .ui.properties import PropertiesPanel
from .ui.viewport import Viewport, set_default_gl_format

APP_TITLE = "Serpentine"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1440, 900)

        # core state
        self.scene = Scene()
        self.selection = SelectionManager(self.scene)
        self.history = History(self.scene)

        # widgets
        self.viewport = Viewport(self.scene, self.selection)
        self.setCentralWidget(self.viewport)

        self.command_line = CommandLine()
        cmd_dock = QDockWidget("Command", self)
        cmd_dock.setObjectName("commandDock")
        cmd_dock.setWidget(self.command_line)
        cmd_dock.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        cmd_dock.setTitleBarWidget(_EmptyTitleBar())
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, cmd_dock)

        self.properties = PropertiesPanel(self.scene, self.selection,
                                          self.history)
        prop_dock = QDockWidget("Properties", self)
        prop_dock.setObjectName("propertiesDock")
        prop_dock.setWidget(self.properties)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, prop_dock)

        self.layers_panel = LayersPanel(self.scene, self.history)
        layer_dock = QDockWidget("Layers", self)
        layer_dock.setObjectName("layersDock")
        layer_dock.setWidget(self.layers_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, layer_dock)
        self.resizeDocks([prop_dock, layer_dock], [280, 280],
                         Qt.Orientation.Horizontal)

        # command engine
        self.ctx = CommandContext(self.scene, self.selection, self.history,
                                  viewport=self.viewport, window=self)
        self.ctx.current_path = None
        self.processor = CommandProcessor(self.ctx)
        self.ctx.add_echo_listener(self.command_line.echo)
        self.processor.add_listener(self._sync_command_state)

        # wiring
        self.command_line.submitted.connect(self._on_submit)
        self.command_line.cancelled.connect(self._cancel)
        self.viewport.objectClicked.connect(self._on_object_clicked)
        self.viewport.emptyClicked.connect(self._on_empty_clicked)
        self.viewport.boxSelected.connect(self._on_box_selected)
        self.viewport.pointPicked.connect(self._on_point_picked)
        self.viewport.mouseWorldMoved.connect(self._on_mouse_world)
        self.viewport.cvEditBegan.connect(
            lambda: self.history.checkpoint("edit control point"))
        self.viewport.escapePressed.connect(self._cancel)
        self.scene.add_listener(self._update_status)
        self.selection.add_listener(self._update_status)

        self._build_toolbar()
        self._build_menus()
        self._update_status()
        self.command_line.echo("Serpentine — type a command to begin "
                               "(line, circle, box, extrude, loft, ...)")
        self.command_line.focus()

    # ------------------------------------------------------------ UI assembly

    def _build_toolbar(self):
        bar = QToolBar("Tools")
        bar.setObjectName("toolPalette")
        bar.setOrientation(Qt.Orientation.Vertical)
        bar.setMovable(False)
        bar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        groups = [
            [("Line", "line"), ("Pline", "polyline"), ("Curve", "curve"),
             ("Circle", "circle"), ("Arc", "arc"), ("Rect", "rectangle")],
            [("Extrude", "extrude"), ("Revolve", "revolve"),
             ("Loft", "loft"), ("Planar", "planarsrf"),
             ("Sweep", "sweep1")],
            [("Box", "box"), ("Sphere", "sphere"), ("Cyl", "cylinder"),
             ("Torus", "torus")],
            [("Move", "move"), ("Copy", "copy"), ("Rotate", "rotate"),
             ("Scale", "scale"), ("Mirror", "mirror")],
            [("Union", "booleanunion"), ("Diff", "booleandifference"),
             ("Inter", "booleanintersection")],
            [("Join", "join"), ("Del", "delete")],
        ]
        for gi, group in enumerate(groups):
            if gi:
                bar.addSeparator()
            for label, command in group:
                act = QAction(label, self)
                act.setToolTip(command)
                act.triggered.connect(
                    lambda checked=False, c=command: self.run_command(c))
                bar.addAction(act)
        self.addToolBar(Qt.ToolBarArea.LeftToolBarArea, bar)

    def _build_menus(self):
        mb = self.menuBar()

        m_file = mb.addMenu("&File")
        self._action(m_file, "New", "Ctrl+N", lambda: self._file_new())
        self._action(m_file, "Open...", "Ctrl+O", self._file_open)
        m_file.addSeparator()
        self._action(m_file, "Save", "Ctrl+S", self._file_save)
        self._action(m_file, "Save As...", "Ctrl+Shift+S",
                     lambda: self._file_save(force_dialog=True))
        m_file.addSeparator()
        self._action(m_file, "Import...", None, self._file_import)
        self._action(m_file, "Export...", None, self._file_export)
        m_file.addSeparator()
        self._action(m_file, "Quit", "Ctrl+Q", self.close)

        m_edit = mb.addMenu("&Edit")
        self._action(m_edit, "Undo", "Ctrl+Z", lambda: self.run_command("undo"))
        self._action(m_edit, "Redo", "Ctrl+Y", lambda: self.run_command("redo"))
        m_edit.addSeparator()
        self._action(m_edit, "Copy", "Ctrl+C", self._copy_selected)
        self._action(m_edit, "Paste", "Ctrl+V", self._paste)
        m_edit.addSeparator()
        self._action(m_edit, "Delete", None, self._delete_selected)
        self._action(m_edit, "Select All", "Ctrl+A",
                     lambda: self.run_command("selall"))
        self._action(m_edit, "Select None", None,
                     lambda: self.run_command("selnone"))
        self._action(m_edit, "Invert Selection", None,
                     lambda: self.run_command("invert"))
        m_edit.addSeparator()
        self._action(m_edit, "Control Points On", "F10",
                     lambda: self.run_command("pointson"))
        self._action(m_edit, "Control Points Off", "F11",
                     lambda: self.run_command("pointsoff"))

        m_view = mb.addMenu("&View")
        self._action(m_view, "Top", "F1", lambda: self.run_command("top"))
        self._action(m_view, "Front", "F2", lambda: self.run_command("front"))
        self._action(m_view, "Right", "F3", lambda: self.run_command("right"))
        self._action(m_view, "Perspective", "F4",
                     lambda: self.run_command("perspective"))
        m_view.addSeparator()
        self._action(m_view, "Zoom Extents", "Ctrl+E",
                     lambda: self.run_command("zoomextents"))
        m_view.addSeparator()
        self._action(m_view, "Wireframe", None,
                     lambda: self.run_command("wireframe"))
        self._action(m_view, "Shaded", None,
                     lambda: self.run_command("shaded"))
        self._action(m_view, "Ghosted", None,
                     lambda: self.run_command("ghosted"))
        self._action(m_view, "Toggle Grid", "F7",
                     lambda: self.run_command("grid"))

        m_help = mb.addMenu("&Help")
        self._action(m_help, "Commands", None, self._show_commands)
        self._action(m_help, "About", None, self._about)

    def _action(self, menu, label, shortcut, fn):
        act = QAction(label, self)
        if shortcut:
            act.setShortcut(QKeySequence(shortcut))
        act.triggered.connect(lambda checked=False: fn())
        menu.addAction(act)
        return act

    # ------------------------------------------------------------- commanding

    def run_command(self, name: str):
        self.processor.run(name)
        self.command_line.focus()

    def _on_submit(self, text: str):
        text = text.strip()
        if self.processor.busy:
            self.processor.provide_text(text)
            return
        if not text:
            if self.processor.last_command:
                self.processor.run(self.processor.last_command)
            return
        self.processor.run(text.split()[0])

    def _cancel(self):
        if self.processor.busy:
            self.processor.cancel()
        else:
            self.selection.clear()
        self.viewport.set_point_mode(False)
        self.command_line.set_prompt("Command")

    def _sync_command_state(self):
        req = self.processor.request
        self.command_line.set_prompt(self.processor.prompt_text())
        if isinstance(req, PointReq):
            self.viewport.set_point_mode(True)
            self._refresh_rubber(None)
        else:
            self.viewport.set_point_mode(False)
            self.viewport.set_preview(None)
        self._update_status()

    def _on_object_clicked(self, obj_id: str, modifiers):
        if isinstance(self.processor.request, SelectReq):
            self.processor.click_object(obj_id)
            return
        additive = bool(modifiers & (Qt.KeyboardModifier.ShiftModifier
                                     | Qt.KeyboardModifier.ControlModifier))
        if additive:
            self.selection.toggle(obj_id)
        else:
            self.selection.set([obj_id])

    def _on_empty_clicked(self, modifiers):
        if isinstance(self.processor.request, SelectReq):
            return
        additive = bool(modifiers & (Qt.KeyboardModifier.ShiftModifier
                                     | Qt.KeyboardModifier.ControlModifier))
        if not additive:
            self.selection.clear()

    def _on_box_selected(self, ids, modifiers):
        if isinstance(self.processor.request, SelectReq):
            self.processor.box_objects(ids)
            return
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            remaining = [i for i in self.selection.ids if i not in ids]
            self.selection.set(remaining)
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            merged = self.selection.ids + [i for i in ids
                                           if i not in self.selection.ids]
            self.selection.set(merged)
        else:
            self.selection.set(ids)

    def _on_point_picked(self, point):
        if isinstance(self.processor.request, PointReq):
            self.ctx.last_point = point
            self.processor.provide(point)

    def _on_mouse_world(self, point):
        self._refresh_rubber(point)

    def _refresh_rubber(self, cursor):
        req = self.processor.request
        if not isinstance(req, PointReq):
            return
        markers = []
        segs = []
        pts = list(req.rubber_pts or [])
        if req.rubber_from is not None:
            pts = [req.rubber_from]
        if pts:
            markers = list(pts)
            chain = pts + ([cursor] if cursor is not None else [])
            if len(chain) >= 2:
                arr = np.asarray(chain, np.float32)
                segs = np.stack([arr[:-1], arr[1:]], axis=1)
        self.viewport.set_preview(segs if len(segs) else None, markers)

    def _delete_selected(self):
        if self.selection.ids and not self.processor.busy:
            self.run_command("delete")

    def _copy_selected(self):
        objs = self.selection.objects()
        if not objs:
            return
        self._clipboard = [(o.name, o.shape, o.layer_id) for o in objs]
        self.command_line.echo(f"Copied {len(objs)} object(s).")

    def _paste(self):
        clip = getattr(self, "_clipboard", None)
        if not clip:
            return
        from .core import geometry as g
        self.history.checkpoint("paste")
        pasted = []
        for name, shape, layer_id in clip:
            lid = layer_id if layer_id in {
                l.id for l in self.scene.layers.all()} else None
            pasted.append(self.scene.add(g.copy_shape(shape), layer_id=lid))
        self.selection.set([o.id for o in pasted])
        self.command_line.echo(f"Pasted {len(pasted)} object(s).")

    # ------------------------------------------------------------ file dialogs

    _FILTERS = ("Serpentine (*.serp);;STEP (*.step *.stp);;"
                "Wavefront OBJ (*.obj)")

    def _file_new(self):
        if self.scene.all():
            ret = QMessageBox.question(self, "New", "Clear the scene?")
            if ret != QMessageBox.StandardButton.Yes:
                return
        self.history.checkpoint("new")
        self.scene.clear()
        self.ctx.current_path = None
        self.command_line.echo("New document.")

    def _file_open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open", "",
                                              self._FILTERS)
        if not path:
            return
        try:
            self.history.checkpoint("open")
            fileio.import_file(self.scene, path)
            if path.endswith(".serp"):
                self.ctx.current_path = path
            self.command_line.echo(
                f"Opened {path}: {len(self.scene.all())} object(s).")
            self.viewport.zoom_extents()
        except Exception as exc:                              # noqa: BLE001
            self.history.discard_checkpoint()
            QMessageBox.warning(self, "Open failed", str(exc))

    def _file_save(self, force_dialog: bool = False):
        path = self.ctx.current_path
        if force_dialog or not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save", "untitled.serp", "Serpentine (*.serp)")
            if not path:
                return
            if not path.endswith(".serp"):
                path += ".serp"
        try:
            fileio.export_file(self.scene, path)
            self.ctx.current_path = path
            self.command_line.echo(f"Saved {path}")
        except Exception as exc:                              # noqa: BLE001
            QMessageBox.warning(self, "Save failed", str(exc))

    def _file_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import", "",
                                              self._FILTERS)
        if not path:
            return
        try:
            self.history.checkpoint("import")
            n = fileio.import_file(self.scene, path)
            self.command_line.echo(f"Imported {n} object(s).")
            self.viewport.zoom_extents()
        except Exception as exc:                              # noqa: BLE001
            self.history.discard_checkpoint()
            QMessageBox.warning(self, "Import failed", str(exc))

    def _file_export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export", "",
                                              self._FILTERS)
        if not path:
            return
        try:
            ids = self.selection.ids or None
            fileio.export_file(self.scene, path, only_ids=ids)
            scope = "selection" if ids else "scene"
            self.command_line.echo(f"Exported {scope} to {path}")
        except Exception as exc:                              # noqa: BLE001
            QMessageBox.warning(self, "Export failed", str(exc))

    # ------------------------------------------------------------------ misc

    def _show_commands(self):
        names = ", ".join(c.name for c in cmd_pkg.all_commands())
        self.command_line.echo(f"Commands: {names}")

    def _about(self):
        QMessageBox.about(
            self, "About Serpentine",
            "<b>Serpentine</b> — open-source NURBS surface modeller.<br>"
            "OpenCASCADE geometry kernel · Qt · MCP-enabled.<br>"
            "Named for the serpentine stone of Zimbabwean Shona sculpture.")

    def _update_status(self):
        n = len(self.scene.all())
        sel = len(self.selection.ids)
        mode = self.viewport.display_mode
        layer = self.scene.layers.current.name
        self.statusBar().showMessage(
            f"{n} object(s)  ·  {sel} selected  ·  layer: {layer}  ·  "
            f"{mode}  ·  MMB orbit / Shift+MMB pan / scroll zoom")
        path = getattr(self.ctx, "current_path", None)
        name = os.path.basename(path) if path else "untitled"
        self.setWindowTitle(f"{name} — {APP_TITLE}")

    def keyPressEvent(self, ev):
        # fallback for env without a WM where QAction shortcuts don't fire
        if ev.modifiers() & Qt.KeyboardModifier.ControlModifier:
            handlers = {
                Qt.Key.Key_C: self._copy_selected,
                Qt.Key.Key_V: self._paste,
                Qt.Key.Key_A: lambda: self.run_command("selall"),
                Qt.Key.Key_Z: lambda: self.run_command("undo"),
                Qt.Key.Key_Y: lambda: self.run_command("redo"),
            }
            fn = handlers.get(ev.key())
            if fn:
                fn()
                return
        if ev.key() == Qt.Key.Key_F10:
            self.run_command("pointson")
            return
        if ev.key() == Qt.Key.Key_F11:
            self.run_command("pointsoff")
            return
        # any printable key focuses the command line (Rhino behaviour)
        text = ev.text()
        if text and text.isprintable() and not self.command_line.input.hasFocus():
            self.command_line.focus()
            self.command_line.input.insert(text)
            return
        if ev.key() == Qt.Key.Key_Delete:
            self._delete_selected()
            return
        if ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if not self.processor.busy and self.processor.last_command:
                self.run_command(self.processor.last_command)
                return
        super().keyPressEvent(ev)


from PySide6.QtWidgets import QWidget


class _EmptyTitleBar(QWidget):
    """Zero-height title bar to hide the command dock header."""
    def __init__(self):
        super().__init__()
        self.setFixedHeight(0)


def main():
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    set_default_gl_format()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setStyleSheet(theme.QSS)
    window = MainWindow()

    # RPC bridge for the MCP server (unless disabled)
    if os.environ.get("SERP_NO_RPC") != "1":
        from .rpc import RpcServer
        window._rpc = RpcServer(window)
        window._rpc.start()

    window.show()

    for arg in app.arguments()[1:]:
        if not arg.startswith("-") and os.path.exists(arg):
            try:
                fileio.import_file(window.scene, arg)
                if arg.endswith(".serp"):
                    window.ctx.current_path = os.path.abspath(arg)
                window.command_line.echo(
                    f"Opened {arg}: {len(window.scene.all())} object(s).")
                window.viewport.zoom_extents()
            except Exception as exc:                          # noqa: BLE001
                window.command_line.echo(f"Could not open {arg}: {exc}")
            break
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
