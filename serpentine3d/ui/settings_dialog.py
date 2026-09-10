"""Settings dialog: sidebar categories, changes apply immediately.

Deliberately not Rhino's option-tree maze: a handful of flat pages, plain
language, live apply, and one-click import for Rhino alias files.
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView,
    QLabel,
    QListWidget, QMessageBox, QPushButton, QRadioButton, QSlider, QSpinBox,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..commands import base as cmd_base
from ..core.snaps import SNAP_TYPES
from ..utils.config import parse_chord, parse_rhino_aliases, parse_shortcuts
from .dialogs import untether


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


class _ModelDiscovery(QObject):
    finished = Signal(str, object, str)

    def start(self, endpoint: str):
        def fetch():
            from ..ai.local_client import discover_models
            try:
                models, error = discover_models(endpoint), ""
            except Exception as exc:
                models, error = [], str(exc)
            try:
                self.finished.emit(endpoint, models, error)
            except RuntimeError:
                # The dialog owns this signal object and can be destroyed
                # while HTTP is in flight. Qt has already disconnected its
                # receivers; a completed request then has nothing to update.
                pass
        threading.Thread(target=fetch, daemon=True).start()


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
        footer = QHBoxLayout()
        footer.addWidget(btn_defaults)
        footer.addStretch(1)
        note = QLabel("Changes apply immediately")
        note.setStyleSheet("color: #85868a; font-size: 11px;")
        footer.addWidget(note)
        footer.addSpacing(12)
        footer.addWidget(btn_close)

        body = QHBoxLayout()
        body.addWidget(self.sidebar)
        body.addWidget(self.pages, 1)
        root = QVBoxLayout(self)
        root.addLayout(body, 1)
        root.addLayout(footer)

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
        for key, cmd in sorted(
                (self.cfg.get("shortcuts", default={}) or {}).items()):
            self._add_row(self.key_table, key, cmd)
        layout.addWidget(self.key_table, 2)   # more keys get bound than chords
        layout.addLayout(self._table_buttons(
            self.key_table, self._import_shortcuts,
            on_change=self._shortcuts_changed))

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
        bad = []
        for r in range(self.key_table.rowCount()):
            key_item = self.key_table.item(r, 0)
            cmd_item = self.key_table.item(r, 1)
            if not key_item or not cmd_item:
                continue
            key = key_item.text().strip()
            cmd = cmd_item.text().strip().lower()
            if not key or not cmd:
                continue
            if QKeySequence(key).isEmpty():
                bad.append(key)
                continue
            shortcuts[key] = cmd
        self.cfg.set("shortcuts", shortcuts)
        self.window.apply_user_shortcuts()

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
            "Choose who receives Ask AI messages. LM Studio runs models on "
            "your local server; Anthropic uses your own cloud API key. "
            "Changes during a response apply to the next turn.")

        self._ai_loading = True
        row_provider = QHBoxLayout()
        row_provider.addWidget(QLabel("Provider"))
        self.cb_ai_provider = QComboBox()
        self.cb_ai_provider.addItem("Anthropic", "anthropic")
        self.cb_ai_provider.addItem("LM Studio", "lmstudio")
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
        self.ed_ai_key.setPlaceholderText("sk-ant-…")
        self.ed_ai_key.setText(
            str(self.cfg.get("ai", "api_key", default="") or ""))
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
        self._ai_provider_changed()
        layout.addStretch(1)
        return w

    def _ai_changed(self):
        if self._ai_loading:
            return
        from ..ai.local_client import DEFAULT_ENDPOINT

        self.cfg.set("ai", "api_key", self.ed_ai_key.text().strip())
        local = self.cb_ai_provider.currentData() == "lmstudio"
        self.cfg.set("ai", "provider", self.cb_ai_provider.currentData())
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
        if self.cb_ai_model.currentData():
            self.cfg.set("ai", "local_model" if local else "model", self.cb_ai_model.currentData())
        self.cfg.save()
        # Settings also apply when the assistant pane was already open.
        from ..ai.panel import AiPanel
        for panel in self.window.findChildren(AiPanel):
            panel._refresh_mode()

    def _ai_provider_changed(self, *_):
        from ..ai.client import DEFAULT_MODEL, MODELS
        self._ai_loading = True
        local = self.cb_ai_provider.currentData() == "lmstudio"
        self.ai_key_row.setVisible(not local)
        self.ai_endpoint_row.setVisible(local)
        self.cb_ai_model.clear()
        if local:
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
            current = self.cfg.get("ai", "model", default=DEFAULT_MODEL)
            for model_id, label in MODELS:
                self.cb_ai_model.addItem(label, model_id)
            self.ai_note.setText("The key is stored in your Serpentine3D config. "
                                 "ANTHROPIC_API_KEY takes precedence and is never saved. "
                                 "Usage is billed to your Anthropic account.")
        index = self.cb_ai_model.findData(current)
        self.cb_ai_model.setCurrentIndex(max(0, index))
        self.ai_discovery_status.clear()
        self._ai_loading = False
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
        layout.addStretch(1)
        return w

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
        for r in range(table.rowCount()):
            if table.item(r, 0) and table.item(r, 0).text() == a:
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
