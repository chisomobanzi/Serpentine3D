"""Asynchronous managed ChatGPT sign-in and model selection."""

import queue
import threading

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .client import AiError
from .codex_client import CodexServer
from ..ui.workspace_icons import workspace_icon


class AccountConnection(QWidget):
    connected = Signal()
    changed = Signal()
    disconnectRequested = Signal()
    _completed = Signal(int, str, object, str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.server = None
        self.authenticated = False
        self._models = []
        self._login_id = None
        self._generation = 0
        self._working = False
        self._restore = False
        self._closed = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.status = QLabel("Use your ChatGPT account with Codex.")
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        self.check_account = QPushButton("Check account")
        self.check_account.setIcon(workspace_icon("refresh"))
        self.check_account.clicked.connect(self.discover)
        self.sign_in = QPushButton("Sign in")
        self.sign_in.setIcon(workspace_icon("external"))
        self.sign_in.clicked.connect(self.login)
        self.cancel = QPushButton("Cancel")
        self.cancel.clicked.connect(self.cancel_login)
        self.cancel.hide()
        self.help = QPushButton("Install Codex")
        self.help.setIcon(workspace_icon("external"))
        self.help.setToolTip("Open the Codex setup guide")
        self.help.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://developers.openai.com/codex/cli/")))
        self.help.hide()
        for button in (self.check_account, self.sign_in, self.cancel, self.help):
            row.addWidget(button)
        row.addStretch(1)
        layout.addLayout(row)
        self.model_row = QWidget()
        row = QHBoxLayout(self.model_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Model"))
        self.models = QComboBox()
        self.models.setMinimumContentsLength(8)
        self.models.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.models, 1)
        self.connect_button = QPushButton("Connect")
        self.connect_button.setIcon(workspace_icon("link", color="#a6d4c4"))
        self.connect_button.clicked.connect(self.connect_account)
        row.addWidget(self.connect_button)
        layout.addWidget(self.model_row)
        self.model_row.hide()
        self.disconnect = QPushButton("Disconnect")
        self.disconnect.clicked.connect(self.disconnectRequested.emit)
        self.disconnect.hide()
        self.disconnect.setIcon(workspace_icon("close"))
        layout.addWidget(self.disconnect, 0, Qt.AlignmentFlag.AlignLeft)
        self._completed.connect(self._finish)
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._poll_login)
        self._timer.start()

    @property
    def ready(self):
        model = self.cfg.get("ai", "chatgpt_model", default="")
        return bool(self.authenticated and self.server and self.server.alive
                    and self.cfg.get("ai", "chatgpt_connected", default=False)
                    and any((entry.get("model") or entry.get("id")) == model
                            for entry in self._models))

    def _work(self, operation, fn):
        if self._working or self._closed:
            return
        self._working = True
        self._generation += 1
        generation = self._generation
        self.check_account.setEnabled(False)
        self.sign_in.setEnabled(False)

        def run():
            try:
                result, error = fn(), ""
            except Exception as exc:
                result, error = None, str(exc)
            try:
                self._completed.emit(generation, operation, result, error)
            except RuntimeError:
                # The owning window may have been deleted during the request.
                pass

        threading.Thread(target=run, daemon=True).start()

    def _ensure_server(self):
        if self._closed:
            raise RuntimeError("The ChatGPT connection was closed.")
        if self.server is None or not self.server.alive:
            if self.server is not None:
                self.server.close()
            server = CodexServer()
            self.server = server
            server.start()
            if self._closed:
                server.close()
        return self.server

    def discover(self, *, restore=False):
        if self._working or self._login_id:
            return
        self._restore = restore
        self.status.setText("Checking your ChatGPT account…")

        def read():
            server = self._ensure_server()
            account = server.request("account/read", {"refreshToken": False}).get("account")
            models = []
            if account and account.get("type") == "chatgpt":
                cursor = None
                while True:
                    params = {"limit": 50}
                    if cursor:
                        params["cursor"] = cursor
                    page = server.request("model/list", params)
                    models.extend(model for model in page.get("data", []) if not model.get("hidden"))
                    cursor = page.get("nextCursor")
                    if not cursor:
                        break
            return account, models

        self._work("discover", read)

    def login(self):
        if self._working or self._login_id:
            return
        self.authenticated = False
        self.model_row.hide()
        self.status.setText("Starting browser sign-in…")
        self.changed.emit()
        self._work("login", lambda: self._ensure_server().request("account/login/start", {
            "type": "chatgpt", "useHostedLoginSuccessPage": True, "appBrand": "chatgpt"}))

    def _finish(self, generation, operation, result, error):
        if self._closed or generation != self._generation:
            return
        self._working = False
        self.check_account.setEnabled(True)
        self.sign_in.setEnabled(True)
        if error:
            self.authenticated = False
            self.status.setText(error)
            self.help.setVisible("install" in error.lower() or "not found" in error.lower())
            self.model_row.hide()
            self.changed.emit()
            return
        self.help.hide()
        if operation == "login":
            self._login_id = result["loginId"]
            self.status.setText("Complete sign-in in your browser. Waiting for your account…")
            self.cancel.show()
            self.sign_in.setEnabled(False)
            self.check_account.setEnabled(False)
            QDesktopServices.openUrl(QUrl(result["authUrl"]))
            return
        if operation == "cancel":
            self.status.setText("Sign-in cancelled. You can sign in again.")
            return
        account, models = result
        self.authenticated = bool(account and account.get("type") == "chatgpt")
        self._models = models
        self.models.clear()
        for model in models:
            model_id = model.get("model") or model["id"]
            self.models.addItem(model.get("displayName") or model_id, model_id)
        saved = self.cfg.get("ai", "chatgpt_model", default="")
        index = self.models.findData(saved)
        self.models.setCurrentIndex(max(0, index))
        self.model_row.setVisible(bool(models))
        self.connect_button.setEnabled(bool(models))
        if self.authenticated:
            self.status.setText("ChatGPT account ready. Choose a model, then Connect." if models
                                else "No ChatGPT models are available. Check your account and retry.")
        else:
            self.status.setText("Sign in to use your ChatGPT account.")
        if self._restore and index >= 0 and self.authenticated:
            self.connected.emit()
        elif self._restore and self.authenticated and models:
            self.status.setText("Your previous model is unavailable. Choose a model, then Connect.")
        self._restore = False
        self.disconnect.setVisible(self.ready)
        self.changed.emit()

    def _poll_login(self):
        if self.server is None:
            return
        if (self.authenticated or self._login_id) and not self.server.alive:
            self.authenticated = False
            self._clear_login()
            self.status.setText("Codex disconnected. Check your account to reconnect.")
            self.model_row.hide()
            self.changed.emit()
        while True:
            try:
                event = self.server.account_events.get_nowait()
            except queue.Empty:
                return
            params = event.get("params", {})
            if (event.get("method") != "account/login/completed" or not self._login_id
                    or params.get("loginId") != self._login_id):
                continue
            self._clear_login()
            if params.get("success"):
                self.discover()
            else:
                self.status.setText(params.get("error") or "Sign-in failed. Please try again.")
                self.changed.emit()

    def _clear_login(self):
        login_id, self._login_id = self._login_id, None
        self.cancel.hide()
        self.sign_in.setEnabled(not self._working and not self._closed)
        self.check_account.setEnabled(not self._working and not self._closed)
        return login_id

    def cancel_login(self):
        login_id = self._clear_login()
        self.status.setText("Sign-in cancelled. You can sign in again.")
        server = self.server
        if login_id and server and server.alive:
            self._work("cancel", lambda: server.request("account/login/cancel", {"loginId": login_id}))

    def connect_account(self):
        if not self.authenticated or not self.models.currentData():
            return
        self.cfg.set("ai", "provider", "chatgpt")
        self.cfg.set("ai", "chatgpt_connected", True)
        self.cfg.set("ai", "chatgpt_model", self.models.currentData())
        self.cfg.set("ai", "chatgpt_models", [{
            "id": model.get("model") or model["id"],
            "label": model.get("displayName") or model["id"],
            "vision": "image" in model.get("inputModalities", []),
        } for model in self._models])
        self.cfg.save()
        self.disconnect.show()
        self.connected.emit()

    def disconnect_account(self):
        self.cfg.set("ai", "chatgpt_connected", False)
        self.cfg.save()
        self.close_connection()
        self._closed = False
        self._timer.start()
        self.status.setText("Disconnected. Your ChatGPT account remains signed in to Codex.")
        self.sign_in.setEnabled(True)
        self.check_account.setEnabled(True)
        self.disconnect.hide()
        self.model_row.hide()
        self.changed.emit()

    def close_connection(self):
        self._closed = True
        self._generation += 1
        self._working = False
        self._timer.stop()
        self.authenticated = False
        login_id = self._clear_login()
        if self.server:
            try:
                if login_id and self.server.alive:
                    self.server.request("account/login/cancel", {"loginId": login_id}, wait=False)
            except AiError:
                # The subprocess may exit after the liveness check.
                pass
            finally:
                self.server.close()
