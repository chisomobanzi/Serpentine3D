"""Dockable chat panel for the in-app assistant."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from ..api import SerpApi
from ..ui.workspace_icons import workspace_icon
from .agent import Agent, build_system_prompt
from .client import DEFAULT_MODEL, AnthropicClient, resolve_api_key
from .connection_setup import ConnectionSetup
from .local_client import DEFAULT_ENDPOINT, LocalClient
from .openai_client import DEFAULT_MODEL as OPENAI_DEFAULT_MODEL, OpenAIClient
from .codex_client import CodexClient

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
        self._editing_connection = False
        self.setAccessibleName("Assistant")

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 0, 6, 0)
        root.setSpacing(0)

        header = QHBoxLayout()
        header.setSpacing(3)
        mark = QLabel()
        mark.setPixmap(workspace_icon("assistant", color="#88b6a7").pixmap(
            QSize(16, 16), self.devicePixelRatioF()))
        mark.setFixedSize(20, 20)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setAccessibleName("Assistant")
        header.addWidget(mark)
        self.recipient = QLabel()
        self.recipient.setMinimumWidth(0)
        self.recipient.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.recipient.setStyleSheet("color: #88b6a7; font-size: 11px;")
        self.usage = QLabel("")
        self.usage.setStyleSheet("color: #85868a; font-size: 11px;")
        self.btn_new = QPushButton()
        self.btn_new.setIcon(workspace_icon("plus"))
        self.btn_new.setStyleSheet("padding: 0;")
        self.btn_new.setAccessibleName("New chat")
        self.btn_new.setToolTip("New chat")
        self.btn_new.setFixedSize(26, 28)
        self.btn_new.clicked.connect(self._new_chat)
        self.btn_settings = QPushButton()
        self.btn_settings.setIcon(workspace_icon("settings"))
        self.btn_settings.setAccessibleName("Connection options")
        self.btn_settings.setToolTip("Connection options")
        self.btn_settings.setStyleSheet("padding: 0;")
        self.btn_settings.setFixedSize(26, 28)
        self.btn_settings.clicked.connect(self._toggle_connection_setup)
        header.addWidget(self.recipient, 1)
        header.addWidget(self.usage)
        header.addWidget(self.btn_new)
        header.addWidget(self.btn_settings)
        root.addLayout(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 2, 2)
        content_layout.setSpacing(6)
        self.setup_card = ConnectionSetup(self.cfg)
        self.setup_card.connected.connect(self._connection_saved)
        self.setup_card.changed.connect(self._refresh_mode)
        self.setup_card.disconnectRequested.connect(self._disconnect_account)
        # Keep the original standalone key entry API available to callers.
        self.key_edit = self.setup_card.key_edit
        content_layout.addWidget(self.setup_card)

        self.welcome = QWidget()
        welcome = QVBoxLayout(self.welcome)
        welcome.setContentsMargins(0, 4, 0, 4)
        welcome.setSpacing(6)
        intro = QLabel("Describe what to model, edit your selection, or ask about the scene.")
        intro.setWordWrap(True)
        welcome.addWidget(intro)
        examples = QHBoxLayout()
        for text, prompt in (("Make a box", "Make a 4 by 5 by 6 box"),
                             ("Inspect this scene", "What's in this scene?")):
            button = QPushButton(text)
            button.setToolTip("Draft an example prompt")
            button.clicked.connect(lambda checked=False, draft=prompt: self._draft_prompt(draft))
            examples.addWidget(button)
        examples.addStretch(1)
        welcome.addLayout(examples)
        content_layout.addWidget(self.welcome)
        self.feed_host = QWidget()
        self.feed = QVBoxLayout(self.feed_host)
        self.feed.setContentsMargins(2, 2, 2, 2)
        self.feed.setSpacing(8)
        self.feed.addStretch(1)
        content_layout.addWidget(self.feed_host, 1)
        self.scroll.setWidget(content)
        root.addWidget(self.scroll, 1)

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
        if (self.cfg.get("ai", "provider", default="") == "chatgpt"
                and self.cfg.get("ai", "chatgpt_connected", default=False)):
            self.setup_card.account_form.show()
            self.setup_card.account_choice.setChecked(True)
            QTimer.singleShot(0, lambda: self.setup_card.account_form.discover(restore=True))

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

    # ------------------------------------------------------------- connection

    def is_ready(self):
        provider, address, model, _vision = self._settings()
        if provider == "chatgpt":
            return self.setup_card.account_form.ready
        return bool(model and (provider == "lmstudio" or address))

    def _refresh_mode(self):
        provider, _address, model, _vision = self._settings()
        local = provider == "lmstudio"
        ready = self.is_ready()
        self.setup_card.setVisible(not ready or self._editing_connection)
        self.welcome.setVisible(ready and not self._editing_connection and self.feed.count() == 1)
        self.input_row.setVisible(ready and not self._external_composer)
        self.btn_send.setEnabled(ready)
        self.input.setPlaceholderText(
            "Ask about your model…" if ready else "Choose a connection above to send a prompt…")
        if local or provider == "chatgpt":
            metadata = next((m for m in self.cfg.get("ai", "local_models" if local else "chatgpt_models", default=[]) or []
                             if m.get("id") == model), {})
            model = metadata.get("label") or model
        provider_label = {"lmstudio": "LM Studio · local", "chatgpt": "ChatGPT",
                          "openai": "OpenAI"}.get(provider, "Anthropic")
        label = (f"{provider_label} · {model}" if ready
                 else "Choose a connection")
        if self.agent and self.agent.busy and self._client_settings != self._settings():
            label = f"{getattr(self.agent.client, 'model', 'Assistant')} · responding; settings apply next turn"
        self.recipient.setText(label)
        self.recipient.setToolTip(label)
        self.composerStateChanged.emit()

    def _toggle_connection_setup(self):
        self._editing_connection = not self._editing_connection
        self._refresh_mode()
        if self.setup_card.isVisibleTo(self):
            self.scroll.verticalScrollBar().setValue(0)

    def _connection_saved(self):
        self._editing_connection = False
        self._refresh_mode()

    def _disconnect_account(self):
        if self.agent:
            self.agent.stop()
            if isinstance(self.agent.client, CodexClient):
                self.agent.client.close()
                self._client_settings = None
        self.setup_card.account_form.disconnect_account()
        self._editing_connection = False
        self._refresh_mode()

    def shutdown(self):
        if self.agent:
            self.agent.stop()
            if hasattr(self.agent.client, "close"):
                self.agent.client.close()
        self.setup_card.account_form.close_connection()

    def _draft_prompt(self, prompt):
        self.input.setPlainText(prompt)
        workspace = getattr(self.window, "command_workspace", None)
        if workspace is not None:
            workspace.set_mode("ai")
        self.input.setFocus()

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
        if provider == "chatgpt":
            model = self.cfg.get("ai", "chatgpt_model", default="")
            metadata = next((m for m in self.cfg.get("ai", "chatgpt_models", default=[]) or []
                             if m.get("id") == model), {})
            account = self.setup_card.account_form
            # Include the process identity so rediscovery replaces a client
            # whose previous Codex process exited, even for the same model.
            return (provider, account.server if account.ready else None,
                    model, bool(metadata.get("vision")))
        if provider == "lmstudio":
            model = self.cfg.get("ai", "local_model", default="")
            metadata = next((m for m in self.cfg.get("ai", "local_models", default=[]) or []
                             if m.get("id") == model), {})
            return (provider, self.cfg.get("ai", "local_endpoint", default=DEFAULT_ENDPOINT),
                    model, bool(metadata.get("vision")))
        if provider == "openai":
            return (provider, resolve_api_key(self.cfg, provider),
                    self.cfg.get("ai", "openai_model", default=OPENAI_DEFAULT_MODEL), True)
        return (provider, resolve_api_key(self.cfg),
                self.cfg.get("ai", "model", default=DEFAULT_MODEL), True)

    def _save_key(self):
        self.setup_card.save_key()

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
                if provider == "chatgpt":
                    client = CodexClient(self.setup_card.account_form.server, model, vision=vision)
                elif provider == "lmstudio":
                    client = LocalClient(address, model, vision=vision)
                elif provider == "openai":
                    client = OpenAIClient(address, model)
                else:
                    client = AnthropicClient(address, model)
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
            if (hasattr(old_client, "close") and not (
                    isinstance(old_client, CodexClient) and isinstance(client, CodexClient)
                    and old_client.server is client.server)):
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
        self._refresh_mode()
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
        self.welcome.hide()
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
        if not tokens_in and not tokens_out:
            self.usage.clear()
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
