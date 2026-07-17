"""Serpentine3D main application."""

from __future__ import annotations

import os
import signal
import sys

import numpy as np
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QMainWindow, QMessageBox,
    QToolBar, QVBoxLayout, QWidget,
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

APP_TITLE = "Serpentine3D"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1440, 900)

        # core state
        from .utils.config import Config
        self.cfg = Config()
        self.scene = Scene()
        from .utils.units import UNITS
        default_units = self.cfg.get("default_units", default="mm")
        if default_units in UNITS:
            self.scene.units = default_units
        self.selection = SelectionManager(self.scene)
        self.history = History(self.scene)

        # widgets
        from PySide6.QtWidgets import QTabBar
        self.viewport = Viewport(self.scene, self.selection, config=self.cfg)
        self.space_tabs = QTabBar()
        self.space_tabs.setExpanding(False)
        self.space_tabs.setDrawBase(False)
        self.space_tabs.setStyleSheet(
            "QTabBar::tab { padding: 4px 14px; background: #2b2c30;"
            " border: 1px solid #1b1c1f; border-bottom: none; }"
            "QTabBar::tab:selected { background: #4a3f28; color: #f0d9a8; }")
        self._tabs_updating = False
        self.space_tabs.currentChanged.connect(self._space_tab_changed)
        from PySide6.QtWidgets import QGridLayout
        self.aux_viewports: list = []           # Top/Front/Right in quad mode
        self.dock_viewports: list = []          # user-created dockable panes
        self._active_vp = self.viewport
        self._view_grid = QWidget()
        grid = QGridLayout(self._view_grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        grid.addWidget(self.viewport, 0, 0, 2, 2)
        grid.setRowStretch(0, 1)
        grid.setRowStretch(1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._view_grid, 1)
        central_layout.addWidget(self.space_tabs)
        self.setCentralWidget(central)

        from .ui.osnap_bar import OsnapBar
        self.command_line = CommandLine()
        self.osnap_bar = OsnapBar(self.viewport, self.cfg)
        cmd_container = QWidget()
        cmd_layout = QVBoxLayout(cmd_container)
        cmd_layout.setContentsMargins(0, 0, 0, 0)
        cmd_layout.setSpacing(0)
        cmd_layout.addWidget(self.command_line)
        cmd_layout.addWidget(self.osnap_bar)
        cmd_dock = QDockWidget("Command", self)
        cmd_dock.setObjectName("commandDock")
        cmd_dock.setWidget(cmd_container)
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
        self._ai_dock = None                # created on first use

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
        self.command_line.optionClicked.connect(self._on_option_chip)
        self.command_line.input.textEdited.connect(self._live_preview)
        self._wire_viewport(self.viewport)
        self.scene.add_listener(self._update_status)
        self.selection.add_listener(self._update_status)
        self.scene.add_listener(self._refresh_space_tabs)
        self._refresh_space_tabs()

        self._build_toolbar()
        self._build_menus()
        self._user_shortcuts: list = []
        self.apply_user_aliases()
        self.apply_user_shortcuts()

        # autosave every N seconds (config), crash recovery in main()
        from .utils.autosave import AutosaveManager, DEFAULT_INTERVAL_SEC
        autosave_dir = os.environ.get("SERP3D_AUTOSAVE_DIR")
        self.autosave = (AutosaveManager(self.scene, autosave_dir)
                         if autosave_dir else AutosaveManager(self.scene))
        self._saved_revision = self.scene.revision
        interval = int(self.cfg.get("autosave_interval_sec",
                                    default=DEFAULT_INTERVAL_SEC))
        if interval > 0:
            self._autosave_timer = QTimer(self)
            self._autosave_timer.setInterval(interval * 1000)
            self._autosave_timer.timeout.connect(self._autosave_tick)
            self._autosave_timer.start()

        from .ui.spacemouse import SpaceMouseNavigator
        self.spacemouse = SpaceMouseNavigator(self)

        self._update_status()
        self.command_line.echo("Serpentine3D — type a command to begin "
                               "(line, circle, box, extrude, loft, ...)")
        self.command_line.focus()

    @staticmethod
    def _pane_alive(vp) -> bool:
        """Not explicitly hidden, and its dock (if any) not closed.
        Unlike isVisible this stays true in headless/never-shown windows."""
        parent = vp.parentWidget()
        return not vp.isHidden() and (parent is None
                                      or not parent.isHidden())

    @property
    def active_viewport(self):
        vp = self._active_vp
        if vp is not self.viewport and not self._pane_alive(vp):
            self._active_vp = self.viewport      # its dock was closed
        return self._active_vp

    def _set_active_viewport(self, vp):
        if vp is self._active_vp:
            return
        self._active_vp = vp
        self.ctx.viewport = vp                   # commands act on this pane
        self._refresh_space_tabs()

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.MouseButtonPress \
                and isinstance(obj, Viewport):
            self._set_active_viewport(obj)
        return super().eventFilter(obj, ev)

    def new_viewport_dock(self, area: str = "Right", space: str = "model"):
        """A fully live extra viewport in a dockable/floatable panel."""
        vp = Viewport(self.scene, self.selection, self.cfg)
        vp.cplane = self.viewport.cplane
        vp.camera.azimuth = self.viewport.camera.azimuth + 0.4
        vp.camera.elevation = self.viewport.camera.elevation
        vp.camera.target = self.viewport.camera.target.copy()
        vp.camera.distance = self.viewport.camera.distance
        vp.setMinimumSize(360, 260)   # a size-hint-less GL widget would
        self._wire_viewport(vp)        # otherwise collapse the dock to 0px
        self.dock_viewports.append(vp)
        dock = QDockWidget("Viewport", self)
        dock.setObjectName(f"viewportDock{len(self.dock_viewports)}")
        dock.setWidget(vp)
        areas = {"Right": Qt.DockWidgetArea.RightDockWidgetArea,
                 "Left": Qt.DockWidgetArea.LeftDockWidgetArea,
                 "Top": Qt.DockWidgetArea.TopDockWidgetArea,
                 "Bottom": Qt.DockWidgetArea.BottomDockWidgetArea}
        self.addDockWidget(areas.get(area,
                                     Qt.DockWidgetArea.RightDockWidgetArea),
                           dock)
        if area == "Floating":
            dock.setFloating(True)
            dock.resize(860, 620)
        if space != "model":
            vp.set_space(space)
        self._update_viewport_dock_title(vp)
        vp.zoom_extents()
        self._set_active_viewport(vp)
        return vp

    def show_ai_panel(self):
        """Open (or reveal) the AI assistant dock."""
        if self._ai_dock is None:
            from .ai.panel import AiPanel
            panel = AiPanel(self)
            dock = QDockWidget("Assistant", self)
            dock.setObjectName("aiDock")
            dock.setWidget(panel)
            dock.setMinimumWidth(320)
            self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
            self._ai_dock = dock
        self._ai_dock.show()
        self._ai_dock.raise_()
        panel = self._ai_dock.widget()
        if panel.input_row.isVisible():
            panel.input.setFocus()
        return panel

    def _update_viewport_dock_title(self, vp):
        dock = vp.parentWidget()
        if not isinstance(dock, QDockWidget):
            return
        if vp.space == "model":
            label = "Model"
        else:
            lay = next((l for l in self.scene.layouts if l.id == vp.space),
                       None)
            label = lay.name if lay else "Layout"
        dock.setWindowTitle(f"{label} viewport")

    def _wire_viewport(self, vp):
        vp.installEventFilter(self)
        vp.displayModeChanged.connect(self._update_status)
        vp.history = self.history
        vp.objectClicked.connect(self._on_object_clicked)
        vp.emptyClicked.connect(self._on_empty_clicked)
        vp.boxSelected.connect(self._on_box_selected)
        vp.pointPicked.connect(self._on_point_picked)
        vp.mouseWorldMoved.connect(self._on_mouse_world)
        vp.cvEditBegan.connect(
            lambda: self.history.checkpoint("edit control point"))
        vp.escapePressed.connect(self._cancel)
        vp.enterShortcut.connect(self._rmb_enter)

    def all_viewports(self) -> list:
        return ([self.viewport]
                + [v for v in self.aux_viewports if self._pane_alive(v)]
                + [v for v in self.dock_viewports if self._pane_alive(v)])

    def set_view_layout(self, mode: str):
        """'single' or 'quad' (Top / Front / Right around Perspective)."""
        grid = self._view_grid.layout()
        if mode == "quad" and not self.aux_viewports:
            import math
            angles = [(-math.pi / 2, math.radians(89.9)),   # Top
                      (-math.pi / 2, 0.0),                  # Front
                      (0.0, 0.0)]                           # Right
            for az, el in angles:
                aux = Viewport(self.scene, self.selection, self.cfg)
                aux.camera.azimuth = az
                aux.camera.elevation = el
                aux.cplane = self.viewport.cplane
                self._wire_viewport(aux)
                self.aux_viewports.append(aux)
        if mode == "quad":
            grid.removeWidget(self.viewport)
            grid.addWidget(self.aux_viewports[0], 0, 0)   # top view
            grid.addWidget(self.viewport, 0, 1)           # perspective
            grid.addWidget(self.aux_viewports[1], 1, 0)   # front
            grid.addWidget(self.aux_viewports[2], 1, 1)   # right
            for aux in self.aux_viewports:
                aux.show()
                aux.zoom_extents()
        else:
            for aux in self.aux_viewports:
                grid.removeWidget(aux)
                aux.hide()
            grid.removeWidget(self.viewport)
            grid.addWidget(self.viewport, 0, 0, 2, 2)
        self.viewport.update()

    # ------------------------------------------------------------ UI assembly

    def _build_toolbar(self):
        from .ui.icons import command_icon
        bar = QToolBar("Tools")
        bar.setObjectName("toolPalette")
        bar.setOrientation(Qt.Orientation.Vertical)
        bar.setMovable(False)
        groups = [
            [("Line", "line"), ("Polyline", "polyline"), ("Curve", "curve"),
             ("Circle", "circle"), ("Arc", "arc"), ("Rectangle", "rectangle")],
            [("Extrude", "extrude"), ("Revolve", "revolve"),
             ("Loft", "loft"), ("Planar surface", "planarsrf"),
             ("Sweep 1 rail", "sweep1"), ("Sweep 2 rails", "sweep2")],
            [("Box", "box"), ("Sphere", "sphere"), ("Cylinder", "cylinder"),
             ("Torus", "torus")],
            [("Move", "move"), ("Copy", "copy"), ("Rotate", "rotate"),
             ("Scale", "scale"), ("Mirror", "mirror")],
            [("Boolean union", "booleanunion"),
             ("Boolean difference", "booleandifference"),
             ("Boolean intersection", "booleanintersection")],
            [("Trim", "trim"), ("Split", "split"), ("Offset", "offset"),
             ("Fillet", "fillet")],
            [("Join", "join"), ("Explode", "explode"),
             ("Control points", "pointson"), ("Delete", "delete")],
        ]
        for gi, group in enumerate(groups):
            if gi:
                bar.addSeparator()
            for label, command in group:
                icon = command_icon(command)
                act = QAction(label, self)
                if icon is not None:
                    act.setIcon(icon)
                act.setToolTip(f"{label}  ({command})")
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
        self._action(m_view, "Rendered", None,
                     lambda: self.run_command("rendered"))
        self._action(m_view, "Technical", None,
                     lambda: self.run_command("technical"))
        m_view.addSeparator()
        self._action(m_view, "AI Assistant", "Ctrl+Shift+A",
                     self.show_ai_panel)
        m_view.addSeparator()
        m_ports = m_view.addMenu("Viewports")
        self._action(m_ports, "New Viewport...", None,
                     lambda: self.run_command("newviewport"))
        self._action(m_ports, "Floating Viewport", None,
                     lambda: self.run_command("floatviewport"))
        self._action(m_ports, "Four Viewports", None,
                     lambda: self.run_command("4view"))
        self._action(m_ports, "Single Viewport", None,
                     lambda: self.run_command("1view"))
        m_view.addSeparator()
        self._action(m_view, "Toggle Grid", "F7",
                     lambda: self.run_command("grid"))

        m_draft = mb.addMenu("&Drafting")
        self._action(m_draft, "New Layout...", None,
                     lambda: self.run_command("layout"))
        self._action(m_draft, "Place Detail View...", None,
                     lambda: self.run_command("detail"))
        self._action(m_draft, "Text Note...", None,
                     lambda: self.run_command("text"))
        self._action(m_draft, "Linear Dimension...", None,
                     lambda: self.run_command("dim"))
        m_draft.addSeparator()
        self._action(m_draft, "Make2D", None,
                     lambda: self.run_command("make2d"))
        self._action(m_draft, "Technical Display", None,
                     lambda: self.run_command("technical"))
        m_draft.addSeparator()
        self._action(m_draft, "Export PDF...", "Ctrl+P",
                     lambda: self.run_command("exportpdf"))

        m_tools = mb.addMenu("&Tools")
        self._action(m_tools, "Python Console", "Ctrl+`",
                     self._toggle_console)
        self._action(m_tools, "Settings...", "Ctrl+,", self._show_settings)

        self._plugins_menu = mb.addMenu("&Plugins")
        self._action(self._plugins_menu, "Plugin folder...", None,
                     self._open_plugin_dir)
        self._plugins_menu.addSeparator()

        m_help = mb.addMenu("&Help")
        self._action(m_help, "Commands", None, self._show_commands)
        self._action(m_help, "About", None, self._about)

    def plugin_menu_action(self, label: str, fn):
        self._action(self._plugins_menu, label, None, fn)

    def _open_plugin_dir(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from .plugins import plugin_dir
        d = plugin_dir()
        os.makedirs(d, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(d))  # portable

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
        for vp in self.all_viewports():
            vp.set_point_mode(False)
        self.command_line.set_prompt("Command")

    def show_help_browser(self):
        from .ui.help_browser import HelpBrowser
        if getattr(self, "_help_browser", None) is None:
            self._help_browser = HelpBrowser(self)
        self._help_browser.show()
        self._help_browser.raise_()

    def _rmb_enter(self):
        """Right-click: Enter while busy; when idle, the first click after
        a command ends is the 'done' gesture, the next one repeats."""
        if not self.processor.busy and getattr(self, "_rmb_absorb", False):
            self._rmb_absorb = False
            return
        self._on_submit("")

    def _on_option_chip(self, name: str):
        self.processor.set_option(name)
        self._live_preview(self.command_line.input.text())
        self.command_line.focus()

    def _live_preview(self, text: str):
        req = self.processor.request
        if req is not None and getattr(req, "preview_fn", None) and \
                text.strip():
            self.viewport.set_ghost(self.processor.preview_shape(text))
        else:
            self.viewport.set_ghost(None)

    def _sync_command_state(self):
        busy = self.processor.busy
        if getattr(self, "_prev_busy", False) and not busy:
            self._rmb_absorb = True          # one inert right-click
        elif busy:
            self._rmb_absorb = False
        self._prev_busy = busy
        req = self.processor.request
        self.command_line.set_prompt(self.processor.prompt_text())
        self.command_line.set_options(self.processor.option_chips())
        self.viewport.set_ghost(None)
        if isinstance(req, PointReq):
            base = req.rubber_from
            if base is None and req.rubber_pts:
                base = req.rubber_pts[-1]
            for vp in self.all_viewports():
                vp.set_point_mode(True)
                vp.snap_base = base
                vp.point_axis = req.axis_lock
            self._refresh_rubber(None)
        else:
            for vp in self.all_viewports():
                vp.set_point_mode(False)
                vp.snap_base = None
                vp.point_axis = None
                vp.set_preview(None)
        self.osnap_bar.refresh()
        self._update_status()

    def _on_object_clicked(self, obj_id: str, modifiers):
        self._rmb_absorb = False             # fresh pick: next RMB repeats
        if isinstance(self.processor.request, SelectReq):
            self.processor.click_object(obj_id)
            return
        additive = bool(modifiers & (Qt.KeyboardModifier.ShiftModifier
                                     | Qt.KeyboardModifier.ControlModifier))
        ids = self.scene.expand_group_ids([obj_id])
        if additive:
            if self.selection.is_selected(obj_id):
                self.selection.set([i for i in self.selection.ids
                                    if i not in ids])
            else:
                self.selection.set(self.selection.ids
                                   + [i for i in ids
                                      if i not in self.selection.ids])
        else:
            self.selection.set(ids)

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
        ids = self.scene.expand_group_ids(ids)
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
        req = self.processor.request
        if isinstance(req, PointReq) and getattr(req, "preview_fn", None):
            # ghost of the pending result under the cursor, ~30Hz cap
            from PySide6.QtCore import QElapsedTimer
            timer = getattr(self, "_ghost_timer", None)
            due = timer is None or timer.elapsed() >= 33
            if timer is None:
                timer = self._ghost_timer = QElapsedTimer()
            if due:
                timer.restart()
                ghost = self.processor.preview_for(point)
                for vp in self.all_viewports():
                    vp.set_ghost(ghost)

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

    _FILTERS = ("Serpentine3D (*.serp);;STEP (*.step *.stp);;"
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
        self.mark_saved()

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
            self.mark_saved()
        except Exception as exc:                              # noqa: BLE001
            self.history.discard_checkpoint()
            QMessageBox.warning(self, "Open failed", str(exc))

    def _file_save(self, force_dialog: bool = False):
        path = self.ctx.current_path
        if force_dialog or not path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save", "untitled.serp", "Serpentine3D (*.serp)")
            if not path:
                return
            if not path.endswith(".serp"):
                path += ".serp"
        try:
            fileio.export_file(self.scene, path)
            self.ctx.current_path = path
            self.command_line.echo(f"Saved {path}")
            self.mark_saved()
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

    # ------------------------------------------------------------- autosave

    @property
    def dirty(self) -> bool:
        return self.scene.revision != self._saved_revision

    def mark_saved(self):
        self._saved_revision = self.scene.revision
        self.autosave.set_doc_path(getattr(self.ctx, "current_path", None))
        self._update_status()

    def _autosave_tick(self):
        if self.autosave.maybe_autosave():
            self.statusBar().showMessage("Autosaved.", 2500)

    def closeEvent(self, ev):
        if self.dirty and self.scene.all():
            ret = QMessageBox.question(
                self, "Unsaved changes",
                "Save changes before closing?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel)
            if ret == QMessageBox.StandardButton.Cancel:
                ev.ignore()
                return
            if ret == QMessageBox.StandardButton.Save:
                self._file_save()
                if self.dirty:          # save was cancelled
                    ev.ignore()
                    return
        self.autosave.clean_exit()
        super().closeEvent(ev)

    def offer_recovery(self):
        """Restore the newest crashed session, if any (called at startup)."""
        candidates = self.autosave.find_recoverable()
        if not candidates:
            return
        entry = candidates[0]
        if os.environ.get("SERP3D_AUTORESTORE") != "1":
            import datetime
            when = datetime.datetime.fromtimestamp(
                entry["mtime"]).strftime("%H:%M")
            doc = entry.get("doc_path") or "an unsaved document"
            ret = QMessageBox.question(
                self, "Recover unsaved work?",
                f"Serpentine3D did not close cleanly last time.\n\n"
                f"An autosave of {doc} from {when} was found. Restore it?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No)
            if ret != QMessageBox.StandardButton.Yes:
                self.autosave.discard(entry)
                return
        try:
            doc_path = self.autosave.recover(entry)
            self.ctx.current_path = doc_path
            self.autosave.set_doc_path(doc_path)
            self.command_line.echo(
                f"Recovered {len(self.scene.all())} object(s) from the "
                "previous session's autosave.")
            self.viewport.zoom_extents()
            self._update_status()
        except Exception as exc:                              # noqa: BLE001
            QMessageBox.warning(self, "Recovery failed", str(exc))

    # ---------------------------------------------------------- space tabs

    def _refresh_space_tabs(self):
        self._tabs_updating = True
        want = [("model", "Model")] + [(lay.id, lay.name)
                                       for lay in self.scene.layouts]
        while self.space_tabs.count() > len(want):
            self.space_tabs.removeTab(self.space_tabs.count() - 1)
        while self.space_tabs.count() < len(want):
            self.space_tabs.addTab("")
        current_index = 0
        for i, (space_id, label) in enumerate(want):
            self.space_tabs.setTabText(i, label)
            self.space_tabs.setTabData(i, space_id)
            if space_id == self.active_viewport.space:
                current_index = i
        if self.viewport.space != "model" and \
                self.viewport.space not in [w[0] for w in want]:
            # active layout was deleted (e.g. via undo)
            self.viewport.set_space("model")
            current_index = 0
        self.space_tabs.setCurrentIndex(current_index)
        self._tabs_updating = False

    def _space_tab_changed(self, index: int):
        if self._tabs_updating or index < 0:
            return
        space_id = self.space_tabs.tabData(index)
        if space_id and space_id != self.active_viewport.space:
            self.switch_space(space_id)

    def switch_space(self, space_id: str):
        if self.processor.busy:
            self.processor.cancel()
        vp = self.active_viewport
        vp.set_space(space_id)
        self._update_viewport_dock_title(vp)
        self._refresh_space_tabs()
        if space_id == "model":
            self.command_line.echo("Model space.")
        else:
            lay = next((l for l in self.scene.layouts
                        if l.id == space_id), None)
            if lay:
                self.command_line.echo(
                    f"Layout '{lay.name}' — 'detail' places a model view, "
                    "'text'/'dim' annotate, double-click a detail to enter "
                    "it.")
        self._update_status()

    # ------------------------------------------------------------- settings

    def _toggle_console(self):
        if not hasattr(self, "_console_dock"):
            from .ui.console import PythonConsole
            self._console_dock = QDockWidget("Python", self)
            self._console_dock.setObjectName("pythonDock")
            self._console_dock.setWidget(PythonConsole(self))
            self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea,
                               self._console_dock)
        else:
            self._console_dock.setVisible(
                not self._console_dock.isVisible())

    def _show_settings(self):
        from .ui.settings_dialog import SettingsDialog
        SettingsDialog(self).exec()

    def apply_user_aliases(self):
        from .commands import base as cmd_base
        current = self.cfg.get("aliases", default={}) or {}
        previous = getattr(self, "_applied_aliases", {})
        for alias in previous:
            if alias not in current:
                cmd_base.remove_alias(alias)
        for alias, target in current.items():
            cmd_base.add_alias(alias, target)
        self._applied_aliases = dict(current)

    def apply_user_shortcuts(self):
        from PySide6.QtGui import QShortcut
        for sc in self._user_shortcuts:
            sc.setParent(None)
            sc.deleteLater()
        self._user_shortcuts = []
        self._user_shortcut_keys = set()
        wanted = {}
        for key, command in (self.cfg.get("shortcuts",
                                          default={}) or {}).items():
            seq = QKeySequence(key)
            if seq.isEmpty():
                continue
            wanted[seq.toString()] = command
        # the user's keys win: strip clashing built-in menu shortcuts
        for act in self.findChildren(QAction):
            if not act.shortcut().isEmpty() \
                    and act.shortcut().toString() in wanted:
                act.setShortcut(QKeySequence())
        for key_text, command in wanted.items():
            sc = QShortcut(QKeySequence(key_text), self)
            sc.activated.connect(
                lambda c=command: self.run_command(c))
            self._user_shortcuts.append(sc)
            self._user_shortcut_keys.add(key_text)

    # ------------------------------------------------------------------ misc

    def _show_commands(self):
        names = ", ".join(c.name for c in cmd_pkg.all_commands())
        self.command_line.echo(f"Commands: {names}")

    def _about(self):
        QMessageBox.about(
            self, "About Serpentine3D",
            "<b>Serpentine3D</b> — open-source NURBS surface modeller.<br>"
            "OpenCASCADE geometry kernel · Qt · MCP-enabled.<br>"
            "Named for the serpentine stone of Zimbabwean Shona sculpture.")

    def _update_status(self):
        n = len(self.scene.all())
        sel = len(self.selection.ids)
        mode = self.viewport.display_mode
        layer = self.scene.layers.current.name
        filt = ""
        if self.selection.filter_active and self.selection.filter_kinds:
            filt = ("  ·  filter: "
                    + ", ".join(sorted(self.selection.filter_kinds)))
        self.statusBar().showMessage(
            f"{n} object(s)  ·  {sel} selected  ·  layer: {layer}  ·  "
            f"{mode}  ·  units: {self.scene.units}{filt}")
        path = getattr(self.ctx, "current_path", None)
        name = os.path.basename(path) if path else "untitled"
        star = "*" if getattr(self, "autosave", None) and self.dirty else ""
        self.setWindowTitle(f"{name}{star} — {APP_TITLE}")

    def _match_user_shortcut(self, ev) -> bool:
        try:
            pressed = QKeySequence(ev.keyCombination())
        except Exception:
            return False
        for key, cmd in (self.cfg.get("shortcuts", default={}) or {}).items():
            seq = QKeySequence(key)
            if not seq.isEmpty() and seq.matches(pressed) == \
                    QKeySequence.SequenceMatch.ExactMatch:
                self.run_command(cmd)
                return True
        return False

    def keyPressEvent(self, ev):
        if self._match_user_shortcut(ev):
            return
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
        if ev.key() == Qt.Key.Key_F1 \
                and "F1" not in getattr(self, "_user_shortcut_keys", ()):
            self.show_help_browser()
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


def _selftest() -> int:
    """Verify a packaged install without opening a window: Qt platform
    plugin, OCCT kernel, and file I/O. Windowed executables on Windows
    have no console, so the report also goes to a file."""
    import tempfile
    lines = []
    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        qt_app = QApplication.instance() or QApplication([])
        lines.append(f"qt: {qt_app.platformName()}")
        from .core import geometry as g
        from .core.scene import Scene
        scene = Scene()
        obj = scene.add(g.make_box((0, 0, 0), 10, 10, 10), name="Box")
        scene.replace_shape(obj.id, g.fillet_edges(obj.shape, radius=1.0))
        with tempfile.TemporaryDirectory() as tmp:
            step = os.path.join(tmp, "selftest.step")
            fileio.export_file(scene, step)
            lines.append(f"step: {os.path.getsize(step)} bytes")
        vol = g.volume(scene.all()[0].shape)
        lines.append(f"volume: {vol:.1f}")
        ok = abs(vol - 975.6) < 1.0
        lines.append("SELFTEST OK" if ok else "SELFTEST FAILED: bad volume")
    except Exception as exc:                                  # noqa: BLE001
        ok = False
        lines.append(f"SELFTEST FAILED: {type(exc).__name__}: {exc}")
    report = "\n".join(lines) + "\n"
    try:
        print(report, end="")
    except Exception:                                         # noqa: BLE001
        pass                        # windowed exe: stdout may be closed
    path = os.path.join(tempfile.gettempdir(), "serp3d-selftest.txt")
    with open(path, "w") as f:
        f.write(report)
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    set_default_gl_format()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    # GNOME matches windows to the launcher (icon, grouping, pinning)
    # by this name — must equal the installed serpentine3d.desktop
    app.setDesktopFileName("serpentine3d")
    app.setStyleSheet(theme.QSS)
    window = MainWindow()

    # RPC bridge for the MCP server (unless disabled)
    if os.environ.get("SERP3D_NO_RPC") != "1":
        from .rpc import RpcServer
        window._rpc = RpcServer(window)
        window._rpc.start()

    template = os.path.expanduser("~/.config/serpentine3d/template.serp")
    if os.path.exists(template):
        try:
            fileio.import_file(window.scene, template)
            window.mark_saved()
            window.command_line.echo("Started from template.serp.")
        except Exception:                                     # noqa: BLE001
            pass

    from .plugins import load_plugins
    loaded = load_plugins(window)
    if loaded:
        window.command_line.echo("Plugins: " + ", ".join(loaded))

    window.show()
    window.offer_recovery()

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
