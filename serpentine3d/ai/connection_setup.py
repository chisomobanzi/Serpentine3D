"""Inline connection choices; discovery is a preview until explicit Connect."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QToolButton, QVBoxLayout, QWidget,
)

from .client import DEFAULT_MODEL, MODELS, resolve_api_key
from .local_client import DEFAULT_ENDPOINT, server_root
from .openai_client import DEFAULT_MODEL as OPENAI_DEFAULT_MODEL, MODELS as OPENAI_MODELS
from .model_discovery import ModelDiscovery
from ..ui.workspace_icons import workspace_icon
from .account_connection import AccountConnection
from ..ui.connection_choice import ConnectionChoice


class ConnectionSetup(QWidget):
    connected = Signal()
    changed = Signal()
    disconnectRequested = Signal()

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._models = []
        self._discovered_endpoint = None
        self._discovering = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(6)

        self.intro = QLabel(
            "Connect an account, a local model, or an API key.")
        self.intro.setWordWrap(True)
        layout.addWidget(self.intro)
        self.external_assistant = QToolButton()
        self.external_assistant.setText("External assistant · MCP")
        self.external_assistant.setIcon(workspace_icon("external"))
        self.external_assistant.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.external_assistant.setAutoRaise(True)
        self.external_assistant.setToolTip("Connect Claude Desktop, Codex, or another MCP client")
        self.external_assistant.clicked.connect(self._show_mcp_connection)
        self._mcp_dialog = None
        choices = QHBoxLayout()
        self.account_choice = ConnectionChoice("ChatGPT", "Use your account", "account")
        self.local_choice = ConnectionChoice("Local model", "LM Studio", "local")
        self.cloud_choice = ConnectionChoice("API key", "OpenAI · Claude", "key")
        for button in (self.account_choice, self.local_choice, self.cloud_choice):
            button.setCheckable(True)
            choices.addWidget(button)
        choices.addStretch(1)
        layout.addLayout(choices)

        self.account_form = AccountConnection(cfg, self)
        self.account_form.connected.connect(self.connected.emit)
        self.account_form.changed.connect(self.changed.emit)
        self.account_form.disconnectRequested.connect(self.disconnectRequested.emit)
        self.account_form.hide()
        layout.addWidget(self.account_form)

        self.local_form = QWidget()
        local = QVBoxLayout(self.local_form)
        local.setContentsMargins(0, 0, 0, 0)
        local.setSpacing(4)
        row = QHBoxLayout()
        row.addWidget(QLabel("Server URL"))
        self.endpoint = QLineEdit(str(cfg.get(
            "ai", "local_endpoint", default=DEFAULT_ENDPOINT) or DEFAULT_ENDPOINT))
        self.endpoint.setPlaceholderText(DEFAULT_ENDPOINT)
        self.endpoint.setAccessibleName("LM Studio server URL")
        row.addWidget(self.endpoint, 1)
        self.refresh = QPushButton("Discover")
        self.refresh.setIcon(workspace_icon("refresh"))
        self.refresh.clicked.connect(self._discover)
        row.addWidget(self.refresh)
        local.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Model"))
        self.models = self._model_combo()
        self.models.addItem("Discover models to choose one", None)
        row.addWidget(self.models, 1)
        self.connect_local = QPushButton("Connect")
        self.connect_local.setIcon(workspace_icon("link", color="#a6d4c4"))
        self.connect_local.setEnabled(False)
        self.connect_local.clicked.connect(self._connect_local)
        row.addWidget(self.connect_local)
        local.addLayout(row)
        local.addWidget(self._note(
            "Start LM Studio’s local server, then discover models. "
            "Local models need no cloud API key."))
        self.status = self._note("")
        self.status.hide()
        local.addWidget(self.status)
        layout.addWidget(self.local_form)

        self.cloud_form = QWidget()
        cloud = QVBoxLayout(self.cloud_form)
        cloud.setContentsMargins(0, 0, 0, 0)
        cloud.setSpacing(4)
        row = QHBoxLayout()
        self.cloud_provider = self._model_combo()
        self.cloud_provider.setFixedWidth(112)
        self.cloud_provider.setAccessibleName("API provider")
        self.cloud_provider.addItem("OpenAI", "openai")
        self.cloud_provider.addItem("Anthropic", "anthropic")
        self.cloud_provider.setCurrentIndex(max(0, self.cloud_provider.findData(
            cfg.get("ai", "provider", default="anthropic"))))
        row.addWidget(self.cloud_provider)
        row.addWidget(QLabel("Model"))
        self.cloud_model = self._model_combo()
        row.addWidget(self.cloud_model, 1)
        cloud.addLayout(row)
        row = QHBoxLayout()
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        row.addWidget(self.key_edit, 1)
        self.connect_cloud = QPushButton("Connect")
        self.connect_cloud.setIcon(workspace_icon("link", color="#a6d4c4"))
        self.connect_cloud.setEnabled(False)
        self.connect_cloud.clicked.connect(self.save_key)
        self.key_edit.textChanged.connect(self._update_cloud_connect)
        self.cloud_model.currentTextChanged.connect(self._update_cloud_connect)
        row.addWidget(self.connect_cloud)
        cloud.addLayout(row)
        self.cloud_note = self._note("")
        cloud.addWidget(self.cloud_note)
        self.cloud_provider.currentIndexChanged.connect(self._cloud_provider_changed)
        self._cloud_provider_changed()
        layout.addWidget(self.cloud_form)
        layout.addWidget(self.external_assistant, alignment=Qt.AlignmentFlag.AlignLeft)

        self.local_form.hide()
        self.cloud_form.hide()
        self.local_choice.clicked.connect(lambda: self.choose("lmstudio"))
        self.cloud_choice.clicked.connect(lambda: self.choose(self.cloud_provider.currentData()))
        self.account_choice.clicked.connect(lambda: self.choose("chatgpt"))
        self.endpoint.textChanged.connect(self._endpoint_changed)
        self.models.currentIndexChanged.connect(self._update_connect)
        self._discovery = ModelDiscovery(self)
        self._discovery.finished.connect(self._models_discovered)

    def _show_mcp_connection(self):
        from ..ui.mcp_connection import MCPConnectionDialog
        if self._mcp_dialog is None:
            self._mcp_dialog = MCPConnectionDialog(self)
        self._mcp_dialog.show()
        self._mcp_dialog.raise_()
        self._mcp_dialog.activateWindow()

    @staticmethod
    def _model_combo():
        combo = QComboBox()
        combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(8)
        combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        return combo

    @staticmethod
    def _note(text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: #85868a; font-size: 11px;")
        return label

    def choose(self, provider):
        local = provider == "lmstudio"
        account = provider == "chatgpt"
        cloud = provider in ("anthropic", "openai")
        self.account_choice.setChecked(account)
        self.local_choice.setChecked(local)
        self.cloud_choice.setChecked(cloud)
        self.local_form.setVisible(local)
        self.cloud_form.setVisible(cloud)
        if cloud:
            self.cloud_provider.setCurrentIndex(self.cloud_provider.findData(provider))
            self._cloud_provider_changed()
        self.account_form.setVisible(account)
        if account and not self.account_form.authenticated:
            self.account_form.discover()

    def _set_status(self, text, *, error=False):
        self.status.setText(text)
        self.status.setStyleSheet(
            "color: #d9705f; font-size: 11px;" if error
            else "color: #85868a; font-size: 11px;")
        self.status.setVisible(bool(text))

    def _endpoint_changed(self):
        self._models = []
        self._discovered_endpoint = None
        self.models.clear()
        self.models.addItem("Discover models to choose one", None)
        self._set_status("Server URL changed. Discover models from this server.")
        self._update_connect()

    def _update_connect(self):
        self.connect_local.setEnabled(
            not self._discovering and bool(self.models.currentData())
            and self._discovered_endpoint == self.endpoint.text().strip())

    def _discover(self):
        self._discovering = True
        self.refresh.setEnabled(False)
        self._models = []
        self._discovered_endpoint = None
        self.models.clear()
        self.models.addItem("Discovering models…", None)
        self._update_connect()
        self._set_status("Discovering models…")
        self._discovery.start(self.endpoint.text().strip())

    def _models_discovered(self, endpoint, models, error):
        self._discovering = False
        self.refresh.setEnabled(True)
        if endpoint != self.endpoint.text().strip():
            self._set_status("Server URL changed. Discover models again.")
            return
        self.models.clear()
        if error:
            self.models.addItem("No models discovered", None)
            self.refresh.setText("Retry")
            self._set_status(
                f"Discovery failed: {error} Retry when ready.", error=True)
            return
        self._models = models
        self._discovered_endpoint = endpoint
        self.refresh.setText("Refresh")
        for model in models:
            model_id = model["id"]
            label = model.get("label", model_id)
            self.models.addItem(label, model_id)
            features = "Vision" if model.get("vision") else "Text only"
            if model.get("tool_use") is False:
                features += " · not trained for tool use"
            elif model.get("tool_use"):
                features += " · tool use"
            self.models.setItemData(self.models.count() - 1,
                                    f"{model_id} · {features}", Qt.ItemDataRole.ToolTipRole)
        if not models:
            self.models.addItem("No language models found", None)
            self._set_status("Download a language model in LM Studio, then refresh.")
        else:
            self._set_status("Choose a model, then Connect. Your prompt stays a draft until you send it.")
        self._update_connect()

    def _connect_local(self):
        if not self.connect_local.isEnabled():
            return
        endpoint = server_root(self._discovered_endpoint)
        self.cfg.set("ai", "provider", "lmstudio")
        self.cfg.set("ai", "local_endpoint", endpoint)
        self.cfg.set("ai", "local_model", self.models.currentData())
        self.cfg.set("ai", "local_models", self._models)
        self.cfg.save()
        self.connected.emit()

    def save_key(self):
        provider = self.cloud_provider.currentData()
        key = self.key_edit.text().strip()
        model = self._cloud_model_id()
        if not model or not (key or resolve_api_key(self.cfg, provider)):
            return
        self.cfg.set("ai", "provider", provider)
        self.cfg.set("ai", "openai_model" if provider == "openai" else "model", model)
        if key:
            self.cfg.set("ai", "openai_api_key" if provider == "openai" else "api_key", key)
        self.cfg.save()
        self.key_edit.clear()
        self.connected.emit()

    def _cloud_model_id(self):
        return (self.cloud_model.currentText().strip() if self.cloud_model.isEditable()
                else self.cloud_model.currentData())

    def _update_cloud_connect(self):
        self.connect_cloud.setEnabled(bool(self._cloud_model_id()) and bool(
            self.key_edit.text().strip() or resolve_api_key(self.cfg, self.cloud_provider.currentData())))

    def _cloud_provider_changed(self):
        openai = self.cloud_provider.currentData() == "openai"
        label = "OpenAI" if openai else "Anthropic"
        self.cloud_model.clear()
        self.cloud_model.setEditable(openai)
        self.cloud_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        for model_id, model_label in OPENAI_MODELS if openai else MODELS:
            self.cloud_model.addItem(model_label, model_id)
        current = self.cfg.get("ai", "openai_model" if openai else "model",
                               default=OPENAI_DEFAULT_MODEL if openai else DEFAULT_MODEL)
        if current and self.cloud_model.findData(current) < 0:
            self.cloud_model.addItem(current, current)
        self.cloud_model.setCurrentIndex(max(0, self.cloud_model.findData(current)))
        self.key_edit.setAccessibleName(f"{label} API key")
        self.key_edit.setPlaceholderText(f"{label} API key · " + ("sk-…" if openai else "sk-ant-…"))
        self.key_edit.setText(str(self.cfg.get(
            "ai", "openai_api_key" if openai else "api_key", default="") or ""))
        site = "platform.openai.com/api-keys" if openai else "console.anthropic.com"
        self.cloud_note.setText(f"Get a key at {site}.\nAPI usage is billed separately from subscriptions.")
        details = (f"Your {label} key is stored in Serpentine3D’s config. "
                   f"{'OPENAI' if openai else 'ANTHROPIC'}_API_KEY takes precedence and is never saved.")
        self.key_edit.setToolTip(details)
        self.cloud_note.setToolTip(details)
        self._update_cloud_connect()
