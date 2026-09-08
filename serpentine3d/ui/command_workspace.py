"""The bottom workspace: history, optional panes, and an explicit composer."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QMenu, QPushButton,
    QSizePolicy, QSplitter, QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)


class CommandWorkspace(QWidget):
    """Keep pane layout independent from the destination of typed input."""

    def __init__(self, window, command_line, tab_row, osnap_bar):
        super().__init__(window)
        self.window = window
        self.command_line = command_line
        self.mode = "command"
        self.assistant = None
        self.console = None
        self._order = "script-first"
        self._collapsed = False
        self._expanded_height = 360
        self._pane_widths = {}
        self.setObjectName("commandWorkspace")
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Preferred)
        self.setStyleSheet("""
            QWidget#commandWorkspace { background: #202226; color: #d4d6d5; }
            QFrame#workspaceComposer { background: #242529;
                border-top: 1px solid #383a3c; }
            QFrame#workspaceComposer[mode="ai"] { border-color: #477d73; }
            QPushButton, QToolButton { background: transparent; color: #adb3b4;
                border: 1px solid transparent; border-radius: 3px;
                padding: 3px 8px; }
            QPushButton:hover, QToolButton:hover { background: #33363a;
                color: #e7e7de; }
            QPushButton:disabled, QToolButton:disabled { color: #62676b; }
            QPushButton:checked, QToolButton:checked { background: #39372f; color: #dbc087;
                border-bottom-color: #aa8b49; }
            QPushButton#aiMode:checked { background: #29473f;
                color: #9bd3c3; border-bottom-color: #4c8273; }
            QPushButton#workspaceSubmit { background: #39372f;
                color: #dbc087; padding: 3px 10px; }
            QPushButton#workspaceSubmit[mode="ai"] { background: #294b42;
                color: #a9dfce; border-color: #4c8273; }
            QSplitter::handle { background: #303236; width: 3px; }
            QSplitter::handle:hover { background: #867352; }
            QToolButton::menu-indicator { image: none; width: 0px; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(tab_row)

        # Space tabs and workspace controls share one strip, leaving the
        # vertical room to the drawing and the pane contents.
        toolbar = tab_row.layout()
        toolbar.setContentsMargins(0, 0, 2, 0)
        self.assistant_toggle = self._toggle("Assistant")
        self.script_toggle = self._toggle("Script")
        self.assistant_toggle.toggled.connect(
            lambda shown: self.set_pane_visible("assistant", shown))
        self.script_toggle.toggled.connect(
            lambda shown: self.set_pane_visible("script", shown))
        toolbar.addWidget(self.assistant_toggle)
        toolbar.addWidget(self.script_toggle)
        arrange = QToolButton()
        arrange.setText("⋯")
        arrange.setAccessibleName("Arrange")
        arrange.setToolTip("Arrange workspace")
        arrange.setFixedWidth(28)
        arrange.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(arrange)
        menu.addAction("History → Script → Assistant",
                       lambda: self.set_order("script-first"))
        menu.addAction("History → Assistant → Script",
                       lambda: self.set_order("assistant-first"))
        menu.addSeparator()
        menu.addAction("Reset pane widths", self.reset_widths)
        arrange.setMenu(menu)
        toolbar.addWidget(arrange)
        self.expand_button = QToolButton()
        self.expand_button.setText("⤢")
        self.expand_button.setAccessibleName("Expand")
        self.expand_button.setFixedWidth(28)
        self.expand_button.setToolTip("Expand workspace")
        self.expand_button.clicked.connect(self.expand)
        toolbar.addWidget(self.expand_button)
        self.collapse_button = QToolButton()
        self.collapse_button.setFixedWidth(28)
        self.collapse_button.clicked.connect(
            lambda: self.set_collapsed(not self._collapsed))
        toolbar.addWidget(self.collapse_button)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(3)
        self.history_pane = QWidget()
        history = QVBoxLayout(self.history_pane)
        history.setContentsMargins(0, 0, 0, 0)
        history.setSpacing(0)
        command_line.echo_view.setAccessibleName("Command history")
        command_line.echo_view.setToolTip("Command history · commands, AI, MCP and scripts")
        # Reparent the existing history instead of copying its document.
        history.addWidget(command_line.echo_view)
        self.script_pane = QWidget()
        script = QVBoxLayout(self.script_pane)
        script.setContentsMargins(4, 0, 4, 0)
        script.setSpacing(0)
        self.assistant_pane = QWidget()
        assistant = QVBoxLayout(self.assistant_pane)
        assistant.setContentsMargins(0, 0, 0, 0)
        self._panes = {"history": self.history_pane,
                       "script": self.script_pane,
                       "assistant": self.assistant_pane}
        for pane in self._panes.values():
            pane.setMinimumWidth(150)
            self.splitter.addWidget(pane)
        self.script_pane.hide()
        self.assistant_pane.hide()
        root.addWidget(self.splitter, 1)

        self.composer = QFrame()
        self.composer.setObjectName("workspaceComposer")
        composer = QHBoxLayout(self.composer)
        composer.setContentsMargins(6, 3, 6, 3)
        composer.setSpacing(3)
        group = QButtonGroup(self)
        self.command_mode = self._toggle("Command")
        self.ai_mode = self._toggle("Ask AI")
        self.ai_mode.setObjectName("aiMode")
        for button in (self.command_mode, self.ai_mode):
            group.addButton(button)
            composer.addWidget(button, 0, Qt.AlignmentFlag.AlignVCenter)
        self.command_mode.setChecked(True)
        self.command_mode.clicked.connect(lambda: self.set_mode("command"))
        self.ai_mode.clicked.connect(lambda: self.set_mode("ai"))
        self.command_mode.setToolTip("Command input · Alt+/ switches destination")
        self.ai_mode.setToolTip("Ask AI · Alt+/ switches destination")
        shortcut = QShortcut(QKeySequence("Alt+/"), self)
        shortcut.activated.connect(
            lambda: self.set_mode("ai" if self.mode == "command" else "command"))
        command_line.set_compact(True)
        self.inputs = QStackedWidget()
        self.inputs.addWidget(command_line)
        self.ai_input_host = QWidget()
        ai_input_layout = QVBoxLayout(self.ai_input_host)
        ai_input_layout.setContentsMargins(3, 0, 3, 0)
        self.inputs.addWidget(self.ai_input_host)
        composer.addWidget(self.inputs, 1)
        self.submit_button = QPushButton("Run command")
        self.submit_button.setObjectName("workspaceSubmit")
        self.submit_button.clicked.connect(self.submit)
        composer.addWidget(self.submit_button, 0, Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self.composer)
        root.addWidget(osnap_bar)
        command_line.input.textChanged.connect(self._update_draft_hint)
        command_line.suggestion_anchor = self
        self._update_composer()
        self._update_collapse_control()

    @staticmethod
    def _toggle(text):
        button = QPushButton(text)
        button.setCheckable(True)
        return button

    def sizeHint(self):
        if self._collapsed:
            return QSize(1000, self.minimumSizeHint().height())
        if self.script_toggle.isChecked():
            return QSize(1000, min(360, max(280, int(self.window.height() * .34))))
        return QSize(1000, 280 if self.assistant_toggle.isChecked() else 180)

    def _ensure_assistant(self):
        if self.assistant is None:
            from ..ai.panel import AiPanel
            self.assistant = AiPanel(self.window)
            self.assistant_pane.layout().addWidget(self.assistant)
            field = self.assistant.use_external_composer()
            field.setAccessibleName("AI assistant input")
            field.setPlaceholderText("Ask about your model…")
            field.setFixedHeight(48)
            field.setStyleSheet(
                "QPlainTextEdit { background: #202b28; color: #d0e5dc;"
                " border: 1px solid #50766b; border-radius: 4px; padding: 4px; }")
            self.ai_input_host.layout().addWidget(field)
            field.textChanged.connect(self._update_draft_hint)
            field.submitted.connect(self.show_assistant)
            self.assistant.composerStateChanged.connect(self._update_composer)
        return self.assistant

    def _ensure_script(self):
        if self.console is None:
            from .script_editor import ScriptEditor
            self.console = ScriptEditor(self.window)
            self.script_pane.layout().addWidget(self.console, 1)
        return self.console

    def show_assistant(self):
        panel = self._ensure_assistant()
        self.set_pane_visible("assistant", True)
        panel._refresh_mode()
        return panel

    def toggle_script(self):
        self.set_pane_visible("script", not self.script_toggle.isChecked())

    def set_pane_visible(self, name, shown):
        self._remember_widths()
        if shown:
            (self._ensure_assistant if name == "assistant"
             else self._ensure_script)()
        button = (self.assistant_toggle if name == "assistant"
                  else self.script_toggle)
        button.blockSignals(True)
        button.setChecked(shown)
        button.blockSignals(False)
        self._panes[name].setVisible(shown)
        if shown and self._collapsed:
            self.set_collapsed(False)
        self._restore_widths()
        preferred_height = self.sizeHint().height()
        if shown and self.window.isVisible() and self.height() < preferred_height:
            self.window.resizeDocks([self.window._cmd_dock], [preferred_height],
                                    Qt.Orientation.Vertical)

    def _active_names(self):
        return [name for name in self._ordered_names()
                if not self._panes[name].isHidden()]

    def _ordered_names(self):
        return (["history", "script", "assistant"]
                if self._order == "script-first"
                else ["history", "assistant", "script"])

    def _remember_widths(self):
        if self._collapsed:
            return
        names = self._active_names()
        widths = {name: self.splitter.sizes()[self.splitter.indexOf(self._panes[name])]
                  for name in names}
        if widths and all(value > 0 for value in widths.values()):
            self._pane_widths[",".join(names)] = widths

    def _restore_widths(self):
        names = self._active_names()
        widths = self._pane_widths.get(",".join(names), {})
        self.splitter.setSizes([widths.get(name, 350) if name in names else 0
                                for name in self._ordered_names()])

    def set_order(self, order):
        if order not in ("script-first", "assistant-first"):
            return
        self._remember_widths()
        self._order = order
        for index, name in enumerate(self._ordered_names()):
            self.splitter.insertWidget(index, self._panes[name])
        self._restore_widths()

    def reset_widths(self):
        self._pane_widths.clear()
        self._restore_widths()

    def set_mode(self, mode):
        if mode not in ("command", "ai"):
            return
        self.command_line.suggestions.hide()
        if mode == "ai":
            self.show_assistant()
        self.mode = mode
        self.command_mode.setChecked(mode == "command")
        self.ai_mode.setChecked(mode == "ai")
        self.inputs.setCurrentIndex(1 if mode == "ai" else 0)
        self._update_composer()
        self.focus_input()

    def focus_input(self):
        field = (self.assistant.input if self.mode == "ai"
                 else self.command_line.input)
        field.setFocus()

    def submit(self):
        if self.mode == "ai":
            self.show_assistant()._send_or_stop()
        else:
            self.command_line.submit_input()
            self.command_line.focus()

    def _update_composer(self):
        ai = self.mode == "ai"
        # QStackedWidget otherwise reserves the hidden multiline AI page's
        # height even in Command mode. Only the active input needs that room.
        for index in range(self.inputs.count()):
            page = self.inputs.widget(index)
            page.setSizePolicy(QSizePolicy.Policy.Expanding,
                               QSizePolicy.Policy.Preferred if index == int(ai)
                               else QSizePolicy.Policy.Ignored)
        self.inputs.updateGeometry()
        busy = bool(ai and self.assistant and self.assistant.agent
                    and self.assistant.agent.busy)
        label = "Stop" if busy else "Send to AI" if ai else "Run command"
        if busy and self.assistant.btn_send.text() == "Stopping…":
            label = "Stopping…"
        self.submit_button.setText(label)
        self.inputs.setToolTip(
            "Enter to send · Shift+Enter for a new line" if ai else
            "Enter to run · Esc to clear · History stays visible")
        for widget in (self.composer, self.submit_button):
            widget.setProperty("mode", self.mode)
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self._update_draft_hint()

    def _update_draft_hint(self):
        for button, has_draft, label in (
            (self.command_mode, bool(self.command_line.input.text()), "Command"),
            (self.ai_mode, bool(self.assistant and self.assistant.input.toPlainText()), "Ask AI"),
        ):
            draft = " · draft saved" if has_draft else ""
            button.setToolTip(f"{label}{draft} · Alt+/ switches destination")

    def _update_collapse_control(self):
        label = "Restore workspace" if self._collapsed else "Collapse workspace"
        self.collapse_button.setText("⌃" if self._collapsed else "⌄")
        self.collapse_button.setAccessibleName(label)
        self.collapse_button.setToolTip(label)
        self.expand_button.setEnabled(not self._collapsed)

    def set_collapsed(self, collapsed):
        if collapsed == self._collapsed:
            return
        self._remember_widths()
        if collapsed:
            self._expanded_height = self.height()
        self._collapsed = collapsed
        self.splitter.setVisible(not collapsed)
        self._update_collapse_control()
        if not collapsed:
            self._restore_widths()
        self.layout().activate()
        if hasattr(self.window, "_cmd_dock"):
            height = self.minimumSizeHint().height() if collapsed else self._expanded_height
            self.window.resizeDocks([self.window._cmd_dock], [height],
                                    Qt.Orientation.Vertical)

    def expand(self):
        self.set_collapsed(False)
        height = min(int(self.window.height() * .62), self.height() + 180)
        self.window.resizeDocks([self.window._cmd_dock], [height],
                                Qt.Orientation.Vertical)

    def save_settings(self):
        self._remember_widths()
        self.window.cfg.set("workspace", {
            "assistant": self.assistant_toggle.isChecked(),
            "script": self.script_toggle.isChecked(),
            "order": self._order,
            "widths": self._pane_widths,
            "collapsed": self._collapsed,
            "expanded_height": self._expanded_height,
        })

    def restore_settings(self):
        cfg = self.window.cfg
        self.set_order(cfg.get("workspace", "order", default="script-first"))
        for name in ("assistant", "script"):
            self.set_pane_visible(name, bool(cfg.get("workspace", name, default=False)))
        widths = cfg.get("workspace", "widths", default={})
        if isinstance(widths, dict):
            self._pane_widths = {key: value for key, value in widths.items()
                                 if isinstance(value, dict)
                                 and all(isinstance(w, (int, float)) and w > 0
                                         for w in value.values())}
        self._restore_widths()
        self.set_collapsed(bool(cfg.get("workspace", "collapsed", default=False)))
        height = cfg.get("workspace", "expanded_height", default=360)
        if isinstance(height, (int, float)) and height > 0:
            self._expanded_height = int(height)
        QTimer.singleShot(0, self, self._restore_widths)
