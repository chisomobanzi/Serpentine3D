"""Configure a local assistant and observe its real scene operations.

Only HTTP and framebuffer capture are fixtures. Settings, streamed replies,
the Agent, SerpApi, geometry, and the bottom history are the application.
No local-model implementation class or config-key spelling is prescribed.
"""

from __future__ import annotations

import base64
import json
import re
import threading
import time

import httpx
import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QComboBox, QLabel, QLineEdit,
)

from serpentine3d.app import MainWindow
from serpentine3d.ui.settings_dialog import SettingsDialog


ENDPOINT = "http://127.0.0.1:19451"
QWEN = "qwen/qwen3.5-9b"
GEMMA = "google/gemma-3-4b"
SECRET = "sk-ant-never-send-this-to-local"
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a"
    "l1sAAAAASUVORK5CYII=")


def _chunk(delta=None, finish=None, usage=None):
    result = {"choices": [{"index": 0, "delta": delta or {},
                           "finish_reason": finish}]}
    if usage is not None:
        result["usage"] = usage
    return result


def _sse(chunks):
    return ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks)
            + "data: [DONE]\n\n").encode()


def _answer(text="Done."):
    return _sse([
        _chunk({"reasoning_content": "PRIVATE REASONING"}),
        _chunk({"content": text[:3]}), _chunk({"content": text[3:]}),
        _chunk(finish="stop", usage={"prompt_tokens": 12,
                                    "completion_tokens": 7}),
    ])


def _calls(*calls):
    """Interleave indexed calls and fragment both names and JSON arguments."""
    chunks = []
    for index, (call_id, name, arguments) in enumerate(calls):
        encoded = arguments if isinstance(arguments, str) else json.dumps(arguments)
        chunks.append(_chunk({"tool_calls": [{
            "index": index, "id": call_id, "type": "function",
            "function": {"name": name[:3], "arguments": encoded[:5]},
        }]}))
    for index, (_, name, arguments) in enumerate(calls):
        encoded = arguments if isinstance(arguments, str) else json.dumps(arguments)
        chunks.append(_chunk({"tool_calls": [{
            "index": index,
            "function": {"name": name[3:], "arguments": encoded[5:12]},
        }]}))
        chunks.append(_chunk({"tool_calls": [{
            "index": index, "function": {"arguments": encoded[12:]},
        }]}))
    chunks.append(_chunk(finish="tool_calls"))
    return _sse(chunks)


BOX = {"command": "box", "inputs": ["0,0,0", "4,5,0", "6"]}


