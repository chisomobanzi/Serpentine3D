"""Settings dialog: sidebar categories, changes apply immediately.

Deliberately not Rhino's option-tree maze: five flat pages, plain language,
live apply, and one-click import for Rhino alias files.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QListWidget, QMessageBox, QPushButton, QRadioButton, QSlider, QSpinBox,
    QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..commands import base as cmd_base
from ..core.snaps import SNAP_TYPES
from ..utils.config import parse_rhino_aliases, parse_shortcuts


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


class SettingsDialog(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.cfg = window.cfg
        self.setWindowTitle("Serpentine3D Settings")
        self.resize(760, 500)

        self.sidebar = QListWidget()
        self.sidebar.setFixedWidth(160)
        self.pages = QStackedWidget()
        for name, builder in [
            ("Mouse", self._mouse_page),
            ("Keyboard", self._keyboard_page),
            ("Aliases", self._aliases_page),
            ("Object Snaps", self._osnap_page),
            ("Display", self._display_page),
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
                          "How the mouse drives the viewport. Pan is always "
                          "Shift + the orbit button; left button selects and "
                          "picks points.")
        self.rb_middle = QRadioButton("Orbit with the middle mouse button "
                                      "(Rhino default)")
        self.rb_right = QRadioButton("Orbit with the right mouse button")
        current = self.cfg.get("mouse", "orbit_button", default="middle")
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
        layout.addStretch(1)
        return w

    def _mouse_changed(self, *_):
        self.cfg.set("mouse", "orbit_button",
                     "right" if self.rb_right.isChecked() else "middle")
        self.cfg.set("mouse", "invert_scroll", self.cb_invert.isChecked())
        self.cfg.set("mouse", "orbit_speed", self.sl_orbit.value() / 100.0)
        self.cfg.set("mouse", "zoom_speed", self.sl_zoom.value() / 100.0)

    # ---------------------------------------------------------- keyboard

    def _keyboard_page(self) -> QWidget:
        w, layout = _page("Keyboard Shortcuts",
                          "Bind any key to any command. Import accepts "
                          "simple text files ('F5 zoomextents' or "
                          "'ctrl+b=box' per line) or JSON.")
        self.key_table = QTableWidget(0, 2)
        self.key_table.setHorizontalHeaderLabels(["Shortcut", "Command"])
        self.key_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self.key_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        for key, cmd in sorted(
                (self.cfg.get("shortcuts", default={}) or {}).items()):
            self._add_row(self.key_table, key, cmd)
        self.key_table.itemChanged.connect(self._shortcuts_changed)
        layout.addWidget(self.key_table, 1)
        layout.addLayout(self._table_buttons(
            self.key_table, self._import_shortcuts,
            on_change=self._shortcuts_changed))
        return w

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
            parsed = parse_shortcuts(open(path).read())
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
            aliases, unmapped = parse_rhino_aliases(open(path).read())
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
            "center": "Circle/arc centers", "quad": "Quadrant points",
            "int": "Intersections",
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
        layout.addStretch(1)
        return w

    def _display_changed(self, *_):
        self.cfg.set("display", "grid_extent", self.sp_extent.value())
        self.cfg.set("display", "grid_major", self.sp_major.value())
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
        btn_imp = QPushButton("Import…")
        btn_imp.clicked.connect(import_fn)
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        row.addStretch(1)
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
