"""A new user connects a local model in the Assistant, then models with it.

The application, its Qt controls, configuration, agent, scene tools, and command
history are real. Only HTTP is replaced by LM Studio's documented wire format.
Controls are found by their visible purpose, not proposed implementation names.
"""

from __future__ import annotations

import json
import re
import threading
import time

import httpx
import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QComboBox, QLabel, QLineEdit, QWidget,
)

from serpentine3d.app import MainWindow
from serpentine3d.ui.settings_dialog import SettingsDialog


ENDPOINT = "http://127.0.0.1:19473"
MODELS = {"qwen/qwen3.5-9b": "Qwen", "google/gemma-3-4b": "Gemma"}


def _stream(delta, finish):
    chunks = [{"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
              {"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}]
    return ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            + "data: [DONE]\n\n").encode()


class LocalServer:
    def __init__(self):
        self.requests = []
        self.posts = []
        self.fail_discovery = False
        self.discovery_started = threading.Event()
        self.discovery_gate = None
        self.discovery_saw_heartbeat = []

    def handle(self, request):
        self.requests.append((request, threading.get_ident()))
        # Every client is intercepted, so a mistaken cloud route never leaves
        # the test process and remains visible in the request assertions.
        if request.url.host != "127.0.0.1" or request.url.port != 19473:
            return httpx.Response(403, text="Unexpected destination in local onboarding")
        if request.method == "GET" and request.url.path == "/api/v1/models":
            self.discovery_started.set()
            if self.discovery_gate is not None:
                self.discovery_saw_heartbeat.append(self.discovery_gate.wait(.5))
            if self.fail_discovery:
                return httpx.Response(503, text="LM Studio server is not ready")
            return httpx.Response(200, json={"models": [
                {"type": "llm", "key": model, "display_name": name,
                 "capabilities": {"vision": False, "trained_for_tool_use": True}}
                for model, name in MODELS.items()
            ] + [{"type": "embedding", "key": "embed-only"}]})
        if request.method == "POST" and request.url.path == "/v1/chat/completions":
            body = json.loads(request.content)
            self.posts.append(body)
            if any(message["role"] == "tool" for message in body["messages"]):
                reply = _stream({"content": "Created your 4 by 5 by 6 box."}, "stop")
            else:
                reply = _stream({"tool_calls": [{
                    "index": 0, "id": "first-box", "type": "function",
                    "function": {"name": "run_command", "arguments": json.dumps({
                        "command": "box", "inputs": ["0,0,0", "4,5,0", "6"],
                    })},
                }]}, "tool_calls")
            return httpx.Response(200, content=reply,
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(404, text="Unknown local fixture route")


@pytest.fixture
def local(monkeypatch):
    server = LocalServer()
    original_init = httpx.Client.__init__

    def init(client, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(server.handle)
        original_init(client, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", init)
    return server


@pytest.fixture
def windows(monkeypatch, tmp_path, local):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RPC", "1")
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY",
                 "GOOGLE_API_KEY", "OPENROUTER_API_KEY", "AZURE_OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    opened = []

    def create():
        window = MainWindow()
        opened.append(window)
        window.resize(1400, 900)
        _lay_out(window)
        return window

    yield create
    if local.discovery_gate is not None:
        local.discovery_gate.set()
    for window in opened:
        panel = window.command_workspace.assistant
        if panel is not None and panel.agent is not None and panel.agent.busy:
            panel.agent.stop()
            _wait(lambda: not panel.agent.busy, "Assistant did not stop at teardown")
        for dialog in window.findChildren(SettingsDialog):
            dialog.close()
        window.processor.cancel()
        window.mark_saved()
        window.close()


def _wait(predicate, message, seconds=6):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(5)
    QApplication.processEvents()
    assert predicate(), message


def _lay_out(window):
    """Use the existing workspace tests' layout, without an offscreen GL view."""
    window.layout().activate()
    shelf = window._cmd_dock.widget()
    shelf.resize(1100, 360)
    for _ in range(2):
        for widget in [shelf, *shelf.findChildren(QWidget)]:
            if widget.layout() is not None:
                widget.layout().invalidate()
                widget.layout().activate()
    QApplication.processEvents()


def _description(widget):
    return " ".join((widget.text(), widget.accessibleName(), widget.toolTip()))


def _button(root, pattern):
    matches = [button for button in root.findChildren(QAbstractButton)
               if button.isVisibleTo(root) and re.search(pattern, _description(button), re.I)]
    exact = [button for button in matches if re.fullmatch(pattern, button.text().strip(), re.I)]
    matches = exact or matches
    assert len(matches) == 1, f"Expected one visible {pattern!r} action; found {len(matches)}"
    return matches[0]


def _mode(window, label):
    shelf = window._cmd_dock.widget()
    matches = [button for button in shelf.findChildren(QAbstractButton)
               if button.isVisibleTo(shelf) and button.text().replace("&", "") == label]
    assert len(matches) == 1, f"The workspace needs its explicit {label!r} input choice"
    return matches[0]


def _visible_text(root):
    return "\n".join(label.text() for label in root.findChildren(QLabel)
                     if label.isVisibleTo(root))


def _connection_choices(panel, pattern):
    choices = [(button, None) for button in panel.findChildren(QAbstractButton)
               if button.isVisibleTo(panel) and button.isEnabled()
               and re.search(pattern, _description(button), re.I)]
    for combo in panel.findChildren(QComboBox):
        if combo.isVisibleTo(panel) and combo.isEnabled():
            choices.extend((combo, index) for index in range(combo.count())
                           if re.search(pattern, combo.itemText(index), re.I))
    return choices


def _choose_local(window, panel):
    choices = _connection_choices(panel, r"LM\s*Studio")
    if not choices:
        choices = _connection_choices(panel, r"\blocal\b")
    assert choices, "The Assistant pane needs an actionable local-model connection choice"
    control, index = choices[0]
    control.click() if index is None else control.setCurrentIndex(index)
    _lay_out(window)
    # A local-provider category may reveal a provider selector as its next step.
    for combo in panel.findChildren(QComboBox):
        if combo.isVisibleTo(panel):
            for index in range(combo.count()):
                if re.search(r"LM\s*Studio", combo.itemText(index), re.I):
                    combo.setCurrentIndex(index)
                    _lay_out(window)
                    break
    assert not any(dialog.isVisible() for dialog in window.findChildren(SettingsDialog)), \
        "First local connection must happen in the Assistant pane, without general Settings"


def _endpoint(panel):
    fields = [field for field in panel.findChildren(QLineEdit)
              if field.isVisibleTo(panel) and not field.isReadOnly()
              and (field.text().startswith("http") or re.search(
                  r"server|endpoint|base url|localhost|127\.0\.0\.1",
                  " ".join((field.accessibleName(), field.placeholderText(), field.toolTip())),
                  re.I))]
    assert len(fields) == 1, "The Assistant needs one visible editable local server URL"
    return fields[0]


def _discover(panel):
    button = _button(panel, r"refresh|discover|load models|retry")
    assert button.isEnabled(), "Model discovery/retry must be actionable"
    button.click()


def _model_selector(panel):
    for combo in panel.findChildren(QComboBox):
        if combo.isVisibleTo(panel) and any(
                combo.itemData(index) in MODELS or combo.itemText(index) in MODELS.values()
                for index in range(combo.count())):
            return combo
    return None


def _assert_unconnected(window, panel, local):
    recipient = panel.recipient.text().lower()
    assert "anthropic" not in recipient and "claude" not in recipient, \
        f"An unconfigured Assistant must not claim a cloud recipient: {recipient!r}"
    assert not re.search(r"(?<!not )(?<!dis)\bconnected\b|\bready\b", recipient), \
        f"Incomplete connection must not claim chat readiness: {recipient!r}"
    assert not local.posts and not window.scene.all(), "Setup must not send a prompt or model anything"
    _mode(window, "Ask AI").click()
    _lay_out(window)
    send = window.command_workspace.submit_button
    assert not send.isEnabled() or re.search(r"connect|set.?up", send.text(), re.I), \
        "The AI composer must indicate setup is required before it offers an enabled Send"


def _connect(window, panel, local, model):
    _choose_local(window, panel)
    endpoint = _endpoint(panel)
    assert endpoint.text().startswith("http"), "Offer a useful default LM Studio server URL"
    endpoint.setText(ENDPOINT)
    endpoint.editingFinished.emit()
    _discover(panel)
    _wait(lambda: _model_selector(panel) is not None,
          "Models discovered from this server must become selectable in the Assistant")
    models = _model_selector(panel)
    offered = repr([(models.itemText(i), models.itemData(i)) for i in range(models.count())])
    assert all(model_id in offered or name in offered for model_id, name in MODELS.items())
    assert "embed-only" not in offered
    for index in range(models.count()):
        if models.itemData(index) == model or models.itemText(index) == MODELS[model]:
            models.setCurrentIndex(index)
            break
    _assert_unconnected(window, panel, local)
    button = _button(panel, r"\bconnect\b")
    assert button.isEnabled(), "A selected discovered model must offer an explicit Connect action"
    button.click()
    _lay_out(window)
    _wait(lambda: "lm studio" in panel.recipient.text().lower()
          and MODELS[model].lower() in panel.recipient.text().lower(),
          "Successful connection must identify the configured local recipient")
    assert not any(dialog.isVisible() for dialog in window.findChildren(SettingsDialog))
    assert not local.posts, "Connecting a model does not authorize sending a prompt"


def test_first_open_explains_connection_choices_without_claiming_anthropic(windows, local):
    window = windows()
    window.command_line.input.setText("circle")
    panel = window.show_ai_panel()
    _lay_out(window)
    assert _mode(window, "Command").isChecked(), "Opening Assistant preserves the CAD destination"
    assert window.command_line.input.text() == "circle"
    recipient = panel.recipient.text().lower()
    assert "anthropic" not in recipient and "claude" not in recipient, \
        "First use must say connection is needed instead of displaying a default Anthropic/model recipient"
    assert _connection_choices(panel, r"\blocal\b|LM\s*Studio"), \
        "First use needs a visible local-model connection action in the main Assistant pane"
    assert _connection_choices(panel, r"cloud|account|api key|sign in"), \
        "First use needs a visible cloud-account/API-key connection action"
    guidance = _visible_text(panel).lower()
    assert "local" in guidance and "api key" in guidance, \
        "Brief first-use guidance must explain local models and cloud API keys"
    assert re.search(r"account|sign.?in|log.?in", guidance), \
        "First-use guidance must explain the cloud-account connection option"
    _assert_unconnected(window, panel, local)
    panel.input.setPlainText("make a box")
    QTest.keyClick(panel.input, Qt.Key.Key_Return)
    QTest.qWait(25)
    assert not local.requests, "Incomplete first use must not contact an implicit cloud provider"
    assert not window.processor.busy and not window.scene.all()
    _mode(window, "Command").click()
    assert window.command_line.input.text() == "circle"


@pytest.mark.parametrize("model", list(MODELS), ids=list(MODELS.values()))
def test_inline_local_connection_persists_and_the_first_approved_prompt_models(
        windows, local, model):
    window = windows()
    panel = window.show_ai_panel()
    _lay_out(window)
    local.discovery_gate = threading.Event()
    heartbeat = QTimer()
    heartbeat.setInterval(5)
    heartbeat.timeout.connect(lambda: local.discovery_gate.set()
                              if local.discovery_started.is_set() else None)
    heartbeat.start()
    _connect(window, panel, local, model)
    heartbeat.stop()
    assert local.discovery_saw_heartbeat == [True], "Model discovery must keep Qt responsive"
    discoveries = [(request, worker) for request, worker in local.requests
                   if request.method == "GET"]
    assert discoveries and all(worker != threading.get_ident() for _, worker in discoveries)

    reopened = windows()
    assert reopened.cfg.get("ai", "provider") == "lmstudio"
    assert reopened.cfg.get("ai", "local_endpoint").rstrip("/") == ENDPOINT
    assert reopened.cfg.get("ai", "local_model") == model
    panel = reopened.show_ai_panel()
    _lay_out(reopened)
    assert "lm studio" in panel.recipient.text().lower()
    assert MODELS[model].lower() in panel.recipient.text().lower()

    # A starter may prepare a prompt, but using one is never consent to send.
    starters = [button for button in panel.findChildren(QAbstractButton)
                if button.isVisibleTo(panel) and re.search(
                    r"starter|suggestion|example|\b(make|create|explain|inspect|summarize)\b",
                    _description(button), re.I)]
    if starters:
        starters[0].click()
        _lay_out(reopened)
        assert panel.input.toPlainText().strip(), "A starter must leave an editable prompt draft"
        assert not local.posts and not reopened.scene.all(), "A starter must not silently send"

    reopened.command_line.input.setText("circle")
    _mode(reopened, "Ask AI").click()
    _lay_out(reopened)
    assert panel.input.isVisibleTo(reopened.command_workspace) and panel.input.isEnabled()
    panel.input.setPlainText("Make a 4 by 5 by 6 box")
    _mode(reopened, "Command").click()
    assert reopened.command_line.input.text() == "circle"
    _mode(reopened, "Ask AI").click()
    assert panel.input.toPlainText() == "Make a 4 by 5 by 6 box"
    send = reopened.command_workspace.submit_button
    assert send.isEnabled() and re.search(r"send", send.text(), re.I), \
        "Once connected, the user needs an obvious enabled action to send the prompt"
    send.click()
    _wait(lambda: panel.agent is not None and not panel.agent.busy and len(local.posts) >= 2,
          "The approved first local prompt must finish its real scene tool round trip")

    assert len(reopened.scene.all()) == 1 and reopened.scene.all()[0].kind == "solid"
    from serpentine3d.core import geometry
    low, high = geometry.bbox(reopened.scene.all()[0].shape)
    assert tuple(high[i] - low[i] for i in range(3)) == pytest.approx((4, 5, 6))
    assert len(local.posts) == 2 and all(body["model"] == model for body in local.posts)
    assert any(message.get("role") == "tool" and message.get("tool_call_id") == "first-box"
               for message in local.posts[1]["messages"])
    assert "Created your 4 by 5 by 6 box." in _visible_text(panel)
    history = reopened.command_line.echo_view.toPlainText()
    assert any(re.search(r"\b(ai|assistant)\b", line, re.I) and "box" in line.lower()
               for line in history.splitlines()), "The AI scene operation must appear in command history"
    assert "Unknown command" not in history and not reopened.processor.busy
    assert all(str(request.url).startswith(ENDPOINT) for request, _ in local.requests)
    assert all(worker != threading.get_ident() for _, worker in local.requests)


def test_failed_inline_discovery_stays_unconnected_and_can_be_retried(windows, local):
    window = windows()
    panel = window.show_ai_panel()
    _lay_out(window)
    _choose_local(window, panel)
    endpoint = _endpoint(panel)
    endpoint.setText(ENDPOINT)
    endpoint.editingFinished.emit()
    local.fail_discovery = True
    _discover(panel)
    _wait(lambda: re.search(r"unavailable|not ready|could not|failed|503",
                            _visible_text(panel), re.I),
          "A failed discovery needs a visible actionable error in the Assistant")
    assert re.search(r"start|server|url|retry|refresh", _visible_text(panel), re.I)
    _assert_unconnected(window, panel, local)
    assert not window.cfg.get("ai", "local_model", default=""), \
        "Failed model discovery must not persist a successful model selection"
    assert not any(dialog.isVisible() for dialog in window.findChildren(SettingsDialog))

    local.fail_discovery = False
    _discover(panel)
    _wait(lambda: _model_selector(panel) is not None,
          "The discovery action must work again after the server recovers")
    models = _model_selector(panel)
    for index in range(models.count()):
        if models.itemData(index) == "qwen/qwen3.5-9b" or models.itemText(index) == "Qwen":
            models.setCurrentIndex(index)
            break
    _assert_unconnected(window, panel, local)
    connect = _button(panel, r"\bconnect\b")
    assert connect.isEnabled()
    connect.click()
    _wait(lambda: "lm studio" in panel.recipient.text().lower()
          and any(name.lower() in panel.recipient.text().lower() for name in MODELS.values()),
          "A successful retry must allow explicit connection")
    assert not local.posts and not window.scene.all()