class LocalServer:
    """LM Studio's native discovery and OpenAI-compatible chat wire format."""

    def __init__(self):
        self.requests = []
        self.posts = []
        self.replies = []
        self.before_discovery = None
        self.before_post = None

    def handle(self, request):
        self.requests.append((request, threading.get_ident()))
        if request.method == "GET" and request.url.path == "/api/v1/models":
            if self.before_discovery:
                self.before_discovery()
            return httpx.Response(200, json={"models": [
                {"type": "llm", "key": QWEN, "display_name": "Qwen3.5 9B",
                 "loaded_instances": [],
                 "capabilities": {"vision": True, "trained_for_tool_use": True}},
                {"type": "llm", "key": GEMMA, "display_name": "Gemma 3 4B",
                 "loaded_instances": [],
                 "capabilities": {"vision": False, "trained_for_tool_use": True}},
                {"type": "embedding", "key": "embed-only",
                 "display_name": "Embedding only", "loaded_instances": []},
            ]})
        if request.method == "POST" and request.url.path == "/v1/chat/completions":
            self.posts.append(json.loads(request.content))
            if self.before_post:
                self.before_post()
            assert self.replies, "The assistant sent an unexpected extra request"
            reply = self.replies.pop(0)
            if isinstance(reply, Exception):
                raise reply
            if isinstance(reply, httpx.Response):
                return reply
            return httpx.Response(200, content=reply,
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(404, json={"error": "Fixture route not found"})


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
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    opened = []

    def create():
        window = MainWindow()
        opened.append(window)
        return window

    yield create
    for window in opened:
        panel = window.show_ai_panel()
        if panel.agent and panel.agent.busy:
            panel.agent.stop()
            _wait(lambda: not panel.agent.busy, "Agent did not stop at teardown")
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


def _assistant_settings(window):
    dialog = SettingsDialog(window)
    for index in range(dialog.sidebar.count()):
        if dialog.sidebar.item(index).text() == "Assistant":
            dialog.sidebar.setCurrentRow(index)
            return dialog, dialog.pages.currentWidget()
    pytest.fail("Settings must contain the Assistant page")


def _provider(page):
    for combo in page.findChildren(QComboBox):
        choices = [combo.itemText(i).lower() for i in range(combo.count())]
        if any("lm studio" in text for text in choices):
            assert any("anthropic" in text for text in choices), \
                "The existing Anthropic provider must remain available"
            return combo
    pytest.fail("Assistant settings need a provider choice including LM Studio")


def _choose(combo, text):
    for index in range(combo.count()):
        if (text.lower() in combo.itemText(index).lower()
                or combo.itemData(index) == text):
            combo.setCurrentIndex(index)
            QApplication.processEvents()
            return
    pytest.fail(f"The selector does not offer {text!r}")


def _endpoint(page):
    fields = [field for field in page.findChildren(QLineEdit)
              if field.text().startswith("http")
              or any(word in " ".join((field.accessibleName(), field.toolTip(),
                                       field.placeholderText())).lower()
                     for word in ("endpoint", "base url", "localhost", "127.0.0.1"))]
    assert len(fields) == 1, "LM Studio needs one editable server URL"
    return fields[0]


def _models(page):
    provider = _provider(page)
    # The existing settings page exposes the model choice as a combo box.
    choices = [combo for combo in page.findChildren(QComboBox)
               if combo is not provider]
    assert len(choices) == 1, "Assistant settings need one model selector"
    return choices[0]


def _refresh(page):
    buttons = [button for button in page.findChildren(QAbstractButton)
               if any(word in " ".join((button.text(), button.accessibleName(),
                                        button.toolTip())).lower()
                      for word in ("refresh", "discover", "load models"))]
    assert len(buttons) == 1, "LM Studio needs a discover/refresh models control"
    buttons[0].click()


def _configure(window, model=QWEN):
    dialog, page = _assistant_settings(window)
    _choose(_provider(page), "LM Studio")
    endpoint = _endpoint(page)
    endpoint.setText(ENDPOINT)
    endpoint.editingFinished.emit()
    _refresh(page)
    models = _models(page)
    _wait(lambda: any(models.itemData(i) == model or model in models.itemText(i)
                      for i in range(models.count())),
          "Discovered local LLM identifiers must be selectable")
    _choose(models, model)
    dialog.accept()
    panel = window.show_ai_panel()
    assert panel._ensure_agent() is not None, \
        "A configured local model must work without an Anthropic API key"
    return panel, page


def _send(panel, prompt):
    panel.input.setPlainText(prompt)
    panel._send()
    _wait(lambda: not panel.agent.busy and panel.btn_send.text() == "Send",
          "Assistant request did not finish")


def _feed(panel):
    return "\n".join(label.text() for label in panel.feed_host.findChildren(QLabel))


def _results(body):
    return {message["tool_call_id"]: message for message in body["messages"]
            if message["role"] == "tool"}


def test_discovery_is_asynchronous_filters_embeddings_and_settings_survive_reopen(
        windows, local):
    main_thread = threading.get_ident()
    observed_heartbeat = []
    from PySide6.QtCore import QTimer
    heartbeat = QTimer()
    heartbeat.setInterval(5)
    heartbeat.timeout.connect(lambda: observed_heartbeat.append(True))
    heartbeat.start()

    def slow_discovery():
        # A blocking discovery on Qt's thread cannot receive this heartbeat.
        before = len(observed_heartbeat)
        deadline = time.monotonic() + .25
        while len(observed_heartbeat) == before and time.monotonic() < deadline:
            time.sleep(.005)
        assert len(observed_heartbeat) > before, "Model discovery blocked Qt"

    local.before_discovery = slow_discovery
    window = windows()
    panel, page = _configure(window)
    heartbeat.stop()
    local.before_discovery = None
    assert not panel.setup_card.isVisibleTo(panel), "Local setup must not demand a cloud key"
    models = _models(page)
    choices = repr([(models.itemText(i), models.itemData(i)) for i in range(models.count())])
    assert QWEN in choices and GEMMA in choices
    assert "embed-only" not in choices and "Embedding only" not in choices
    discoveries = [(req, worker) for req, worker in local.requests
                   if req.url.path == "/api/v1/models"]
    assert discoveries and all(worker != main_thread for _, worker in discoveries)
    assert any(str(req.url).startswith(ENDPOINT) for req, _ in discoveries)

    reopened = windows()
    dialog, page = _assistant_settings(reopened)
    assert "lm studio" in _provider(page).currentText().lower()
    assert _endpoint(page).text().rstrip("/") == ENDPOINT
    models = _models(page)
    assert models.currentData() == QWEN or QWEN in models.currentText()
    dialog.accept()


def test_fragmented_local_tool_calls_create_geometry_and_return_matching_results(
        windows, local, monkeypatch):
    window = windows()
    window.cfg.set("ai", "api_key", SECRET)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET + "-env")
    panel, _ = _configure(window)
    local.replies = [
        _calls(("box-call", "run_command", BOX), ("info-call", "scene_info", {})),
        _answer("Built the box."),
    ]
    _send(panel, "make a 4 by 5 by 6 box")
    assert len(window.scene.all()) == 1
    assert window.scene.all()[0].kind == "solid"
    from serpentine3d.core import geometry
    low, high = geometry.bbox(window.scene.all()[0].shape)
    assert tuple(high[i] - low[i] for i in range(3)) == pytest.approx((4, 5, 6))
    assert len(local.posts) == 2
    first, second = local.posts
    assert first["model"] == QWEN and first["stream"] is True
    assert first["messages"][0]["role"] == "system"
    assert any(tool["type"] == "function"
               and tool["function"]["name"] == "run_command"
               and tool["function"]["parameters"]["type"] == "object"
               for tool in first["tools"])
    results = _results(second)
    assert set(results) == {"box-call", "info-call"}
    assert json.loads(results["info-call"]["content"])["object_count"] == 1
    tool_message = next(message for message in second["messages"]
                        if message.get("tool_calls"))
    assert [call["id"] for call in tool_message["tool_calls"]] == ["box-call", "info-call"]
    assert json.loads(tool_message["tool_calls"][0]["function"]["arguments"]) == BOX
    assert "Built the box." in _feed(panel)
    assert "PRIVATE REASONING" not in _feed(panel)
    history = window.command_line.echo_view.toPlainText()
    assert any(re.search(r"\b(ai|assistant)\b", line, re.I) and "box" in line.lower()
               for line in history.splitlines()), "AI scene operations need source-tagged history"
    for request, worker in local.requests:
        assert "anthropic" not in request.url.host
        assert SECRET not in str(request.headers) + request.content.decode()
        assert "x-api-key" not in request.headers
        assert worker != threading.get_ident(), "Local HTTP must not block Qt"


