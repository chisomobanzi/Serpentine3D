"""Serpentine3D main application."""

from __future__ import annotations

import os
import signal
import sys

import numpy as np
from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QDockWidget, QFileDialog, QInputDialog, QMainWindow,
    QMessageBox, QProgressDialog, QToolBar, QVBoxLayout, QWidget,
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
from .ui.dialogs import untether
from .ui.layers_panel import LayersPanel
from .ui.properties import PropertiesPanel
from .ui.viewport import Viewport, set_default_gl_format

APP_TITLE = "Serpentine3D"


class MainWindow(QMainWindow):
    # emitted from the background update-check thread; handled on the main
    # thread so the notice is shown Qt-safely
    updateAvailable = Signal(object)

    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1440, 900)

        # core state
        self._pending_update = None
        self.updateAvailable.connect(self._on_update_available)
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
        self.aux_viewports: list = []           # Top/Front/Right in quad mode
        self.aux_docks: list = []               # their dock wrappers
        self.dock_viewports: list = []          # user-created dockable panes
        self._active_vp = self.viewport
        # Every viewport lives in a dock, so any of them — the main one
        # included — can be dragged out to float or re-docked. The central
        # widget collapses to nothing so the docks fill the whole window.
        self.setDockNestingEnabled(True)
        self._central_stub = QWidget()
        self._central_stub.setFixedSize(0, 0)
        self.setCentralWidget(self._central_stub)
        self._central_stub.hide()   # visible, it still reserves layout space
        self._primary_dock = self._dock_viewport(
            self.viewport, "Perspective", closable=False)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea,
                           self._primary_dock)

        from .ui.osnap_bar import OsnapBar
        self.command_line = CommandLine()
        self.osnap_bar = OsnapBar(self.viewport, self.cfg)
        cmd_container = QWidget()
        from PySide6.QtWidgets import QSizePolicy
        cmd_container.setSizePolicy(QSizePolicy.Policy.Expanding,
                                    QSizePolicy.Policy.Fixed)   # never balloon
        cmd_layout = QVBoxLayout(cmd_container)
        cmd_layout.setContentsMargins(0, 0, 0, 0)
        cmd_layout.setSpacing(0)
        cmd_layout.addWidget(self._build_space_tab_row())   # tabs + "＋"
        cmd_layout.addWidget(self.command_line)
        cmd_layout.addWidget(self.osnap_bar)
        self._cmd_dock = QDockWidget("Command", self)
        self._cmd_dock.setObjectName("commandDock")
        self._cmd_dock.setWidget(cmd_container)
        self._cmd_dock.setFeatures(
            QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self._cmd_dock.setTitleBarWidget(_EmptyTitleBar())
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea,
                           self._cmd_dock)

        self.properties = PropertiesPanel(
            self.scene, self.selection, self.history,
            # a sheet's selection belongs to whichever pane is showing it
            viewport_source=lambda: self.active_viewport)
        self._prop_dock = QDockWidget("Properties", self)
        self._prop_dock.setObjectName("propertiesDock")
        self._prop_dock.setWidget(self.properties)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,
                           self._prop_dock)

        self.layers_panel = LayersPanel(self.scene, self.history)
        self._layer_dock = QDockWidget("Layers", self)
        self._layer_dock.setObjectName("layersDock")
        self._layer_dock.setWidget(self.layers_panel)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea,
                           self._layer_dock)
        # proportions are set post-show in _balance_docks (a pre-show
        # resizeDocks gets redistributed once the layout is realised)
        QTimer.singleShot(0, self._balance_docks)
        self._ai_dock = None                # created on first use
        self._restore_window()              # last session's layout, if any

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
        self.command_line.tabPressed.connect(self._toggle_direction_lock)
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
        self.properties.refresh()                # and so does the panel

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Type.MouseButtonPress \
                and isinstance(obj, Viewport):
            self._set_active_viewport(obj)
        return super().eventFilter(obj, ev)

    def _dock_viewport(self, vp, title: str, closable: bool = True):
        """Wrap a viewport in a floatable/movable QDockWidget so it can be
        torn off. Not closable for the primary — there's always one view."""
        dock = QDockWidget(title, self)
        self._dock_seq = getattr(self, "_dock_seq", 0) + 1
        dock.setObjectName(f"viewportDock{self._dock_seq}")
        feats = (QDockWidget.DockWidgetFeature.DockWidgetMovable
                 | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
        if closable:
            feats |= QDockWidget.DockWidgetFeature.DockWidgetClosable
        dock.setFeatures(feats)
        from PySide6.QtWidgets import QSizePolicy
        vp.setSizePolicy(QSizePolicy.Policy.Expanding,   # claim the leftover
                         QSizePolicy.Policy.Expanding)   # space, not the panels
        vp.setMinimumSize(200, 150)   # a hint-less GL widget collapses to 0px
        dock.setWidget(vp)
        return dock

    def _balance_docks(self):
        """Give the primary viewport the bulk of the window and keep the
        side panels + command strip compact. Runs once after show, when the
        dock layout is realised — unless last session's layout was restored,
        in which case the user already chose their widths and re-imposing
        280 px would undo them every launch (GitHub #5)."""
        if getattr(self, "_docks_restored", False):
            return
        w = max(self.width(), 800)
        self.resizeDocks([self._primary_dock, self._prop_dock],
                         [w - 300, 280], Qt.Orientation.Horizontal)
        # the command strip spans the bottom full-width, so resize it alone
        self.resizeDocks([self._cmd_dock], [96], Qt.Orientation.Vertical)

    def new_viewport_dock(self, area: str = "Right", space: str = "model"):
        """A fully live extra viewport in a dockable/floatable panel."""
        vp = Viewport(self.scene, self.selection, self.cfg)
        vp.cplane = self.viewport.cplane
        vp.camera.azimuth = self.viewport.camera.azimuth + 0.4
        vp.camera.elevation = self.viewport.camera.elevation
        vp.camera.target = self.viewport.camera.target.copy()
        vp.camera.distance = self.viewport.camera.distance
        self._wire_viewport(vp)
        self.dock_viewports.append(vp)
        dock = self._dock_viewport(vp, "Viewport", closable=True)
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
        vp.layoutSelectionChanged.connect(self._update_status)
        vp.layoutSelectionChanged.connect(self.properties.refresh)
        vp.history = self.history
        vp.objectClicked.connect(self._on_object_clicked)
        vp.emptyClicked.connect(self._on_empty_clicked)
        vp.boxSelected.connect(self._on_box_selected)
        vp.pointPicked.connect(self._on_point_picked)
        vp.detailEntered.connect(self._on_detail_entered)
        vp.mouseWorldMoved.connect(self._on_mouse_world)
        vp.cvEditBegan.connect(
            lambda: self.history.checkpoint("edit control point"))
        vp.escapePressed.connect(self._cancel)
        vp.tabPressed.connect(self._toggle_direction_lock)
        vp.enterShortcut.connect(self._rmb_enter)
        vp.popupRequested.connect(self._show_mmb_popup)
        vp.chordActivated.connect(self.run_command)

    def _show_palette(self):
        from .ui.palette import CommandPalette
        CommandPalette.popup(self, self.command_line.run_command)

    def _show_mmb_popup(self):
        """Middle-click popup: recent commands + staples (Rhino-style)."""
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        recent = self.command_line.recent_commands()
        for name in recent:
            menu.addAction(name, lambda n=name:
                           self.command_line.run_command(n))
        if recent:
            menu.addSeparator()
        for name in ("line", "circle", "extrude", "move", "zoomextents"):
            if name not in recent:
                menu.addAction(name, lambda n=name:
                               self.command_line.run_command(n))
        menu.addSeparator()
        menu.addAction("Command palette…", self._show_palette)
        menu.exec(QCursor.pos())

    def all_viewports(self) -> list:
        return ([self.viewport]
                + [v for v in self.aux_viewports if self._pane_alive(v)]
                + [v for v in self.dock_viewports if self._pane_alive(v)])

    def set_view_layout(self, mode: str):
        """'single' or 'quad' (Top / Front / Right alongside Perspective).
        With every viewport a dock, quad just shows three aux viewport docks
        tiled beside the primary — and you can drag them anywhere from there.
        """
        if mode == "quad" and not self.aux_docks:
            for title, view in (("Top", "top"), ("Front", "front"),
                                ("Right", "right")):
                aux = Viewport(self.scene, self.selection, self.cfg)
                aux.set_view(view)                 # named orthographic view
                aux.cplane = self.viewport.cplane
                aux.camera.target = self.viewport.camera.target.copy()
                aux.camera.distance = self.viewport.camera.distance
                self._wire_viewport(aux)
                self.aux_viewports.append(aux)
                self.aux_docks.append(self._dock_viewport(aux, title))
            top, front, right = self.aux_docks           # initial 2x2 tiling
            self.splitDockWidget(self._primary_dock, top,
                                 Qt.Orientation.Horizontal)   # persp | top
            self.splitDockWidget(self._primary_dock, front,
                                 Qt.Orientation.Vertical)     # persp / front
            self.splitDockWidget(top, right,
                                 Qt.Orientation.Vertical)     # top   / right
        if mode == "quad":
            for aux, dock in zip(self.aux_viewports, self.aux_docks):
                dock.show()
                aux.show()
                aux.zoom_extents()
            # split builds the 2x2 structure but leaves lopsided sizes;
            # even them out once the layout is realised
            QTimer.singleShot(0, self._equalize_quad)
        else:
            for dock in self.aux_docks:
                dock.hide()
        self.viewport.update()

    def _equalize_quad(self):
        """Make the quad an even 2x2 — equal columns and equal rows."""
        if len(self.aux_docks) != 3:
            return
        top, front, right = self.aux_docks
        h = Qt.Orientation.Horizontal
        v = Qt.Orientation.Vertical
        self.resizeDocks([self._primary_dock, top], [1000, 1000], h)  # columns
        self.resizeDocks([front, right], [1000, 1000], h)
        self.resizeDocks([self._primary_dock, front], [1000, 1000], v)  # rows
        self.resizeDocks([top, right], [1000, 1000], v)

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
        self._recent_menu = m_file.addMenu("Open Recent")
        self._rebuild_recent_menu()
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
        self._action(m_view, "Isometric", "F5",
                     lambda: self.run_command("isometric"))
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
        self._action(m_tools, "Command Palette...", "Ctrl+Shift+P",
                     self._show_palette)
        self._action(m_tools, "Python Console", "Ctrl+`",
                     self._toggle_console)
        self._action(m_tools, "Settings...", "Ctrl+,", self._show_settings)

        self._plugins_menu = mb.addMenu("&Plugins")
        self._action(self._plugins_menu, "Plugin folder...", None,
                     self._open_plugin_dir)
        self._plugins_menu.addSeparator()

        m_help = mb.addMenu("&Help")
        self._action(m_help, "Commands", None, self._show_commands)
        self._action(m_help, "Check for Updates…", None,
                     self._check_updates_manual)
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
        """Right-click acts as Enter (Rhino-style): if a command is typed at
        the prompt it runs that; mid-command it commits the typed value; on an
        empty prompt it repeats the last command.

        Every click, including the first one after a command ends. That one
        used to be swallowed on the grounds that it was the habitual click
        that finishes a command rather than a request for anything — but the
        click that finishes a command is taken by the command, and the one
        after it is a gesture somebody made on an idle prompt, where it has
        exactly one meaning.
        """
        # Route through the command line so a typed name/value is submitted
        # exactly as Enter would (history, clear, then run/provide/repeat).
        self.command_line.submit_input()

    def _on_option_chip(self, name: str):
        self.processor.set_option(name)
        self._live_preview(self.command_line.input.text())
        self.command_line.focus()

    def _toggle_direction_lock(self):
        """Tab while a point is wanted: freeze the direction, type a length.

        Only the viewport the cursor is in has a direction to freeze, so
        the lock belongs to that one rather than to all of them.
        """
        vp = self.active_viewport
        if vp.toggle_direction_lock():
            self.command_line.echo("Direction locked (Tab to release)")
        else:
            self.command_line.echo("Direction released")
        vp.update()

    def _live_preview(self, text: str):
        req = self.processor.request
        if req is not None and getattr(req, "preview_fn", None) and \
                text.strip():
            self.viewport.set_ghost(self.processor.preview_shape(text))
        else:
            self.viewport.set_ghost(None)

    def _sync_command_state(self):
        busy = self.processor.busy
        req = self.processor.request
        self.command_line.set_prompt(self.processor.prompt_text())
        self.command_line.set_options(self.processor.option_chips())
        # every pane, because a ghost is set on every pane: clearing one of
        # them leaves a preview on the others that no command owns any more
        for vp in self.all_viewports():
            vp.set_ghost(None)
        self.command_line.point_pending = isinstance(req, PointReq)
        # Only guess at command names at the "Command" prompt; mid-command the
        # words belong to the command, not to the registry.
        self.command_line.awaiting_command = not busy
        if isinstance(req, PointReq):
            base = req.rubber_from
            if base is None and req.rubber_pts:
                base = req.rubber_pts[-1]
            pending = list(req.rubber_pts or [])
            picked = list(self.processor.picked_points)
            # On a sheet the same pixel is both paper millimetres and a model
            # point seen through a detail; which one it is depends on what the
            # command asked for, so the registry's answer travels with it.
            active = self.processor.active
            space = active.space if active is not None else "model"
            for vp in self.all_viewports():
                vp.set_point_mode(True)
                vp.snap_base = base
                vp.point_axis = req.axis_lock
                vp.pending_points = pending
                vp.picked_points = picked
                vp.point_space = space
            self._refresh_rubber(None)
        else:
            for vp in self.all_viewports():
                vp.set_point_mode(False)
                vp.snap_base = None
                vp.point_axis = None
                vp.pending_points = []
                vp.picked_points = []
                vp.point_space = "model"
                vp.set_preview(None)
        self.osnap_bar.refresh()
        self._update_status()

    def _on_object_clicked(self, obj_id: str, modifiers):
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

    def _on_detail_entered(self, detail):
        """A click stepped into a detail instead of placing a point."""
        self.ctx.echo(f"Now drawing inside the detail ({detail.scale_text()})"
                      " — pick again to place the point.")
        self._update_status()

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
        sides = req.rubber_sides
        if pts:
            markers = list(pts)
            chain = pts + ([cursor] if cursor is not None else [])
            # A band is a line drawn to say where the next one goes. When what
            # is being dragged out is a frame, the ghost has already drawn it
            # and the band can only be its diagonal — a slash across the middle
            # of the shape it was meant to help place. The number it carried is
            # still wanted, so it is asked for as sides instead of a length.
            if len(chain) >= 2 and sides is None:
                arr = np.asarray(chain, np.float32)
                segs = np.stack([arr[:-1], arr[1:]], axis=1)
        self.viewport.set_preview(segs if len(segs) else None, markers)
        if sides is not None:
            self.viewport.set_frame_readout(
                sides(cursor) if cursor is not None else None, cursor)

    def _delete_selected(self):
        if self.viewport.space != "model":
            # On a sheet the pick is the layout's own, not the scene's.
            if self.viewport.layout_view.delete_selected():
                self.viewport.update()
                self._update_status()
            return
        if self.selection.ids and not self.processor.busy:
            self.run_command("delete")

    def _copy_selected(self):
        """Copy asks where you are, because what is meant is in doubt.

        A sheet has two things on it a command could mean, and the same rule
        that decides that for `move`, `delete` and `copy` decides it here.
        """
        import copy as _copy
        lv = self.ctx.sheet_view()
        if lv is not None:
            lv._prune()
            if not lv.selected:
                return
            self._clipboard = ("sheet", [(k, _copy.deepcopy(o))
                                         for k, o in lv.selected])
            self.ctx.echo(f"Copied {len(lv.selected)} sheet item(s).")
            return
        objs = self.selection.objects()
        if not objs:
            return
        self._clipboard = ("model", [(o.name, o.shape, o.layer_id)
                                     for o in objs])
        self.ctx.echo(f"Copied {len(objs)} object(s).")

    def _paste(self):
        """Paste asks the clipboard, because what it holds is not in doubt.

        Only where to put it is, and there is one answer: model objects go to
        the model wherever you are standing, sheet items go onto the sheet
        that is showing — which need not be the one they were copied from,
        and that is the point of it.
        """
        clip = getattr(self, "_clipboard", None)
        if not clip:
            return
        kind, items = clip
        if kind == "sheet":
            self._paste_on_sheet(items)
            return
        from .core import geometry as g
        self.history.checkpoint("paste")
        pasted = []
        live = {la.id for la in self.scene.layers.all()}
        # One notification for the paste, not one per object — see
        # Scene.batched. The clipboard holds whatever was selected, which on
        # a survey drawing is thousands of things.
        with self.scene.batched():
            for name, shape, layer_id in items:
                lid = layer_id if layer_id in live else None
                pasted.append(self.scene.add(g.copy_shape(shape),
                                             layer_id=lid))
        self.selection.set([o.id for o in pasted])
        where = "" if self.viewport.space == "model" else " into the model"
        self.ctx.echo(f"Pasted {len(pasted)} object(s){where}.")

    def _paste_on_sheet(self, items):
        """Put copied sheet items onto whichever sheet is showing."""
        lv = self.viewport.layout_view
        lay = lv.layout if self.viewport.space != "model" else None
        if lay is None:
            self.ctx.echo(f"{len(items)} sheet item(s) on the clipboard — "
                          "switch to a sheet to paste them.")
            return
        from .core.layout import copy_sheet_item
        self.history.checkpoint("paste")
        pasted = [(k, copy_sheet_item(lay, k, o)) for k, o in items]
        pasted = [(k, o) for k, o in pasted if o is not None]
        # Picked where they land, so they can be moved into place at once —
        # they arrive exactly on top of what they were copied from, and being
        # picked is what shows they arrived at all.
        lv.selected = pasted
        lv.corners = []
        self.scene.notify("layouts")
        self.viewport.update()
        self.ctx.echo(f"Pasted {len(pasted)} sheet item(s) onto {lay.name}.")

    # ------------------------------------------------------------ file dialogs

    # Filters come from fileio so the chooser can never drift from what we can
    # actually read/write (GitHub #2), and so Open stops offering export-only
    # formats.

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

    def start_new(self, units: str = "mm"):
        """Fresh document in the given units (no confirm) — used by the
        welcome screen."""
        self.history.checkpoint("new")
        self.scene.clear()
        self.scene.units = units
        self.scene.notify()
        self.ctx.current_path = None
        self.mark_saved()
        self.command_line.echo(f"New model ({units}).")

    def _pick_file(self, *, save: bool, title: str, name: str = "",
                   filters: str = "") -> str:
        """A file chooser that behaves. On Linux the native GNOME chooser gets
        glued to the main window and fills the screen under
        attach-modal-dialogs, so use Qt's own dialog as a normal, resizable,
        sensibly sized window (NORMAL window type dodges the attach). Native
        elsewhere."""
        import sys
        if not filters:
            filters = (fileio.export_filter() if save
                       else fileio.import_filter())
        dlg = QFileDialog(self, title, "", filters)
        if save:
            dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
            # Export dispatches on the extension, so a typed "part" must come
            # back as "part.stl" — follow whichever format is selected.
            def _suffix(f):
                dlg.setDefaultSuffix(fileio.suffix_for_filter(f))
            _suffix(dlg.selectedNameFilter())
            dlg.filterSelected.connect(_suffix)
            if name:
                dlg.selectFile(name)
        else:
            dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
        if sys.platform.startswith("linux"):
            dlg.setOption(QFileDialog.Option.DontUseNativeDialog, True)
            dlg.resize(900, 580)
        untether(dlg)
        if dlg.exec() and dlg.selectedFiles():
            path = dlg.selectedFiles()[0]
            # Some formats mean more than an extension — "Rhino 6 (*.3dm)"
            # carries the version — so the caller can ask what was picked.
            self._picked_filter = dlg.selectedNameFilter()
            return (fileio.ensure_suffix(path, dlg.selectedNameFilter())
                    if save else path)
        self._picked_filter = ""
        return ""

    def _file_open(self):
        path = self._pick_file(save=False, title="Open")
        if path:
            self._open_path(path)

    def _import_showing_progress(self, path: str) -> int:
        """Import `path`, showing what it is doing and offering a way out.

        A set-design .3dm is minutes of work; with no dialog the window simply
        stops repainting and the only exit is killing the app, which is what
        happened with a 921 MB file. The dialog waits before appearing so
        ordinary files don't flash one up, and updates are throttled because
        repainting per face would cost more than the import itself.
        """
        dlg = QProgressDialog(f"Opening {os.path.basename(path)}…",
                              "Cancel", 0, 100, self)
        dlg.setWindowTitle("Opening")
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(500)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        # It appears on a delay, so place it now rather than on the way up.
        untether(dlg, over=self)

        def report(fraction, message):
            dlg.setLabelText(message)
            dlg.setValue(int(fraction * 100))
            QApplication.processEvents()
            return not dlg.wasCanceled()

        try:
            return fileio.import_file(self.scene, path,
                                      progress=fileio.throttled(report))
        finally:
            dlg.close()

    def _open_path(self, path: str):
        """Open a file by path (shared by the dialog, Recent menu and the
        welcome screen)."""
        try:
            self.history.checkpoint("open")
            self._import_showing_progress(path)
            if path.endswith(".serp"):
                self.ctx.current_path = path
            self.command_line.echo(
                f"Opened {path}: {len(self.scene.all())} object(s).")
            self.viewport.zoom_extents()
            self.mark_saved()
            self.add_recent(path)
        except fileio.Cancelled:
            # the user's own decision, not a failure — no alert. Cancel
            # leaves the scene untouched, so there is nothing to undo.
            self.history.discard_checkpoint()
            self.command_line.echo("Open cancelled.")
        except Exception as exc:                              # noqa: BLE001
            self.history.discard_checkpoint()
            QMessageBox.warning(self, "Open failed", str(exc))

    # -- recent files (MRU) --
    def recent_files(self) -> list:
        """Recently opened/saved paths, most recent first, existing only."""
        return [p for p in self.cfg.get("recent_files", default=[])
                if os.path.exists(p)]

    def add_recent(self, path: str):
        from .utils.config import push_recent
        self.cfg.set("recent_files",
                     push_recent(self.cfg.get("recent_files", default=[]),
                                 path))
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        menu = getattr(self, "_recent_menu", None)
        if menu is None:
            return
        menu.clear()
        files = self.recent_files()
        if not files:
            act = menu.addAction("(no recent files)")
            act.setEnabled(False)
            return
        for p in files:
            menu.addAction(os.path.basename(p),
                           lambda checked=False, path=p: self._open_recent(path))
        menu.addSeparator()
        menu.addAction("Clear Recent", self._clear_recent)

    def _open_recent(self, path: str):
        if os.path.exists(path):
            self._open_path(path)
        else:
            QMessageBox.warning(self, "Open", f"File no longer exists:\n{path}")
            self._rebuild_recent_menu()      # prune it from the menu

    def _clear_recent(self):
        self.cfg.set("recent_files", [])
        self._rebuild_recent_menu()

    def _file_save(self, force_dialog: bool = False):
        path = self.ctx.current_path
        if force_dialog or not path:
            # Rhino formats sit beside the native one: round-tripping a .3dm
            # should not require finding Export (#5). _pick_file already
            # gives a typed bare name the chosen filter's extension.
            path = self._pick_file(
                save=True, title="Save", name="untitled.serp",
                filters="Serpentine3D (*.serp);;Rhino 8 (*.3dm);;"
                        "Rhino 7 (*.3dm);;Rhino 6 (*.3dm);;Rhino 5 (*.3dm)")
            if not path:
                return
            self._save_rhino_version = fileio.rhino_version_from_filter(
                getattr(self, "_picked_filter", ""))
        try:
            fileio.export_file(self.scene, path,
                               rhino_version=getattr(
                                   self, "_save_rhino_version", 8))
            self.ctx.current_path = path
            if path.lower().endswith(".3dm"):
                # Honest about the trade before anyone loses a sheet to it.
                self.command_line.echo(
                    f"Saved {path} — Rhino format; layouts and history "
                    "are kept only in .serp")
            else:
                self.command_line.echo(f"Saved {path}")
            self.mark_saved()
            self.add_recent(path)
        except Exception as exc:                              # noqa: BLE001
            QMessageBox.warning(self, "Save failed", str(exc))

    def _file_import(self):
        path = self._pick_file(save=False, title="Import")
        if not path:
            return
        try:
            self.history.checkpoint("import")
            n = self._import_showing_progress(path)
            self.command_line.echo(f"Imported {n} object(s).")
            self.viewport.zoom_extents()
        except fileio.Cancelled:
            self.history.discard_checkpoint()
            self.command_line.echo("Import cancelled.")
        except Exception as exc:                              # noqa: BLE001
            self.history.discard_checkpoint()
            QMessageBox.warning(self, "Import failed", str(exc))

    # STL export mesh-quality presets, shown in the export prompt.
    _STL_QUALITY = [("Draft — coarse, small file", "draft"),
                    ("Standard", "standard"),
                    ("Fine — smooth curves (recommended)", "fine"),
                    ("Ultra fine — maximum detail", "ultra")]

    def _file_export(self):
        path = self._pick_file(save=True, title="Export")
        if not path:
            return
        stl_quality = "standard"
        if path.lower().endswith(".stl"):
            stl_quality = self._pick_stl_quality()
            if stl_quality is None:
                return
        try:
            ids = self.selection.ids or None
            fileio.export_file(
                self.scene, path, only_ids=ids, stl_quality=stl_quality,
                rhino_version=fileio.rhino_version_from_filter(
                    getattr(self, "_picked_filter", "")))
            scope = "selection" if ids else "scene"
            self.command_line.echo(f"Exported {scope} to {path}")
        except Exception as exc:                              # noqa: BLE001
            QMessageBox.warning(self, "Export failed", str(exc))

    def _pick_stl_quality(self) -> str | None:
        """STL quality picker. Built as an instance (not QInputDialog.getItem)
        so it can be untethered from the main window. Returns a QUALITY key,
        or None if cancelled."""
        labels = [lbl for lbl, _ in self._STL_QUALITY]
        dlg = QInputDialog(self)
        dlg.setWindowTitle("STL mesh quality")
        dlg.setLabelText(
            "Finer meshes print smoother curves but make larger files:")
        dlg.setComboBoxItems(labels)
        dlg.setComboBoxEditable(False)
        dlg.setTextValue(labels[2])            # default to "Fine" for printing
        untether(dlg, over=self)
        if not dlg.exec():
            return None
        return dict(self._STL_QUALITY)[dlg.textValue()]

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

    def _restore_window(self):
        """Come back the way the window was left: geometry, dock sizes and
        the quad layout all reset every launch, which read as "no standard
        configuration" (GitHub #5). Restored state also means _balance_docks
        must keep its hands off the panel widths the user chose.
        """
        from PySide6.QtCore import QByteArray
        self._docks_restored = False
        geometry = self.cfg.get("window", "geometry", default="")
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode()))
        if self.cfg.get("window", "layout", default="single") == "quad":
            # Before restoreState, so the aux docks exist to restore onto.
            self.set_view_layout("quad")
        state = self.cfg.get("window", "state", default="")
        if state and self.restoreState(QByteArray.fromBase64(state.encode())):
            self._docks_restored = True

    def _remember_window(self):
        self.cfg.set("window", "geometry",
                     bytes(self.saveGeometry().toBase64()).decode())
        self.cfg.set("window", "state",
                     bytes(self.saveState().toBase64()).decode())
        self.cfg.set("window", "layout",
                     "quad" if self.aux_docks
                     and self.aux_docks[0].isVisibleTo(self) else "single")
        self.cfg.save()

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
        # Only a window somebody actually saw: a headless one (tests, a
        # crashed pre-show launch) closing would overwrite the layout the
        # user chose with default-constructed geometry.
        if self.isVisible():
            self._remember_window()
        self.autosave.clean_exit()
        super().closeEvent(ev)

    def offer_recovery(self):
        """Restore the newest crashed session, if any (called at startup)."""
        if os.environ.get("SERP3D_NO_RECOVER") == "1":
            # automation: never block startup on a modal recovery prompt
            return
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

    def _build_space_tab_row(self):
        """The bottom space-tab strip: Model / sheet tabs plus a '+' button to
        add a new sheet — click adds A3, the dropdown picks a size or opens the
        full 'layout' options (custom size, portrait)."""
        from PySide6.QtWidgets import QHBoxLayout, QMenu, QToolButton, QWidget
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(3)
        hl.addWidget(self.space_tabs)

        add = QToolButton()
        add.setText("+")
        add.setToolTip("New drafting sheet")
        add.setAutoRaise(True)
        add.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        add.setStyleSheet(
            "QToolButton { padding: 1px 8px; background: #212226;"
            " border: 1px solid #1b1c1f; color: #b9b9bd; font-size: 14px; }"
            "QToolButton:hover { background: #2f3035; color: #e8e8ea; }"
            "QToolButton::menu-button { border: none; width: 13px; }")
        add.clicked.connect(lambda: self._new_sheet("A3"))
        menu = QMenu(add)
        for size in ("A4", "A3", "A2", "A1", "Letter", "Tabloid"):
            menu.addAction(f"New sheet — {size}",
                           lambda s=size: self._new_sheet(s))
        menu.addSeparator()
        menu.addAction("New sheet…  (choose size / portrait)",
                       lambda: self.run_command("layout"))
        add.setMenu(menu)
        self.add_space_btn = add

        hl.addWidget(add)
        hl.addStretch(1)
        return row

    def _new_sheet(self, paper: str = "A3", landscape: bool = True):
        """Create a new paper-space drafting sheet and switch to it — the '+'
        button's action, i.e. 'layout' > New in one click."""
        from .core.layout import PAPER_SIZES, Layout
        w, h = PAPER_SIZES.get(paper, PAPER_SIZES["A3"])
        if not landscape:
            w, h = h, w
        lay = Layout(name=f"Layout {len(self.scene.layouts) + 1}",
                     paper_w=float(w), paper_h=float(h))
        self.scene.layouts.append(lay)
        self.scene.notify()
        self.switch_space(lay.id)
        self.command_line.echo(
            f"Created sheet '{lay.name}' ({w:g}x{h:g}mm). "
            "Use 'detail' to place model views.")
        return lay

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
        self.properties.refresh()       # different space, different selection

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
        from .ui.about import AboutDialog
        AboutDialog(self).exec()

    # -- update notifier -------------------------------------------------
    def start_update_check(self):
        """Kick off a background check for a newer release (launch-time).
        Non-blocking and fail-silent; skipped when turned off/headless."""
        import os
        if self.cfg.get("check_updates", default=True) is False:
            return
        if os.environ.get("SERP3D_NO_UPDATE_CHECK") == "1":
            return
        from PySide6.QtWidgets import QApplication
        if QApplication.platformName() in ("offscreen", "minimal", "vnc"):
            return                           # headless/automation: no network
        import platform
        import threading
        from . import __version__
        from .utils.updates import check_for_update

        def worker():
            rel = check_for_update(__version__, platform.system())
            if rel:
                self.updateAvailable.emit(rel)

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_available(self, rel):
        """Main-thread slot: a newer release was found on launch."""
        self._pending_update = rel
        self.statusBar().showMessage(
            f"Serpentine3D {rel['version']} is available — "
            f"Help ▸ Check for Updates to download.", 12000)

    def _check_updates_manual(self):
        """Help ▸ Check for Updates: synchronous, always reports back."""
        import platform
        from . import __version__
        from .utils.updates import check_for_update
        rel = self._pending_update or check_for_update(
            __version__, platform.system())
        self._show_update_result(rel)

    def _show_update_result(self, rel):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from . import __version__
        if not rel:
            QMessageBox.information(
                self, "Serpentine3D",
                f"You’re up to date — v{__version__} is the latest release.")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Update available")
        box.setText(f"<b>Serpentine3D {rel['version']}</b> is available.")
        box.setInformativeText(f"You have v{__version__}.")
        dl = box.addButton("Download", QMessageBox.ButtonRole.AcceptRole)
        notes = box.addButton("Release Notes",
                              QMessageBox.ButtonRole.ActionRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        url = None
        if clicked is dl:
            url = rel.get("download") or rel.get("url")
        elif clicked is notes:
            url = rel.get("url")
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def _update_status(self):
        n = len(self.scene.all())
        # On a sheet, what is picked lives in the layout view; a readout
        # stuck on "0 selected" is most of why picking looked broken there.
        sel = len(self.selection.ids)
        if self.viewport.space != "model":
            lv = self.viewport.layout_view
            # Except inside a detail, which is a window into the model: what a
            # click in there picks is a model object, and the model's count is
            # the one to show.
            if lv._entered() is None:
                # A corner is a smaller thing than the detail it belongs to, so
                # say which of the two the count is about.
                picked = len(lv.corners)
                sel = (f"{picked} corner{'' if picked == 1 else 's'}"
                       if picked else len(lv.selected))
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


def run_app(app, splash=None):
    """Build the main window and run the event loop.

    `app` is an already-created QApplication; `splash` is an optional
    SplashScreen already on screen (see serpentine3d.launcher, which shows
    it before the geometry kernel imports so it covers the slow cold start).
    """
    app.setApplicationName(APP_TITLE)
    # GNOME matches windows to the launcher (icon, grouping, pinning)
    # by this name — must equal the installed serpentine3d.desktop
    app.setDesktopFileName("serpentine3d")
    app.setStyleSheet(theme.QSS)

    if splash:
        splash.message("Preparing workspace…", 0.7)
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

    if splash:
        splash.message("Ready", 1.0)
    window.show()
    if splash:
        splash.finish(window)
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
                window.add_recent(arg)
            except Exception as exc:                          # noqa: BLE001
                window.command_line.echo(f"Could not open {arg}: {exc}")
            break

    from .ui.welcome import WelcomeScreen, should_show as _welcome
    if _welcome(window):
        WelcomeScreen(window).exec()
    window.start_update_check()
    return app.exec()


def main():
    """Standalone entry (tests, `python -m serpentine3d.app`).

    Real launches go through serpentine3d.launcher instead, which puts the
    splash up before this module's geometry-kernel imports load. This path
    has no early splash — by the time it runs, the kernel is already
    imported — so it's kept for tests and simple invocations.
    """
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    set_default_gl_format()
    app = QApplication(sys.argv)
    return run_app(app, splash=None)


if __name__ == "__main__":
    sys.exit(main())
