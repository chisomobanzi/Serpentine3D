"""Dockable chat panel for the in-app assistant."""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ..api import SerpApi
from .agent import Agent, build_system_prompt
from .client import DEFAULT_MODEL, AnthropicClient, resolve_api_key
from .local_client import DEFAULT_ENDPOINT, LocalClient

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

    composerStateChanged = Signal()

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.cfg = window.cfg
        self.agent: Agent | None = None
        self._client_settings = None
        self._stream_label: QLabel | None = None
        self._chips: list[QLabel] = []
        self._resetting = False
        self._external_composer = False
        self.setAccessibleName("Assistant")

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 0, 6, 0)
        root.setSpacing(0)

        header = QHBoxLayout()
        header.setSpacing(3)
        self.recipient = QLabel()
        self.recipient.setMinimumWidth(0)
        self.recipient.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.recipient.setStyleSheet("color: #88b6a7; font-size: 11px;")
        self.usage = QLabel("")
        self.usage.setStyleSheet("color: #85868a; font-size: 11px;")
        self.btn_new = QPushButton("+")
        self.btn_new.setAccessibleName("New chat")
        self.btn_new.setToolTip("New chat")
        self.btn_new.setFixedSize(26, 28)
        self.btn_new.clicked.connect(self._new_chat)
        self.btn_settings = QPushButton("Settings")
        self.btn_settings.setFixedHeight(28)
        self.btn_settings.clicked.connect(self._open_settings)
        header.addWidget(self.recipient, 1)
        header.addWidget(self.usage)
        header.addWidget(self.btn_new)
        header.addWidget(self.btn_settings)
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
        self.setup_intro = QLabel(
            "The assistant models with your own Anthropic API key "
            "(console.anthropic.com → API keys). The key is stored in "
            "your Serpentine3D config; the ANTHROPIC_API_KEY environment "
            "variable also works and is never written to disk.")
        self.setup_intro.setWordWrap(True)
        self.setup_intro.setStyleSheet("color: #85868a;")
        self.setup_key_row = QWidget()
        row = QHBoxLayout(self.setup_key_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("sk-ant-…")
        btn_save = QPushButton("Save key")
        btn_save.clicked.connect(self._save_key)
        row.addWidget(self.key_edit, 1)
        row.addWidget(btn_save)
        card.addWidget(self.setup_intro)
        card.addWidget(self.setup_key_row)
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

    def use_external_composer(self):
        """Give a containing workspace the input, retaining the chat and setup.

        Standalone panels keep their composer. In the workspace the same
        input (and therefore the same draft and send behavior) lives below
        all the panes, so hiding the conversation never hides the draft.
        """
        self.input_row.layout().removeWidget(self.input)
        self._external_composer = True
        self.input_row.hide()
        self.btn_send.hide()
        self._refresh_mode()
        return self.input

    # ------------------------------------------------------------- key mgmt

    def _refresh_mode(self):
        local = self.cfg.get("ai", "provider", default="anthropic") == "lmstudio"
        model = self.cfg.get("ai", "local_model" if local else "model",
                             default="" if local else DEFAULT_MODEL)
        ready = bool(model) if local else bool(resolve_api_key(self.cfg))
        self.setup_card.setVisible(not ready)
        self.input_row.setVisible(ready and not self._external_composer)
        self.setup_key_row.setVisible(not local and not self._external_composer)
        self.setup_intro.setText(
            "Choose LM Studio in Settings, enter its server URL, then refresh "
            "and select a local model. No cloud API key is needed." if local else
            "Add your Anthropic API key below, or open Settings to choose a "
            "local model with LM Studio. ANTHROPIC_API_KEY also works.")
        if self._external_composer:
            self.setup_intro.setText("Choose a local model or connect an API key in Settings.")
        label = f"{'LM Studio · local' if local else 'Anthropic'} · {model or 'choose a model in Settings'}"
        if self.agent and self.agent.busy and self._client_settings != self._settings():
            label = f"{getattr(self.agent.client, 'model', 'Assistant')} · responding; settings apply next turn"
        self.recipient.setText(label)
        self.recipient.setToolTip(label)
        self.composerStateChanged.emit()

    def _open_settings(self):
        from ..ui.settings_dialog import SettingsDialog
        dialog = SettingsDialog(self.window)
        for index in range(dialog.sidebar.count()):
            if dialog.sidebar.item(index).text() == "Assistant":
                dialog.sidebar.setCurrentRow(index)
                break
        dialog.finished.connect(self._refresh_mode)
        dialog.show()

    def _settings(self):
        provider = self.cfg.get("ai", "provider", default="anthropic")
        if provider == "lmstudio":
            model = self.cfg.get("ai", "local_model", default="")
            metadata = next((m for m in self.cfg.get("ai", "local_models", default=[]) or []
                             if m.get("id") == model), {})
            return (provider, self.cfg.get("ai", "local_endpoint", default=DEFAULT_ENDPOINT),
                    model, bool(metadata.get("vision")))
        return (provider, resolve_api_key(self.cfg),
                self.cfg.get("ai", "model", default=DEFAULT_MODEL), True)

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
        # A settings change or duplicate Enter must never rewrite an in-flight
        # client's model between a tool call and its result.
        if self.agent and self.agent.busy:
            return self.agent
        settings = self._settings()
        provider, address, model, vision = settings
        if not model or (provider != "lmstudio" and not address):
            self._refresh_mode()
            return None
        client = None
        if self.agent is None or settings != self._client_settings:
            try:
                client = (LocalClient(address, model, vision=vision)
                          if provider == "lmstudio" else AnthropicClient(address, model))
            except Exception as exc:
                self._on_error(str(exc))
                return None
        if self.agent is None:
            self.agent = Agent(SerpApi(self.window), client, parent=self)
            self.agent.textDelta.connect(self._on_text)
            self.agent.toolStarted.connect(self._on_tool_start)
            self.agent.toolFinished.connect(self._on_tool_finish)
            self.agent.turnFinished.connect(self._on_finished)
            self.agent.errorRaised.connect(self._on_error)
            self.agent.usageUpdated.connect(self._on_usage)
            # Always queue the reset acknowledgement so older queued worker
            # updates are discarded before this new conversation is enabled.
            self.agent.conversationReset.connect(
                self._on_conversation_reset, Qt.ConnectionType.QueuedConnection)
        elif client is not None:
            old_client = self.agent.client
            self.agent.client = client
            self.agent.system = build_system_prompt(vision)
            if hasattr(old_client, "close"):
                old_client.close()
        self._client_settings = settings
        self._refresh_mode()
        return self.agent

    def _new_chat(self):
        self._resetting = self.agent is not None
        while self.feed.count() > 1:
            item = self.feed.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._stream_label = None
        self._chips.clear()
        self.usage.setText("")
        if self.agent:
            self.btn_send.setText("Stopping…" if self.agent.busy else "Send")
            self.input.setEnabled(False)
            self.agent.reset()
        self.composerStateChanged.emit()

    def _on_conversation_reset(self):
        self._resetting = False
        self._on_finished("reset")

    # ---------------------------------------------------------------- send

    def _send_or_stop(self):
        if self.agent and self.agent.busy:
            self.agent.stop()
            self.btn_send.setText("Stopping…")
            self.composerStateChanged.emit()
            return
        self._send()

    def _send(self):
        if self._resetting or (self.agent and self.agent.busy):
            return
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
        self.composerStateChanged.emit()

    # -------------------------------------------------------------- events

    def _on_text(self, delta: str):
        if self._resetting:
            return
        if self._stream_label is None:
            self._stream_label = self._add_label("", wrap=True)
        self._stream_label.setText(self._stream_label.text() + delta)
        self._scroll_down()

    def _on_tool_start(self, name: str, summary: str):
        if self._resetting:
            return
        self._stream_label = None          # next text starts a fresh block
        chip = self._add_label(f"→ {summary} …", wrap=True)
        chip.setStyleSheet(_CHIP_RUNNING)
        self._chips.append(chip)
        self._scroll_down()

    def _on_tool_finish(self, name: str, ok: bool, summary: str):
        if self._resetting or not self._chips:
            return
        chip = self._chips[-1]
        mark = "✓" if ok else "✗"
        base = chip.text().rstrip(" …")
        chip.setText(f"{base}  {mark}" + ("" if ok else f"  {summary}"))
        chip.setStyleSheet(_CHIP_OK if ok else _CHIP_FAIL)

    def _on_finished(self, reason: str):
        if self._resetting:
            return
        self._stream_label = None
        self.btn_send.setText("Send")
        self.input.setEnabled(True)
        # Completion is asynchronous: the user may now be editing Python or
        # working in a viewport. Re-enable the composer without moving focus.
        self.composerStateChanged.emit()
        if reason == "step limit reached":
            lbl = self._add_label(
                "(stopped at the step limit — say “continue” to keep going)",
                wrap=True)
            lbl.setStyleSheet("color: #85868a; font-size: 11px;")
        self._scroll_down()
        self._refresh_mode()

    def _on_error(self, message: str):
        if self._resetting:
            return
        self._stream_label = None
        lbl = self._add_label(message, wrap=True)
        lbl.setStyleSheet(_ERR_STYLE)
        self.btn_send.setText("Send")
        self.input.setEnabled(True)
        self.composerStateChanged.emit()
        self._scroll_down()

    def _on_usage(self, tokens_in: int, tokens_out: int):
        if self._resetting:
            return
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