@pytest.mark.parametrize("failure, expected", [
    (httpx.Response(503, json={"error": {"message": "Model unavailable"}}), "unavailable"),
    (httpx.ConnectError("Local server is offline"), "offline"),
    (_calls(("bad-json", "run_command", '{"command":"box", BROKEN')), "argument"),
], ids=["http-error", "connection-error", "malformed-tool-arguments"])
def test_local_errors_are_visible_do_not_write_and_allow_another_turn(
        windows, local, failure, expected):
    window = windows()
    panel, _ = _configure(window)
    local.replies = [failure, _answer("Ready again.")]
    _send(panel, "try making a box")
    assert not window.scene.all()
    assert expected in _feed(panel).lower()
    _send(panel, "hello again")
    assert "Ready again." in _feed(panel)
    assert len(local.posts) == 2


def test_stop_discards_late_local_tool_calls_and_the_next_turn_is_usable(windows, local):
    window = windows()
    panel, _ = _configure(window)
    entered, release = threading.Event(), threading.Event()

    def delayed_reply():
        entered.set()
        release.wait(timeout=3)

    local.before_post = delayed_reply
    local.replies = [_calls(("late-box", "run_command", BOX)), _answer("Still here.")]
    panel.input.setPlainText("make a box slowly")
    panel._send()
    try:
        _wait(entered.is_set, "The local request did not start")
        assert panel.agent.busy
        panel._send_or_stop()
    finally:
        release.set()
    _wait(lambda: not panel.agent.busy and panel.btn_send.text() == "Send", "Stop did not complete")
    assert not window.scene.all(), "A reply arriving after Stop must not modify the scene"
    local.before_post = None
    _send(panel, "are you still there")
    assert "Still here." in _feed(panel)
    assert len(local.posts) == 2
    # The resumed request cannot contain any tool call lacking its result.
    messages = local.posts[-1]["messages"]
    call_ids = {call["id"] for msg in messages for call in msg.get("tool_calls", [])}
    result_ids = {msg["tool_call_id"] for msg in messages if msg["role"] == "tool"}
    assert call_ids == result_ids


