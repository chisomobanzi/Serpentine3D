"""Settings dialog: sidebar categories, changes apply immediately.

All but one: the interface scale, which Qt reads only at startup. That
one previews live, says it waits on a restart, and asks once on close.

Deliberately not Rhino's option-tree maze: a handful of flat pages, plain
language, live apply, and one-click import for Rhino alias files.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFontComboBox,
    QFrame, QHBoxLayout, QHeaderView, QLabel,
    QListWidget, QMessageBox, QPushButton, QRadioButton, QSlider, QSpinBox,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..commands import base as cmd_base
from ..ai.model_discovery import ModelDiscovery as _ModelDiscovery
from ..core.snaps import SNAP_TYPES
from ..utils.config import (
    DEFAULT_SHORTCUTS, parse_chord, parse_rhino_aliases, parse_shortcuts,
)
from .. import launcher
from . import theme
from .dialogs import untether

# the slider's range, which launcher._apply_ui_scale also holds to
SCALE_MIN, SCALE_MAX = 100, 150


class _ScalePreview(QLabel):
    """A piece of the real interface, enlarged to a scale it does not run at.

    Qt takes the scale before any window exists, so the page cannot show
    a new one live. It can show its size: the top-left of the Properties
    panel (all text, and no 3D view to re-render), magnified by the step
    from the running scale. Pixel-enlarged, so a little soft; the
    restarted interface is sharp.
    """

    BOX = QSize(360, 132)

    def __init__(self, window):
        super().__init__()
        self._window = window
        self._shot = None
        self.setFixedSize(self.BOX)
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        self.setFrameShape(QFrame.Shape.StyledPanel)

    def regrab(self):
        """Take the interface again, as after a font change."""
        self._shot = None

    def _grab(self):
        if self._shot is None:
            dock = getattr(self._window, "_prop_dock", None)
            source = (dock if dock is not None and dock.isVisible()
                      else self._window)
            # only the corner a smaller scale could show: grabbing the
            # whole window would re-render the 3D view for nothing
            self._shot = source.grab(QRect(0, 0, self.BOX.width() * 2,
                                           self.BOX.height() * 2))
        return self._shot

    def show_step(self, step: float):
        """Show the interface `step` times its running size."""
        shot = self._grab()
        dpr = shot.devicePixelRatio()
        # the crop that fills the box at this size, within what was grabbed
        w = min(self.BOX.width() / step, shot.width() / dpr)
        h = min(self.BOX.height() / step, shot.height() / dpr)
        crop = shot.copy(QRect(0, 0, round(w * dpr), round(h * dpr)))
        big = crop.scaled(round(w * step * dpr), round(h * step * dpr),
                          Qt.AspectRatioMode.IgnoreAspectRatio,
                          Qt.TransformationMode.SmoothTransformation)
        big.setDevicePixelRatio(dpr)
        self.setPixmap(big)


def _page(title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(18, 14, 18, 14)
    layout.setSpacing(10)
    t = QLabel(title)
    t.setStyleSheet("font-size: 16px; font-weight: bold; color: #e8e9ea;")
    s = QLabel(subtitle)
    s.setWordWrap(True)
    s.setStyleSheet("color: #85868a;")
    layout.addWidget(t)
    layout.addWidget(s)
    return w, layout


def _section(title: str, subtitle: str) -> QWidget:
    """A heading part-way down a page, for pages holding more than one
    thing."""
    w = QWidget()
    layout = QVBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(2)
    t = QLabel(title)
    t.setStyleSheet("font-weight: bold; color: #e8e9ea;")
    s = QLabel(subtitle)
    s.setWordWrap(True)
    s.setStyleSheet("color: #85868a; font-size: 11px;")
    layout.addWidget(t)
    layout.addWidget(s)
    return w


class SettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.cfg = window.cfg
        self.setWindowTitle("Serpentine3D Settings")
        self.resize(760, 620)
        untether(self, over=window)   # a panel you read beside the drawing

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(160)
        self.pages = QStackedWidget()
        for name, builder in [
            ("Mouse", self._mouse_page),
            ("Shortcuts", self._shortcuts_page),
            ("Aliases", self._aliases_page),
            ("Object Snaps", self._osnap_page),
            ("Display", self._display_page),
            ("Assistant", self._assistant_page),
        ]:
            self.sidebar.addItem(name)
            self.pages.addWidget(builder())
        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sidebar.setCurrentRow(0)

        btn_defaults = QPushButton("Restore Defaults")
        btn_defaults.clicked.connect(self._restore_defaults)
        btn_close = QPushButton("Close")
        btn_close.setDefault(True)
        btn_close.clicked.connect(self.accept)
        # while a new interface scale waits, the footer says so beside
        # Close, which is where people look before pressing it
        self.btn_restart_now = QPushButton("Restart now")
        self.btn_restart_now.clicked.connect(self._restart_now)
        footer = QHBoxLayout()
        footer.addWidget(btn_defaults)
        footer.addStretch(1)
        self.footer_note = QLabel()
        footer.addWidget(self.footer_note)
        footer.addSpacing(12)
        footer.addWidget(self.btn_restart_now)
        footer.addWidget(btn_close)

        body = QHBoxLayout()
        body.addWidget(self.sidebar)
        body.addWidget(self.pages, 1)
        root = QVBoxLayout(self)
        root.addLayout(body, 1)
        root.addLayout(footer)
        self._show_scale_state()

    # ------------------------------------------------------------- mouse

    def _mouse_page(self) -> QWidget:
        w, layout = _page("Mouse",
                          "How the mouse drives the viewport. Shift + the "
                          "orbit button always pans, and Ctrl + the orbit "
                          "button zooms; left button selects and picks "
                          "points.")
        self.rb_middle = QRadioButton("Orbit with the middle mouse button")
        self.rb_right = QRadioButton("Orbit with the right mouse button "
                                     "(Rhino default)")
        current = self.cfg.get("mouse", "orbit_button", default="right")
        (self.rb_right if current == "right" else self.rb_middle
         ).setChecked(True)
        self.rb_middle.toggled.connect(self._mouse_changed)
        layout.addWidget(self.rb_middle)
        layout.addWidget(self.rb_right)

        self.cb_invert = QCheckBox("Invert scroll-wheel zoom direction")
        self.cb_invert.setChecked(
            bool(self.cfg.get("mouse", "invert_scroll", default=False)))
        self.cb_invert.toggled.connect(self._mouse_changed)
        layout.addWidget(self.cb_invert)

        def slider_row(label, key):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            s = QSlider(Qt.Orientation.Horizontal)
            s.setRange(20, 300)
            s.setValue(int(float(self.cfg.get("mouse", key,
                                              default=1.0)) * 100))
            s.valueChanged.connect(self._mouse_changed)
            row.addWidget(s, 1)
            val = QLabel()
            s.valueChanged.connect(lambda v, lbl=val: lbl.setText(f"{v}%"))
            val.setText(f"{s.value()}%")
            val.setFixedWidth(44)
            row.addWidget(val)
            layout.addLayout(row)
            return s

        self.sl_orbit = slider_row("Orbit speed", "orbit_speed")
        self.sl_zoom = slider_row("Zoom speed", "zoom_speed")

        layout.addSpacing(12)
        layout.addWidget(QLabel("<b>SpaceMouse (3Dconnexion)</b>"))
        self.cb_sm_enabled = QCheckBox("Enable SpaceMouse navigation")
        self.cb_sm_enabled.setChecked(
            bool(self.cfg.get("spacemouse", "enabled", default=True)))
        self.cb_sm_enabled.toggled.connect(self._mouse_changed)
        layout.addWidget(self.cb_sm_enabled)

        row = QHBoxLayout()
        row.addWidget(QLabel("Sensitivity"))
        self.sl_sm = QSlider(Qt.Orientation.Horizontal)
        self.sl_sm.setRange(20, 300)
        self.sl_sm.setValue(int(float(self.cfg.get(
            "spacemouse", "sensitivity", default=1.0)) * 100))
        self.sl_sm.valueChanged.connect(self._mouse_changed)
        row.addWidget(self.sl_sm, 1)
        sm_val = QLabel(f"{self.sl_sm.value()}%")
        sm_val.setFixedWidth(44)
        self.sl_sm.valueChanged.connect(
            lambda v, lbl=sm_val: lbl.setText(f"{v}%"))
        row.addWidget(sm_val)
        layout.addLayout(row)

        self.cb_sm_pan = QCheckBox("Invert pan (slide/lift)")
        self.cb_sm_zoom = QCheckBox("Invert zoom (push/pull)")
        self.cb_sm_orbit = QCheckBox("Invert orbit (tilt/twist)")
        for cb, key in ((self.cb_sm_pan, "invert_pan"),
                        (self.cb_sm_zoom, "invert_zoom"),
                        (self.cb_sm_orbit, "invert_orbit")):
            cb.setChecked(bool(self.cfg.get("spacemouse", key,
                                            default=False)))
            cb.toggled.connect(self._mouse_changed)
            layout.addWidget(cb)
        sm = getattr(self.window, "spacemouse", None)
        layout.addWidget(QLabel(f"Status: {sm.status() if sm else 'n/a'}"))

        layout.addStretch(1)
        return w

    def _mouse_changed(self, *_):
        self.cfg.set("mouse", "orbit_button",
                     "right" if self.rb_right.isChecked() else "middle")
        self.cfg.set("mouse", "invert_scroll", self.cb_invert.isChecked())
        self.cfg.set("mouse", "orbit_speed", self.sl_orbit.value() / 100.0)
        self.cfg.set("mouse", "zoom_speed", self.sl_zoom.value() / 100.0)
        self.cfg.set("spacemouse", "enabled", self.cb_sm_enabled.isChecked())
        self.cfg.set("spacemouse", "sensitivity", self.sl_sm.value() / 100.0)
        self.cfg.set("spacemouse", "invert_pan", self.cb_sm_pan.isChecked())
        self.cfg.set("spacemouse", "invert_zoom",
                     self.cb_sm_zoom.isChecked())
        self.cfg.set("spacemouse", "invert_orbit",
                     self.cb_sm_orbit.isChecked())

    # --------------------------------------------------------- shortcuts
    #
    # Keys and mouse chords answer the same question — what do I press to
    # run this — so they share a page. Two tables rather than one, because
    # 'alt+right' means Alt and the arrow key to a keyboard and Alt and the
    # right button to a mouse; which table a row sits in says which.

    def _shortcuts_page(self) -> QWidget:
        w, layout = _page("Shortcuts",
                          "What you press to run a command, by key or by "
                          "mouse button.")
        layout.addWidget(_section("Keyboard",
                                  "Any key, any command. Import accepts "
                                  "simple text files ('F5 zoomextents' or "
                                  "'ctrl+b=box' per line) or JSON."))
        self.key_table = self._binding_table("Shortcut", self._shortcuts_changed)
        with QSignalBlocker(self.key_table):
            for key, cmd in sorted(
                    (self.cfg.get("shortcuts", default={}) or {}).items()):
                self._add_row(self.key_table, key, cmd)
        layout.addWidget(self.key_table, 2)   # more keys get bound than chords
        keyboard_buttons = self._table_buttons(
            self.key_table, self._import_shortcuts,
            on_change=self._shortcuts_changed)
        restore = QPushButton("Restore keyboard defaults")
        restore.clicked.connect(self._restore_keyboard_defaults)
        keyboard_buttons.addWidget(restore)
        layout.addLayout(keyboard_buttons)
        self.shortcut_feedback = QLabel()
        self.shortcut_feedback.setWordWrap(True)
        self.shortcut_feedback.setStyleSheet("color: #e5ae60;")
        layout.addWidget(self.shortcut_feedback)
        self._shortcuts_changed()

        layout.addSpacing(10)
        layout.addWidget(_section(
            "Mouse chords",
            "A button held with modifiers: 'ctrl+shift+mmb' runs its command "
            "on a click, so a drag still orbits and pans. Middle and right "
            "buttons only. Order and spelling don't matter — "
            "'mmb+ctrl+shift' and 'shift+ctrl+middle' are the same chord."))
        self.chord_table = self._binding_table("Chord", self._chords_changed)
        for chord, cmd in sorted(
                (self.cfg.get("mouse", "chords", default={}) or {}).items()):
            self._add_row(self.chord_table, chord, cmd)
        layout.addWidget(self.chord_table, 1)
        layout.addLayout(self._table_buttons(
            self.chord_table, None, on_change=self._chords_changed))
        return w

    def _binding_table(self, heading: str, on_change) -> QTableWidget:
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels([heading, "Command"])
        for col in (0, 1):
            table.horizontalHeader().setSectionResizeMode(
                col, QHeaderView.ResizeMode.Stretch)
        table.itemChanged.connect(on_change)
        return table

    def _chords_changed(self, *_):
        """Save the chord table. Rows that aren't a chord are dropped rather
        than stored — a half-typed 'ctrl+shift' is normal while editing, and
        keeping it would leave a binding that can never fire."""
        chords = {}
        for r in range(self.chord_table.rowCount()):
            chord_item = self.chord_table.item(r, 0)
            cmd_item = self.chord_table.item(r, 1)
            if not chord_item or not cmd_item:
                continue
            chord = chord_item.text().strip()
            cmd = cmd_item.text().strip().lower()
            if not chord or not cmd or parse_chord(chord) is None:
                continue
            chords[chord] = cmd
        self.cfg.set("mouse", "chords", chords)

    def _shortcuts_changed(self, *_):
        shortcuts = {}
        conflicts = set()
        for r in range(self.key_table.rowCount()):
            key_item = self.key_table.item(r, 0)
            cmd_item = self.key_table.item(r, 1)
            if not key_item or not cmd_item:
                continue
            key = key_item.text().strip()
            cmd = cmd_item.text().strip().lower()
            if not key or not cmd:
                continue
            sequence = QKeySequence(key)
            if sequence.isEmpty():
                continue
            key = sequence.toString()
            if key in shortcuts:
                conflicts.add(key)
            shortcuts[key] = cmd
        if conflicts:
            self.shortcut_feedback.setText(
                "Shortcut conflict: " + ", ".join(sorted(conflicts)) +
                " is already bound. Choose another key or remove the duplicate. "
                "Your last valid bindings remain active.")
            return
        self.shortcut_feedback.clear()
        self.cfg.set("shortcuts", shortcuts)
        self.window.apply_user_shortcuts()

    def _restore_keyboard_defaults(self):
        if QMessageBox.question(
                self, "Restore keyboard defaults",
                "Replace all keyboard bindings with their factory defaults?") \
                != QMessageBox.StandardButton.Yes:
            return
        with QSignalBlocker(self.key_table):
            self.key_table.setRowCount(0)
            for key, command in sorted(DEFAULT_SHORTCUTS.items()):
                self._add_row(self.key_table, key, command)
        self._shortcuts_changed()

    def _import_shortcuts(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import shortcuts", "", "Text/JSON (*.txt *.json)")
        if not path:
            return
        try:
            parsed = parse_shortcuts(open(path, encoding="utf-8").read())
        except Exception as exc:                              # noqa: BLE001
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        for key, cmd in parsed.items():
            self._add_row(self.key_table, key, cmd)
        self._shortcuts_changed()
        QMessageBox.information(self, "Imported",
                                f"Imported {len(parsed)} shortcut(s).")

    # ----------------------------------------------------------- aliases

    def _aliases_page(self) -> QWidget:
        w, layout = _page("Command Aliases",
                          "Short names for commands, e.g. 'l' for line. "
                          "Import reads Rhino alias exports (Options > "
                          "Aliases > Export) and maps known commands "
                          "automatically.")
        self.alias_table = QTableWidget(0, 2)
        self.alias_table.setHorizontalHeaderLabels(["Alias", "Command"])
        self.alias_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.alias_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        for alias, cmd in sorted(
                (self.cfg.get("aliases", default={}) or {}).items()):
            self._add_row(self.alias_table, alias, cmd)
        self.alias_table.itemChanged.connect(self._aliases_changed)
        layout.addWidget(self.alias_table, 1)
        layout.addLayout(self._table_buttons(
            self.alias_table, self._import_aliases,
            on_change=self._aliases_changed))
        return w

    def _aliases_changed(self, *_):
        aliases = {}
        for r in range(self.alias_table.rowCount()):
            a_item = self.alias_table.item(r, 0)
            c_item = self.alias_table.item(r, 1)
            if not a_item or not c_item:
                continue
            alias = a_item.text().strip().lower()
            cmd = c_item.text().strip().lower()
            if alias and cmd:
                aliases[alias] = cmd
        self.cfg.set("aliases", aliases)
        self.window.apply_user_aliases()

    def _import_aliases(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Rhino aliases", "", "Text files (*.txt)")
        if not path:
            return
        try:
            aliases, unmapped = parse_rhino_aliases(
                open(path, encoding="utf-8").read())
        except Exception as exc:                              # noqa: BLE001
            QMessageBox.warning(self, "Import failed", str(exc))
            return
        for alias, cmd in sorted(aliases.items()):
            self._add_row(self.alias_table, alias, cmd)
        self._aliases_changed()
        msg = f"Imported {len(aliases)} alias(es)."
        if unmapped:
            unknown = ", ".join(sorted(set(unmapped))[:8])
            msg += (f"\n\n{len(unmapped)} target(s) have no Serpentine3D "
                    f"equivalent yet (kept as-is): {unknown}")
        QMessageBox.information(self, "Imported", msg)

    # ------------------------------------------------------------ osnaps

    def _osnap_page(self) -> QWidget:
        w, layout = _page("Object Snaps",
                          "Which geometry points the cursor locks onto "
                          "while picking. Also available on the osnap bar "
                          "under the command line.")
        vp = self.window.viewport
        self.os_master = QCheckBox("Object snaps enabled")
        self.os_master.setChecked(vp.snaps.enabled)
        self.os_master.toggled.connect(self._osnaps_changed)
        layout.addWidget(self.os_master)
        labels = {
            "end": "End points", "mid": "Midpoints",
            "point": "Point objects and point-cloud samples",
            "center": "Circle/arc centers", "quad": "Quadrant points",
            "int": "Intersections",
            "appint": "Apparent intersections (crossing on screen only)",
            "perp": "Perpendicular (from previous point)",
            "near": "Nearest point on curve",
        }
        self.os_boxes = {}
        for t in SNAP_TYPES:
            cb = QCheckBox(labels[t])
            cb.setChecked(vp.snaps.types.get(t, False))
            cb.toggled.connect(self._osnaps_changed)
            layout.addWidget(cb)
            self.os_boxes[t] = cb
        layout.addStretch(1)
        return w

    def _osnaps_changed(self, *_):
        vp = self.window.viewport
        vp.snaps.enabled = self.os_master.isChecked()
        self.cfg.set("osnaps", "enabled", vp.snaps.enabled)
        for t, cb in self.os_boxes.items():
            vp.snaps.types[t] = cb.isChecked()
            self.cfg.set("osnaps", t, cb.isChecked())
        self.window.osnap_bar.refresh()

    # ----------------------------------------------------------- display

    def _assistant_page(self) -> QWidget:
        from PySide6.QtWidgets import QComboBox, QLineEdit
        from ..ai.local_client import DEFAULT_ENDPOINT
        w, layout = _page(
            "Assistant",
            "Choose who receives Ask AI messages: your ChatGPT account, a local model, "
            "or an OpenAI or Anthropic API key. "
            "Changes during a response apply to the next turn.")

        self._ai_loading = True
        row_provider = QHBoxLayout()
        row_provider.addWidget(QLabel("Provider"))
        self.cb_ai_provider = QComboBox()
        self.cb_ai_provider.addItem("Anthropic", "anthropic")
        self.cb_ai_provider.addItem("OpenAI", "openai")
        self.cb_ai_provider.addItem("LM Studio", "lmstudio")
        self.cb_ai_provider.addItem("ChatGPT account", "chatgpt")
        self.cb_ai_provider.setCurrentIndex(max(0, self.cb_ai_provider.findData(
            self.cfg.get("ai", "provider", default="anthropic"))))
        row_provider.addWidget(self.cb_ai_provider, 1)
        layout.addLayout(row_provider)

        self.ai_key_row = QWidget()
        row = QHBoxLayout(self.ai_key_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("API key"))
        self.ed_ai_key = QLineEdit()
        self.ed_ai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_ai_key.editingFinished.connect(self._ai_changed)
        row.addWidget(self.ed_ai_key, 1)
        layout.addWidget(self.ai_key_row)

        self.ai_endpoint_row = QWidget()
        endpoint_row = QHBoxLayout(self.ai_endpoint_row)
        endpoint_row.setContentsMargins(0, 0, 0, 0)
        endpoint_row.addWidget(QLabel("Server URL"))
        self.ed_ai_endpoint = QLineEdit(str(self.cfg.get(
            "ai", "local_endpoint", default=DEFAULT_ENDPOINT)))
        self.ed_ai_endpoint.setPlaceholderText(DEFAULT_ENDPOINT)
        self.ed_ai_endpoint.setAccessibleName("LM Studio endpoint")
        self.ed_ai_endpoint.editingFinished.connect(self._ai_changed)
        endpoint_row.addWidget(self.ed_ai_endpoint, 1)
        self.btn_ai_refresh = QPushButton("Refresh models")
        self.btn_ai_refresh.clicked.connect(self._discover_ai_models)
        endpoint_row.addWidget(self.btn_ai_refresh)
        layout.addWidget(self.ai_endpoint_row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Model"))
        self.cb_ai_model = QComboBox()
        self.cb_ai_model.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cb_ai_model.setMinimumContentsLength(16)
        self.cb_ai_model.currentIndexChanged.connect(self._ai_changed)
        self.cb_ai_model.editTextChanged.connect(self._ai_changed)
        row2.addWidget(self.cb_ai_model, 1)
        layout.addLayout(row2)

        self.ai_note = QLabel()
        self.ai_note.setWordWrap(True)
        self.ai_note.setStyleSheet("color: #85868a; font-size: 11px;")
        layout.addWidget(self.ai_note)
        self.ai_discovery_status = QLabel()
        self.ai_discovery_status.setWordWrap(True)
        layout.addWidget(self.ai_discovery_status)
        self._ai_discovery = _ModelDiscovery(self)
        self._ai_discovery.finished.connect(self._ai_models_discovered)
        self.cb_ai_provider.currentIndexChanged.connect(self._ai_provider_changed)
        self._ai_provider_changed(save=False)
        layout.addStretch(1)
        return w

    def _ai_changed(self):
        if self._ai_loading:
            return
        from ..ai.local_client import DEFAULT_ENDPOINT

        provider = self.cb_ai_provider.currentData()
        if provider in ("anthropic", "openai"):
            key_name = "openai_api_key" if provider == "openai" else "api_key"
            self.cfg.set("ai", key_name, self.ed_ai_key.text().strip())
        local = provider == "lmstudio"
        self.cfg.set("ai", "provider", provider)
        endpoint = self.ed_ai_endpoint.text().strip()
        previous_endpoint = self.cfg.get("ai", "local_endpoint", default=DEFAULT_ENDPOINT)
        if endpoint != previous_endpoint:
            # Model IDs can overlap across servers; image support established
            # by the previous server must not follow an endpoint edit.
            self.cfg.set("ai", "local_models", [])
            if local:
                current = self.cb_ai_model.currentData()
                with QSignalBlocker(self.cb_ai_model):
                    self.cb_ai_model.clear()
                    self.cb_ai_model.addItem(current or "Refresh to discover local models", current)
                self.ai_discovery_status.setText("Server URL changed. Refresh models again.")
        self.cfg.set("ai", "local_endpoint", endpoint)
        model = (self.cb_ai_model.currentText().strip() if provider == "openai"
                 else self.cb_ai_model.currentData())
        if model:
            model_key = {"lmstudio": "local_model", "chatgpt": "chatgpt_model",
                         "openai": "openai_model"}.get(provider, "model")
            self.cfg.set("ai", model_key, model)
        self.cfg.save()
        # Settings also apply when the assistant pane was already open.
        from ..ai.panel import AiPanel
        for panel in self.window.findChildren(AiPanel):
            panel._refresh_mode()

    def _ai_provider_changed(self, *_, save=True):
        from ..ai.client import DEFAULT_MODEL, MODELS
        from ..ai.openai_client import DEFAULT_MODEL as OPENAI_DEFAULT_MODEL, MODELS as OPENAI_MODELS
        self._ai_loading = True
        local = self.cb_ai_provider.currentData() == "lmstudio"
        account = self.cb_ai_provider.currentData() == "chatgpt"
        openai = self.cb_ai_provider.currentData() == "openai"
        self.ai_key_row.setVisible(not local and not account)
        self.ai_endpoint_row.setVisible(local)
        self.cb_ai_model.clear()
        self.cb_ai_model.setEditable(openai)
        self.cb_ai_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        if account:
            current = self.cfg.get("ai", "chatgpt_model", default="")
            for model in self.cfg.get("ai", "chatgpt_models", default=[]) or []:
                self.cb_ai_model.addItem(model.get("label") or model["id"], model["id"])
            if current and self.cb_ai_model.findData(current) < 0:
                self.cb_ai_model.addItem(current, current)
            if not self.cb_ai_model.count():
                self.cb_ai_model.addItem("Connect in the Assistant", None)
            self.ai_note.setText("Sign in and manage your ChatGPT connection in the Assistant’s connection options.")
        elif local:
            current = self.cfg.get("ai", "local_model", default="")
            models = self.cfg.get("ai", "local_models", default=[]) or []
            for model in models:
                self._add_local_model(model)
            if current and self.cb_ai_model.findData(current) < 0:
                self.cb_ai_model.addItem(current, current)
            if not self.cb_ai_model.count():
                self.cb_ai_model.addItem("Refresh to discover local models", None)
            self.ai_note.setText("Start LM Studio's local server, then refresh models. "
                                 "Cloud API keys are never sent to this server. "
                                 "Vision support is read from the server's model metadata.")
        else:
            current = self.cfg.get("ai", "openai_model" if openai else "model",
                                   default=OPENAI_DEFAULT_MODEL if openai else DEFAULT_MODEL)
            for model_id, label in OPENAI_MODELS if openai else MODELS:
                self.cb_ai_model.addItem(label, model_id)
            if current and self.cb_ai_model.findData(current) < 0:
                self.cb_ai_model.addItem(current, current)
            provider_label = "OpenAI" if openai else "Anthropic"
            self.ed_ai_key.setAccessibleName(f"{provider_label} API key")
            self.ed_ai_key.setPlaceholderText(f"{provider_label} API key · " + (
                "sk-…" if openai else "sk-ant-…"))
            self.ed_ai_key.setText(str(self.cfg.get(
                "ai", "openai_api_key" if openai else "api_key", default="") or ""))
            self.ai_note.setText(f"API usage is billed to your {provider_label} account, "
                                 "separately from subscriptions.")
            details = ("The key is stored in your Serpentine3D config. "
                       f"{'OPENAI' if openai else 'ANTHROPIC'}_API_KEY takes precedence and is never saved.")
            self.ai_note.setToolTip(details)
            self.ed_ai_key.setToolTip(details)
        index = self.cb_ai_model.findData(current)
        self.cb_ai_model.setCurrentIndex(max(0, index))
        self.ai_discovery_status.clear()
        self._ai_loading = False
        if save:
            self._ai_changed()

    def _add_local_model(self, model):
        model_id = model["id"]
        label = model.get("label", model_id)
        self.cb_ai_model.addItem(f"{label} · {model_id}" if label != model_id else model_id, model_id)
        features = "Vision" if model.get("vision") else "Text only"
        if model.get("tool_use") is False:
            features += " · not trained for tool use"
        elif model.get("tool_use"):
            features += " · tool use"
        self.cb_ai_model.setItemData(self.cb_ai_model.count() - 1, features, Qt.ItemDataRole.ToolTipRole)

    def _discover_ai_models(self):
        self._ai_changed()
        self.btn_ai_refresh.setEnabled(False)
        self.ai_discovery_status.setText("Discovering models…")
        self._ai_discovery.start(self.ed_ai_endpoint.text().strip())

    def _ai_models_discovered(self, endpoint, models, error):
        self.btn_ai_refresh.setEnabled(True)
        if endpoint != self.ed_ai_endpoint.text().strip():
            self.ai_discovery_status.setText("Server URL changed. Refresh models again.")
            return
        if error:
            self.ai_discovery_status.setText(error)
            return
        self.cfg.set("ai", "local_models", models)
        self.cfg.save()
        if self.cb_ai_provider.currentData() == "lmstudio":
            self._ai_provider_changed()
            self.ai_discovery_status.setText(
                f"{len(models)} local language models found." if models
                else "No language models found. Download a model in LM Studio first.")

    def _display_page(self) -> QWidget:
        w, layout = _page("Display",
                          "Viewport appearance. The grid sits on the "
                          "construction plane; one unit per minor square.")
        row = QHBoxLayout()
        row.addWidget(QLabel("Grid extent (units)"))
        self.sp_extent = QSpinBox()
        self.sp_extent.setRange(10, 1000)
        self.sp_extent.setValue(
            int(self.cfg.get("display", "grid_extent", default=100)))
        self.sp_extent.valueChanged.connect(self._display_changed)
        row.addWidget(self.sp_extent)
        row.addStretch(1)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Major line every"))
        self.sp_major = QSpinBox()
        self.sp_major.setRange(2, 100)
        self.sp_major.setValue(
            int(self.cfg.get("display", "grid_major", default=10)))
        self.sp_major.valueChanged.connect(self._display_changed)
        row2.addWidget(self.sp_major)
        row2.addWidget(QLabel("units"))
        row2.addStretch(1)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("New viewports open in"))
        self.cb_mode = QComboBox()
        from .viewport import VIEW_FLIGHT_MS, Viewport
        for mode in Viewport.DISPLAY_MODES:
            self.cb_mode.addItem(mode.capitalize(), mode)
        current = self.cfg.get("display", "default_mode", default="shaded")
        index = self.cb_mode.findData(current)
        self.cb_mode.setCurrentIndex(index if index >= 0 else 0)
        self.cb_mode.currentIndexChanged.connect(self._display_changed)
        row3.addWidget(self.cb_mode)
        row3.addStretch(1)
        layout.addLayout(row3)

        row4 = QHBoxLayout()
        row4.addWidget(QLabel("Turn to a named view over"))
        self.sp_transition = QSpinBox()
        self.sp_transition.setRange(0, 1000)
        self.sp_transition.setSingleStep(10)
        self.sp_transition.setSuffix(" ms")
        self.sp_transition.setSpecialValueText("no time (cut)")
        self.sp_transition.setValue(int(self.cfg.get(
            "display", "view_transition_ms", default=VIEW_FLIGHT_MS)))
        self.sp_transition.valueChanged.connect(self._display_changed)
        row4.addWidget(self.sp_transition)
        row4.addStretch(1)
        layout.addLayout(row4)

        row5 = QHBoxLayout()
        lbl_scale_title = QLabel("Interface scale")
        row5.addWidget(lbl_scale_title)
        self.sl_scale = QSlider(Qt.Orientation.Horizontal)
        self.sl_scale.setRange(SCALE_MIN, SCALE_MAX)
        self.sl_scale.setSingleStep(5)
        self.sl_scale.setPageStep(10)
        self.sl_scale.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.sl_scale.setTickInterval(10)
        self.sl_scale.setValue(round(self._saved_scale() * 100))
        # what this process runs at, which Qt took before any window
        # existed: a saved scale that differs waits on a restart
        self._running_scale = launcher.running_scale()
        self.sl_scale.valueChanged.connect(self._interface_changed)
        self.lbl_scale = QLabel(f"{self.sl_scale.value()}%")
        self.lbl_scale_pending = QLabel("after restart")
        self.lbl_scale_pending.setStyleSheet(f"color: {theme.ACCENT};")
        row5.addWidget(self.sl_scale)
        row5.addWidget(self.lbl_scale)
        row5.addWidget(self.lbl_scale_pending)
        row5.addStretch(1)
        layout.addLayout(row5)

        row_preview = QHBoxLayout()
        row_preview.addSpacing(lbl_scale_title.sizeHint().width()
                               + row5.spacing())
        self.scale_preview = _ScalePreview(self.window)
        row_preview.addWidget(self.scale_preview)
        row_preview.addStretch(1)
        layout.addLayout(row_preview)

        row6 = QHBoxLayout()
        row6.addWidget(QLabel("Interface font"))
        self.cb_font = QFontComboBox()
        self.cb_font.insertItem(0, "System default")
        family = self.cfg.get("display", "interface_font", default="") or ""
        self.cb_font.setCurrentIndex(
            self.cb_font.findText(family) if family else 0)
        self.cb_font.currentIndexChanged.connect(self._font_changed)
        row6.addWidget(self.cb_font)
        row6.addStretch(1)
        layout.addLayout(row6)

        layout.addStretch(1)
        return w

    def _saved_scale(self) -> float:
        try:
            scale = float(self.cfg.get("display", "ui_scale", default=1.0))
        except (TypeError, ValueError):
            return 1.0                   # hand-edited: as the launcher does
        return min(max(scale, SCALE_MIN / 100), SCALE_MAX / 100)

    def _scale_waiting(self) -> float | None:
        """The saved scale, when it is not the one running."""
        saved = self._saved_scale()
        return None if abs(saved - self._running_scale) < 1e-6 else saved

    def _show_scale_state(self):
        waiting = self._scale_waiting() is not None
        self.lbl_scale.setText(f"{self.sl_scale.value()}%")
        self.lbl_scale_pending.setHidden(not waiting)
        self.btn_restart_now.setHidden(not waiting)
        if waiting:
            self.footer_note.setText(
                "Interface scale changes when Serpentine3D restarts")
            self.footer_note.setStyleSheet(
                f"color: {theme.ACCENT}; font-size: 11px;")
        else:
            self.footer_note.setText("Changes apply immediately")
            self.footer_note.setStyleSheet(
                "color: #85868a; font-size: 11px;")
        self.scale_preview.show_step(
            self.sl_scale.value() / 100 / self._running_scale)

    def _interface_changed(self, *_):
        # the scale is read once at launch, before Qt exists, by
        # launcher._apply_ui_scale: persist it, and say it waits
        self.cfg.set("display", "ui_scale", self.sl_scale.value() / 100.0)
        self._show_scale_state()

    def _ask_restart(self, scale: float) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("Interface scale")
        box.setIcon(QMessageBox.Icon.Question)
        box.setText(f"Restart now to switch to {round(scale * 100)}%?")
        box.setInformativeText(
            "The open document comes back as it is, unsaved changes "
            "included.")
        restart = box.addButton("Restart now",
                                QMessageBox.ButtonRole.AcceptRole)
        later = box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(restart)
        box.setEscapeButton(later)
        box.exec()
        return box.clickedButton() is restart

    def done(self, result):
        # Close, Esc and the title bar's X all end here. A new scale that
        # would otherwise wait unseen gets one question.
        waiting = self._scale_waiting()
        if waiting is not None and self._ask_restart(waiting):
            self._restart_now()
            return
        if waiting is not None:
            self.window.command_line.echo(
                f"Interface scale {round(waiting * 100)}% applies the next "
                "time Serpentine3D starts.")
        super().done(result)

    def _restart_now(self):
        from .. import app
        super().done(QDialog.DialogCode.Accepted)
        app.restart_app(self.window)

    def _font_changed(self, *_):
        family = (self.cb_font.currentText()
                  if self.cb_font.currentIndex() > 0 else "")
        self.cfg.set("display", "interface_font", family)
        # the font is live: widgets repolish on the font-change event
        app = QApplication.instance()
        if app is not None:
            theme.apply_interface_font(app, family)
        # the preview shows the interface as it now looks, once the new
        # font has reached it
        self.scale_preview.regrab()
        QTimer.singleShot(0, self._show_scale_state)

    def _display_changed(self, *_):
        self.cfg.set("display", "grid_extent", self.sp_extent.value())
        self.cfg.set("display", "grid_major", self.sp_major.value())
        self.cfg.set("display", "default_mode", self.cb_mode.currentData())
        self.cfg.set("display", "view_transition_ms",
                     self.sp_transition.value())
        self.window.viewport.set_grid_params(self.sp_extent.value(),
                                             self.sp_major.value())

    # ------------------------------------------------------------ shared

    def _add_row(self, table: QTableWidget, a: str, b: str):
        # avoid duplicate keys: update in place
        keyboard = table is getattr(self, "key_table", None)
        if keyboard:
            a = QKeySequence(a).toString()
        for r in range(table.rowCount()):
            existing = table.item(r, 0)
            if existing and (QKeySequence(existing.text()).toString()
                             if keyboard else existing.text()) == a:
                table.item(r, 1).setText(b)
                return
        r = table.rowCount()
        table.insertRow(r)
        table.setItem(r, 0, QTableWidgetItem(a))
        table.setItem(r, 1, QTableWidgetItem(b))

    def _table_buttons(self, table: QTableWidget, import_fn,
                       on_change) -> QHBoxLayout:
        row = QHBoxLayout()
        btn_add = QPushButton("Add")
        btn_add.clicked.connect(
            lambda: (table.insertRow(table.rowCount()),
                     table.setItem(table.rowCount() - 1, 0,
                                   QTableWidgetItem("")),
                     table.setItem(table.rowCount() - 1, 1,
                                   QTableWidgetItem(""))))
        btn_del = QPushButton("Remove")
        btn_del.clicked.connect(
            lambda: (table.removeRow(table.currentRow())
                     if table.currentRow() >= 0 else None,
                     on_change()))
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        row.addStretch(1)
        if import_fn is not None:      # nothing to import a mouse chord from
            btn_imp = QPushButton("Import…")
            btn_imp.clicked.connect(import_fn)
            row.addWidget(btn_imp)
        return row

    def _restore_defaults(self):
        ret = QMessageBox.question(
            self, "Restore defaults",
            "Reset all settings (mouse, shortcuts, aliases, snaps) to "
            "defaults?")
        if ret != QMessageBox.StandardButton.Yes:
            return
        self.cfg.reset()
        self.window.apply_user_aliases()
        self.window.apply_user_shortcuts()
        vp = self.window.viewport
        vp.snaps.enabled = True
        for t in SNAP_TYPES:
            vp.snaps.types[t] = t in ("end", "mid", "center", "quad", "int")
        vp.grid_snap = False
        self.window.osnap_bar.refresh()
        self.accept()
