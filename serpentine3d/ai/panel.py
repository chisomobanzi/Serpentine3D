"""Dockable chat panel for the in-app assistant."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ..api import SerpApi
from .agent import Agent
from .client import DEFAULT_MODEL, AnthropicClient, resolve_api_key

_CHIP_RUNNING = "color: #8fa3b8; font-family: monospace; font-size: 11px;"
_CHIP_OK = "color: #7fb069; font-family: monospace; font-size: 11px;"
_CHIP_FAIL = "color: #d9705f; font-family: monospace; font-size: 11px;"
_USER_STYLE = ("background: #2b3b4d; color: #e8e9ea; padding: 6px 10px;"
               "border-radius: 6px;")
_ERR_STYLE = "color: #d9705f;"
_HINT = ("Try: “a spiral staircase, 3 m tall, 14 steps” · “fillet every "
         "edge of the box 2 mm” · “what's in this scene?”")


class PromptInput(QPlainTextEdit):
    """Multi-line input: Enter sends, Shift+Enter inserts a newline."""

    submitted = Signal()

    def keyPressEvent(self, ev: QKeyEvent):
        if (ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not ev.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submitted.emit()
            ev.accept()
            return
        super().keyPressEvent(ev)


class AiPanel(QWidget):
    """The assistant's chat UI. Owns the Agent for this window."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.cfg = window.cfg
        self.agent: Agent | None = None
        self._stream_label: QLabel | None = None
        self._chips: list[QLabel] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        header = QHBoxLayout()
        title = QLabel("Assistant")
        title.setStyleSheet("font-weight: bold;")
        self.usage = QLabel("")
        self.usage.setStyleSheet("color: #85868a; font-size: 11px;")
        self.btn_new = QPushButton("New chat")
        self.btn_new.setFixedHeight(22)
        self.btn_new.clicked.connect(self._new_chat)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.usage)
        header.addWidget(self.btn_new)
        root.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.feed_host = QWidget()
        self.feed = QVBoxLayout(self.feed_host)
        self.feed.setContentsMargins(2, 2, 2, 2)
        self.feed.setSpacing(8)
        self.feed.addStretch(1)
        self.scroll.setWidget(self.feed_host)
        root.addWidget(self.scroll, 1)

        # --- key setup card (swapped with the input row) ---
        self.setup_card = QWidget()
        card = QVBoxLayout(self.setup_card)
        card.setContentsMargins(0, 0, 0, 0)
        intro = QLabel(
            "The assistant models with your own Anthropic API key "
            "(console.anthropic.com → API keys). The key is stored in "
            "your Serpentine3D config; the ANTHROPIC_API_KEY environment "
            "variable also works and is never written to disk.")
        intro.setWordWrap(True)
        intro.setStyleSheet("color: #85868a;")
        row = QHBoxLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-ant-…")
        btn_save = QPushButton("Save key")
        btn_save.clicked.connect(self._save_key)
        row.addWidget(self.key_edit, 1)
        row.addWidget(btn_save)
        card.addWidget(intro)
        card.addLayout(row)
        root.addWidget(self.setup_card)

        # --- input row ---
        self.input_row = QWidget()
        irow = QVBoxLayout(self.input_row)
        irow.setContentsMargins(0, 0, 0, 0)
        irow.setSpacing(4)
        self.input = PromptInput()
        self.input.setPlaceholderText(
            "Describe what to model… (Enter to send)")
        self.input.setFixedHeight(64)
        self.input.submitted.connect(self._send)
        self.btn_send = QPushButton("Send")
        self.btn_send.clicked.connect(self._send_or_stop)
        hint = QLabel(_HINT)
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #6a6b70; font-size: 10px;")
        srow = QHBoxLayout()
        srow.addWidget(hint, 1)
        srow.addWidget(self.btn_send)
        irow.addWidget(self.input)
        irow.addLayout(srow)
        root.addWidget(self.input_row)

        self._refresh_mode()

    # ------------------------------------------------------------- key mgmt

    def _refresh_mode(self):
        has_key = bool(resolve_api_key(self.cfg))
        self.setup_card.setVisible(not has_key)
        self.input_row.setVisible(has_key)

    def _save_key(self):
        key = self.key_edit.text().strip()
        if not key:
            return
        self.cfg.set("ai", "api_key", key)
        self.cfg.save()
        self.key_edit.clear()
        self._refresh_mode()
        self.input.setFocus()

    # --------------------------------------------------------------- agent

    def _ensure_agent(self) -> Agent | None:
        key = resolve_api_key(self.cfg)
        if not key:
            self._refresh_mode()
            return None
        model = self.cfg.get("ai", "model", default=DEFAULT_MODEL)
        if self.agent is None:
            self.agent = Agent(SerpApi(self.window),
                               AnthropicClient(key, model), parent=self)
            self.agent.textDelta.connect(self._on_text)
            self.agent.toolStarted.connect(self._on_tool_start)
            self.agent.toolFinished.connect(self._on_tool_finish)
            self.agent.turnFinished.connect(self._on_finished)
            self.agent.errorRaised.connect(self._on_error)
            self.agent.usageUpdated.connect(self._on_usage)
        else:
            self.agent.client.api_key = key
            self.agent.client.model = model
        return self.agent

    def _new_chat(self):
        if self.agent and self.agent.busy:
            self.agent.stop()
        if self.agent:
            self.agent.reset()
        while self.feed.count() > 1:
            item = self.feed.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._stream_label = None
        self.usage.setText("")

    # ---------------------------------------------------------------- send

    def _send_or_stop(self):
        if self.agent and self.agent.busy:
            self.agent.stop()
            self.btn_send.setText("Stopping…")
            return
        self._send()

    def _send(self):
        text = self.input.toPlainText().strip()
        if not text:
            return
        agent = self._ensure_agent()
        if agent is None or agent.busy:
            return
        self.input.clear()
        self._add_user_bubble(text)
        self._stream_label = None
        self.btn_send.setText("Stop")
        self.input.setEnabled(False)
        agent.send(text)

    # -------------------------------------------------------------- events

    def _on_text(self, delta: str):
        if self._stream_label is None:
            self._stream_label = self._add_label("", wrap=True)
        self._stream_label.setText(self._stream_label.text() + delta)
        self._scroll_down()

    def _on_tool_start(self, name: str, summary: str):
        self._stream_label = None          # next text starts a fresh block
        chip = self._add_label(f"→ {summary} …", wrap=True)
        chip.setStyleSheet(_CHIP_RUNNING)
        self._chips.append(chip)
        self._scroll_down()

    def _on_tool_finish(self, name: str, ok: bool, summary: str):
        if not self._chips:
            return
        chip = self._chips[-1]
        mark = "✓" if ok else "✗"
        base = chip.text().rstrip(" …")
        chip.setText(f"{base}  {mark}" + ("" if ok else f"  {summary}"))
        chip.setStyleSheet(_CHIP_OK if ok else _CHIP_FAIL)

    def _on_finished(self, reason: str):
        self._stream_label = None
        self.btn_send.setText("Send")
        self.input.setEnabled(True)
        self.input.setFocus()
        if reason == "step limit reached":
            lbl = self._add_label(
                "(stopped at the step limit — say “continue” to keep going)",
                wrap=True)
            lbl.setStyleSheet("color: #85868a; font-size: 11px;")
        self._scroll_down()

    def _on_error(self, message: str):
        self._stream_label = None
        lbl = self._add_label(message, wrap=True)
        lbl.setStyleSheet(_ERR_STYLE)
        self.btn_send.setText("Send")
        self.input.setEnabled(True)
        self._scroll_down()

    def _on_usage(self, tokens_in: int, tokens_out: int):
        self.usage.setText(f"{tokens_in / 1000:.1f}k in · "
                           f"{tokens_out / 1000:.1f}k out")

    # ------------------------------------------------------------- widgets

    def _add_user_bubble(self, text: str):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(_USER_STYLE)
        lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(lbl)
        host = QWidget()
        host.setLayout(row)
        self.feed.insertWidget(self.feed.count() - 1, host)
        self._scroll_down()

    def _add_label(self, text: str, wrap: bool = False) -> QLabel:
        lbl = QLabel(text)
        lbl.setWordWrap(wrap)
        lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setSizePolicy(QSizePolicy.Policy.Preferred,
                          QSizePolicy.Policy.Minimum)
        self.feed.insertWidget(self.feed.count() - 1, lbl)
        return lbl

    def _scroll_down(self):
        QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(
            self.scroll.verticalScrollBar().maximum()))