def test_a_model_change_during_a_turn_applies_to_the_next_turn(windows, local):
    window = windows()
    panel, page = _configure(window)
    entered, release = threading.Event(), threading.Event()

    def delayed_first_reply():
        if len(local.posts) == 1:
            entered.set()
            release.wait(timeout=3)

    local.before_post = delayed_first_reply
    local.replies = [_calls(("box-call", "run_command", BOX)),
                     _answer("Box made."), _answer("New model ready.")]
    panel.input.setPlainText("build a box")
    panel._send()
    try:
        _wait(entered.is_set, "The first model request did not start")
        _choose(_models(page), GEMMA)
        # A duplicate send must not reconfigure the in-flight agent/client.
        panel.input.setPlainText("draft for next model")
        panel._send()
    finally:
        release.set()
    _wait(lambda: not panel.agent.busy and panel.btn_send.text() == "Send", "Turn did not finish")
    assert [body["model"] for body in local.posts] == [QWEN, QWEN]
    assert len(window.scene.all()) == 1
    _send(panel, "hello from the next model")
    assert local.posts[-1]["model"] == GEMMA
    assert "New model ready." in _feed(panel)


@pytest.mark.parametrize("model, vision", [(QWEN, True), (GEMMA, False)])
def test_screenshot_results_respect_the_selected_models_vision_capability(
        windows, local, monkeypatch, tmp_path, model, vision):
    window = windows()
    panel, _ = _configure(window, model)
    from serpentine3d.api import SerpApi
    captured = []

    def capture(api, *args, **kwargs):
        path = tmp_path / "fixture-frame.png"
        path.write_bytes(PNG)
        captured.append(True)
        return {"path": str(path), "width": 1, "height": 1}

    monkeypatch.setattr(SerpApi, "screenshot", capture)
    local.replies = [_calls(("look-call", "screenshot", {"width": 320})),
                     _answer("Checked the model.")]
    _send(panel, "check the scene")
    assert len(local.posts) == 2 and "Checked the model." in _feed(panel)
    second = local.posts[1]
    assert "look-call" in _results(second), "Image tools still need a matching tool result"
    blocks = [block for msg in second["messages"] if isinstance(msg.get("content"), list)
              for block in msg["content"]]
    images = [block for block in blocks if block.get("type") == "image_url"]
    if vision:
        assert captured and images, "Vision models need OpenAI image_url content"
        assert images[0]["image_url"]["url"] == "data:image/png;base64," + base64.b64encode(PNG).decode()
        assert isinstance(_results(second)["look-call"]["content"], str)
        assert any(msg["role"] == "user" and isinstance(msg.get("content"), list)
                   and any(block.get("type") == "image_url" for block in msg["content"])
                   for msg in second["messages"]), "OpenAI image parts belong in a user message"
    else:
        assert not images and "data:image" not in json.dumps(second)
        system = " ".join(str(msg.get("content", "")) for msg in second["messages"]
                          if msg["role"] == "system").lower()
        assert "must use screenshot" not in system
        assert "call screenshot and look at it" not in system
        result = str(_results(second)["look-call"]["content"]).lower()
        assert "vision" in result or "image" in result or "text-only" in result


def test_an_ai_mutation_does_not_overwrite_a_pending_cad_point_prompt(windows):
    """Provider-independent safety boundary, exercising the existing Agent."""
    from serpentine3d.ai.agent import Agent
    from serpentine3d.api import SerpApi
    from serpentine3d.commands.base import PointReq

    window = windows()
    window.processor.run("line")
    window.processor.provide_text("1,2,3")
    request = window.processor.request
    points = list(window.processor.picked_points)
    assert isinstance(request, PointReq)

    class PendingCommandClient:
        def __init__(self):
            self.calls = 0
            self.results = []

        def stream_message(self, system, messages, tools, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"content": [{"type": "tool_use", "id": "conflict",
                                     "name": "run_command", "input": BOX}],
                        "stop_reason": "tool_use", "usage": {}}
            self.results.extend(messages[-1]["content"])
            return {"content": [{"type": "text", "text": "Finish the line first."}],
                    "stop_reason": "end_turn", "usage": {}}

    client = PendingCommandClient()
    agent = Agent(SerpApi(window), client, parent=window)
    agent.send("make a box while I am drawing")
    _wait(lambda: not agent.busy, "Agent did not finish")
    assert window.processor.request is request and window.processor.busy, \
        "An AI tool must preserve the user's active CAD command"
    assert window.processor.picked_points == points
    assert not window.scene.all()
    assert client.results[0].get("is_error") is True
    result = str(client.results[0]["content"]).lower()
    assert "command" in result and any(word in result for word in ("finish", "pending", "busy", "active"))
    window.processor.provide_text("5,2,3")
    assert len(window.scene.all()) == 1, "The user must still be able to finish the original line"
