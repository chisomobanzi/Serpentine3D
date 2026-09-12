"""The connection helper gives an external assistant a runnable MCP config.

Use actual Assistant controls and a real stdio handshake. The child forbids
GUI imports so a missing launcher flag fails promptly without opening a window.
"""

import json
import os
from pathlib import Path
import re
import queue
import subprocess
import sys
import time
import threading

import pytest
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QLabel, QPlainTextEdit, QTextEdit, QWidget,
)

from serpentine3d.app import MainWindow


@pytest.fixture
def assistant(monkeypatch, tmp_path):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RPC", "1")
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    opened = []

    def create():
        window = MainWindow()
        opened.append(window)
        window.resize(1400, 900)
        panel = window.show_ai_panel()
        shelf = window._cmd_dock.widget()
        shelf.resize(1100, 360)
        for _ in range(2):
            for widget in [shelf, *shelf.findChildren(QWidget)]:
                if widget.layout() is not None:
                    widget.layout().activate()
        QApplication.processEvents()
        return panel

    yield create
    for window in opened:
        window.processor.cancel()
        window.mark_saved()
        window.close()


def _button(root, pattern):
    found = [button for button in root.findChildren(QAbstractButton)
             if button.isVisibleTo(root) and button.isEnabled()
             and re.search(pattern, " ".join((button.text(),
                           button.accessibleName(), button.toolTip())), re.I)]
    assert len(found) == 1, f"Expected one visible {pattern!r} action; found {len(found)}"
    return found[0]


def _copy_connection(panel):
    _button(panel, r"external assistant|\bMCP\b").click()
    QApplication.processEvents()
    guidance = "\n".join(
        widget.text() if isinstance(widget, QLabel) else widget.toPlainText()
        for widget in panel.findChildren(QWidget)
        if isinstance(widget, (QLabel, QPlainTextEdit, QTextEdit))
        and widget.isVisibleTo(panel))
    assert re.search(r"keep.{0,50}(running|open)", guidance, re.I | re.S), \
        "MCP setup must explain that Serpentine3D stays running for scene access"
    assert re.search(r"Claude|Codex|external assistant", guidance, re.I), \
        "MCP setup must explain where the copied configuration is used"
    QApplication.clipboard().setText("not copied yet")
    _button(panel, r"copy.*(config|MCP)|copy configuration").click()
    QApplication.processEvents()
    config = json.loads(QApplication.clipboard().text())
    assert isinstance(config.get("mcpServers"), dict), \
        "Copy must produce a ready-to-use mcpServers JSON object"
    assert len(config["mcpServers"]) == 1
    server = next(iter(config["mcpServers"].values()))
    assert isinstance(server.get("command"), str) and server["command"]
    assert isinstance(server.get("args"), list)
    return server


@pytest.mark.parametrize("appimage", [True, False], ids=["appimage", "frozen"])
def test_the_mcp_helper_copies_the_durable_installed_executable(
        assistant, monkeypatch, tmp_path, appimage):
    installed = str(tmp_path / "My Applications" / "Serpentine3D.AppImage")
    executable = "/tmp/.mount_Serpentine123/usr/bin/python3" if appimage else str(
        tmp_path / "My Applications" / "Serpentine3D")
    monkeypatch.setattr(sys, "executable", executable)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    if appimage:
        monkeypatch.setenv("APPIMAGE", installed)
    else:
        monkeypatch.delenv("APPIMAGE", raising=False)

    server = _copy_connection(assistant())
    assert server["command"] == (installed if appimage else executable), \
        "External clients must launch the durable app, never AppImage's temporary mount"
    assert server["args"] == ["--mcp"]
    assert "/tmp/.mount_" not in json.dumps(server)


@pytest.fixture
def headless_environment(tmp_path):
    guard = tmp_path / "headless_guard"
    guard.mkdir()
    (guard / "sitecustomize.py").write_text(
        "import importlib.abc, sys\n"
        "class NoGUI(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname.split('.')[0] in ('PySide6', 'OCP') or fullname == 'serpentine3d.app':\n"
        "            raise RuntimeError('MCP must start without GUI imports: ' + fullname)\n"
        "sys.meta_path.insert(0, NoGUI())\n", encoding="utf-8")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(guard) + os.pathsep + environment.get("PYTHONPATH", "")
    environment.pop("DISPLAY", None)
    environment.pop("WAYLAND_DISPLAY", None)
    return environment


def _assert_real_mcp(server, environment, cwd):
    environment = {**environment, **server.get("env", {})}
    process = subprocess.Popen([server["command"], *server["args"]],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, bufsize=0,
                               env=environment, cwd=cwd)
    replies = queue.Queue()

    def read_replies():
        for line in iter(process.stdout.readline, b""):
            replies.put(line)
        replies.put(b"")

    reader = threading.Thread(target=read_replies, daemon=True)
    reader.start()

    def send(message):
        process.stdin.write((json.dumps({"jsonrpc": "2.0", **message}) + "\n").encode())
        process.stdin.flush()

    def response(request_id):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                line = replies.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty:
                pytest.fail("MCP process did not answer over stdio within 15 seconds")
            if not line:
                process.wait(timeout=5)
                pytest.fail("MCP process exited before replying: " + process.stderr.read().decode())
            message = json.loads(line)
            assert message.get("jsonrpc") == "2.0", "MCP stdout must contain only JSON-RPC"
            if message.get("id") == request_id:
                assert "error" not in message, message
                return message["result"]
        pytest.fail("MCP did not answer the requested message")

    try:
        send({"id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18", "capabilities": {},
            "clientInfo": {"name": "Serpentine MCP setup test", "version": "1"}}})
        initialized = response(1)
        assert "serpentine" in initialized["serverInfo"]["name"].lower()
        assert "tools" in initialized["capabilities"]
        send({"method": "notifications/initialized"})
        send({"id": 2, "method": "tools/list", "params": {}})
        tools = {tool["name"]: tool for tool in response(2)["tools"]}
        assert {"serp_scene_info", "serp_create_curve", "serp_create_surface",
                "serp_prepare_script"} <= tools.keys()
        assert "source" in tools["serp_prepare_script"]["inputSchema"]["required"]
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        reader.join(timeout=5)
        assert not reader.is_alive()
        while not replies.empty():
            line = replies.get_nowait()
            if line:
                assert json.loads(line).get("jsonrpc") == "2.0"
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def test_the_source_installation_config_runs_from_an_external_clients_directory(
        assistant, monkeypatch, tmp_path, headless_environment):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    server = _copy_connection(assistant())
    _assert_real_mcp(server, headless_environment, tmp_path)


def test_the_application_mcp_flag_serves_tools_without_gui_startup(
        headless_environment, tmp_path):
    _assert_real_mcp({"command": sys.executable,
                      "args": ["-c", "from serpentine3d.launcher import main; main()", "--mcp"]},
                     headless_environment, Path(__file__).resolve().parents[1])
