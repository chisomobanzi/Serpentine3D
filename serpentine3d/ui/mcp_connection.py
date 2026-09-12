"""Copyable setup for assistants that control the running scene over MCP."""

import json
import os
import sys

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from .workspace_icons import workspace_icon


def mcp_configuration():
    """Launch the durable app bundle or this Python installation from any cwd."""
    appimage = os.environ.get("APPIMAGE")
    if appimage or getattr(sys, "frozen", False):
        server = {"command": appimage or sys.executable, "args": ["--mcp"]}
    else:
        server = {"command": sys.executable, "args": ["-m", "serpentine3d", "--mcp"]}
    return json.dumps({"mcpServers": {"serpentine3d": server}}, indent=2)


class MCPConnectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("External assistant · MCP")
        self.resize(560, 340)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        instructions = QLabel(
            "Keep Serpentine3D running with your scene open. In Claude Desktop "
            "or another external assistant, add this server to its MCP configuration, "
            "then reconnect the client. Codex and other clients may ask for the "
            "command and arguments separately.")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)
        self.configuration = QPlainTextEdit(mcp_configuration())
        self.configuration.setReadOnly(True)
        self.configuration.setAccessibleName("MCP server configuration")
        self.configuration.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        layout.addWidget(self.configuration, 1)
        self.feedback = QLabel("The external assistant can read and edit the open scene.")
        self.feedback.setWordWrap(True)
        layout.addWidget(self.feedback)
        buttons = QHBoxLayout()
        self.copy = QPushButton("Copy configuration")
        self.copy.setIcon(workspace_icon("copy"))
        self.copy.clicked.connect(self._copy_configuration)
        buttons.addWidget(self.copy)
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        layout.addLayout(buttons)

    def _copy_configuration(self):
        QApplication.clipboard().setText(self.configuration.toPlainText())
        self.feedback.setText("Copied. Add this configuration in your external assistant.")
