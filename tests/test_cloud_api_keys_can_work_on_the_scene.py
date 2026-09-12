"""Connect cloud API keys through the real Assistant and act on its scene.

Only HTTP is replaced. UI, persisted preferences, Agent streaming/tool dispatch,
geometry, and shared command history remain the application's real objects.
"""

from __future__ import annotations

import json
import re
import threading

import httpx
import pytest
from PySide6.QtWidgets import QComboBox, QLineEdit

from serpentine3d.app import MainWindow
from serpentine3d.ui.settings_dialog import SettingsDialog
from tests.test_local_models_can_work_on_the_scene import (
    BOX, LocalServer, _answer, _assistant_settings, _calls, _choose,
    _configure, _feed, _models, _provider,
)
from tests.test_the_assistant_connects_before_the_first_prompt import (
    _button, _connection_choices, _lay_out, _mode, _visible_text, _wait,
)


OPENAI_KEY = "sk-proj-openai-test-only"
ANTHROPIC_KEY = "sk-ant-anthropic-test-only"
ENV_KEY = "sk-proj-environment-test-only"


def _anthropic_answer():
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 8}}},
        {"type": "content_block_start", "index": 0,
         "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0,
         "delta": {"type": "text_delta", "text": "Anthropic connected."}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
         "usage": {"output_tokens": 4}},
        {"type": "message_stop"},
    ]
    return "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                   for event in events).encode()


class CloudAndLocalServers:
    def __init__(self):
        self.requests = []
        self.posts = []
        self.replies = []
        self.local = LocalServer()

    def handle(self, request):
        self.requests.append((request, threading.get_ident()))
        if request.url.host == "127.0.0.1":
            return self.local.handle(request)
        if request.url.host == "api.openai.com":
            if request.method == "GET" and request.url.path == "/v1/models":
                return httpx.Response(200, json={"object": "list", "data": [
                    {"id": "gpt-5.4", "object": "model", "owned_by": "openai"},
                    {"id": "gpt-4.1", "object": "model", "owned_by": "openai"},
                ]})
            if request.method == "POST" and request.url.path == "/v1/chat/completions":
                self.posts.append(json.loads(request.content))
                reply = self.replies.pop(0) if self.replies else _answer("OpenAI connected.")
                if isinstance(reply, Exception):
                    raise reply
                if isinstance(reply, httpx.Response):
                    return reply
                return httpx.Response(200, content=reply,
                                      headers={"content-type": "text/event-stream"})
        if request.url.host == "api.anthropic.com" and request.url.path == "/v1/messages":
            return httpx.Response(200, content=_anthropic_answer(),
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(403, text="Unexpected provider destination")


@pytest.fixture
def servers(monkeypatch):
    server = CloudAndLocalServers()
    original_init = httpx.Client.__init__

    def init(client, *args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(server.handle)
        original_init(client, *args, **kwargs)

    monkeypatch.setattr(httpx.Client, "__init__", init)
    return server


@pytest.fixture
def windows(monkeypatch, tmp_path, servers):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RPC", "1")
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    opened = []

    def create():
        window = MainWindow()
        opened.append(window)
        window.resize(1400, 900)
        _lay_out(window)
        return window

    yield create
    for window in opened:
        panel = window.command_workspace.assistant
        if panel and panel.agent and panel.agent.busy:
            panel.agent.stop()
            _wait(lambda: not panel.agent.busy, "Cloud assistant did not stop")
        for dialog in window.findChildren(SettingsDialog):
            dialog.close()
        window.processor.cancel()
        window.mark_saved()
        window.close()


def _cloud_provider(window, panel, provider="OpenAI"):
    choices = _connection_choices(panel, r"API key")
    if not choices:
        _button(panel, r"connection options").click()
        _lay_out(window)
        choices = _connection_choices(panel, r"API key")
    assert choices, "Assistant needs an inline API-key connection option"
    control, index = choices[0]
    control.click() if index is None else control.setCurrentIndex(index)
    _lay_out(window)
    for combo in panel.findChildren(QComboBox):
        if not combo.isVisibleTo(panel):
            continue
        labels = [combo.itemText(i).lower() for i in range(combo.count())]
        if any("openai" in label for label in labels):
            assert any("anthropic" in label for label in labels), \
                "OpenAI API keys must be offered alongside Anthropic"
            _choose(combo, provider)
            _lay_out(window)
            return combo
    pytest.fail("API-key setup must offer a selectable OpenAI provider alongside Anthropic")


def _key_field(root):
    fields = [field for field in root.findChildren(QLineEdit)
              if field.isVisibleTo(root) and not field.isReadOnly()
              and re.search(r"api.?key", " ".join((field.accessibleName(),
                                  field.placeholderText(), field.toolTip())), re.I)]
    assert len(fields) == 1, "Selected cloud provider needs one clearly labelled API-key field"
    assert fields[0].echoMode() == QLineEdit.EchoMode.Password
    return fields[0]


def _connect_openai(window, servers, key=OPENAI_KEY):
    panel = window.show_ai_panel()
    _lay_out(window)
    provider = _cloud_provider(window, panel)
    field = _key_field(panel)
    assert "anthropic" not in (field.accessibleName() + field.placeholderText()).lower(), \
        "OpenAI key entry must not retain Anthropic labels"
    field.setText(key)
    field.editingFinished.emit()
    models = [combo for combo in panel.findChildren(QComboBox)
              if combo.isVisibleTo(panel) and combo is not provider]
    assert len(models) == 1, "OpenAI setup needs a model choice"
    models = models[0]
    if not models.count() or not (models.currentData() or models.currentText()).strip():
        _button(panel, r"refresh|discover|load models").click()
        _wait(lambda: models.count() > 0 and models.currentData(),
              "OpenAI model discovery must offer a usable selection")
    # Select a genuine offered model; no implementation-specific default ID.
    candidates = [i for i in range(models.count())
                  if re.match(r"gpt-|o[134](?:-|$)",
                              str(models.itemData(i) or models.itemText(i)), re.I)]
    assert candidates or models.isEditable(), "Offer a usable OpenAI model or editable model ID"
    if candidates:
        models.setCurrentIndex(candidates[-1])
    else:
        models.setEditText("gpt-4.1")
    model = str(models.currentData() or models.currentText())
    label = models.currentText()
    assert not servers.posts and not window.scene.all(), "Drafting a key must not send a prompt"
    connect = _button(panel, r"\bconnect\b")
    assert connect.isEnabled(), "A key and selected OpenAI model must permit explicit Connect"
    connect.click()
    _lay_out(window)
    _wait(lambda: "openai" in panel.recipient.text().lower(),
          "Connect must identify OpenAI as the active recipient")
    assert model.lower() in panel.recipient.text().lower() or label.lower() in panel.recipient.text().lower()
    assert not servers.posts, "Connecting does not authorize an inference request"
    return panel, model


def _send(window, panel, prompt):
    _mode(window, "Ask AI").click()
    _lay_out(window)
    panel.input.setPlainText(prompt)
    send = window.command_workspace.submit_button
    assert send.isEnabled(), "A connected Assistant needs an enabled Send action"
    send.click()
    _wait(lambda: panel.agent is not None and not panel.agent.busy,
          "The cloud Assistant turn must finish")


def test_openai_key_connection_persists_in_settings_and_streams_real_scene_tools(windows, servers):
    window = windows()
    panel, model = _connect_openai(window, servers)
    reopened = windows()
    panel = reopened.show_ai_panel()
    _lay_out(reopened)
    assert "openai" in panel.recipient.text().lower()
    dialog, page = _assistant_settings(reopened)
    assert "openai" in _provider(page).currentText().lower(), \
        "Opening Settings must preserve the API-key provider"
    assert (_models(page).currentData() or _models(page).currentText()) == model
    assert "anthropic" not in (_key_field(page).accessibleName()
                               + _key_field(page).placeholderText()).lower()
    dialog.accept()
    servers.replies = [_calls(("cloud-box", "run_command", BOX)), _answer("Built the cloud box.")]
    _send(reopened, panel, "Make a 4 by 5 by 6 box")
    assert len(reopened.scene.all()) == 1 and reopened.scene.all()[0].kind == "solid"
    from serpentine3d.core import geometry
    low, high = geometry.bbox(reopened.scene.all()[0].shape)
    assert tuple(high[i] - low[i] for i in range(3)) == pytest.approx((4, 5, 6))
    assert len(servers.posts) == 2
    assert all(body["model"] == model and body["stream"] for body in servers.posts)
    assert all("max_completion_tokens" in body and "max_tokens" not in body
               for body in servers.posts), "Use OpenAI's current Chat Completions token limit"
    assert any(message.get("role") == "tool" and message.get("tool_call_id") == "cloud-box"
               for message in servers.posts[1]["messages"])
    assert "Built the cloud box." in _feed(panel)
    history = reopened.command_line.echo_view.toPlainText()
    assert any(re.search(r"\b(ai|assistant)\b", line, re.I) and "box" in line.lower()
               for line in history.splitlines()), "The actual scene edit must reach shared history"
    assert "Unknown command" not in history
    for request, worker in servers.requests:
        assert request.url.host == "api.openai.com"
        assert request.headers.get("authorization") == "Bearer " + OPENAI_KEY
        assert "x-api-key" not in request.headers
        assert worker != threading.get_ident(), "Cloud HTTP must not block Qt"


def test_switching_cloud_providers_keeps_keys_separate_and_local_receives_neither(windows, servers):
    window = windows()
    window.cfg.set("ai", "api_key", ANTHROPIC_KEY)
    panel, model = _connect_openai(window, servers)
    _send(window, panel, "hello OpenAI")
    dialog, page = _assistant_settings(window)
    _choose(_provider(page), "Anthropic")
    assert _key_field(page).text() == ANTHROPIC_KEY, "OpenAI setup must preserve the Anthropic key"
    dialog.accept()
    _send(window, panel, "hello Anthropic")
    assert "Anthropic connected." in _feed(panel)
    dialog, page = _assistant_settings(window)
    _choose(_provider(page), "OpenAI")
    assert _key_field(page).text() == OPENAI_KEY, "Returning to OpenAI restores only its own key"
    assert (_models(page).currentData() or _models(page).currentText()) == model
    dialog.accept()
    _send(window, panel, "hello OpenAI again")
    servers.local.replies = [_answer("Local connected.")]
    panel, _ = _configure(window)
    _send(window, panel, "hello local")
    assert "Local connected." in _feed(panel)
    for request, _ in servers.requests:
        outgoing = str(request.headers) + request.content.decode()
        if request.url.host == "api.openai.com":
            assert request.headers.get("authorization") == "Bearer " + OPENAI_KEY
            assert ANTHROPIC_KEY not in outgoing
        elif request.url.host == "api.anthropic.com":
            assert request.headers.get("x-api-key") == ANTHROPIC_KEY
            assert OPENAI_KEY not in outgoing
        else:
            assert request.url.host == "127.0.0.1"
            assert OPENAI_KEY not in outgoing and ANTHROPIC_KEY not in outgoing


def test_openai_environment_key_takes_precedence_without_being_saved(windows, servers, monkeypatch, tmp_path):
    window = windows()
    monkeypatch.setenv("OPENAI_API_KEY", ENV_KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    panel, _ = _connect_openai(window, servers)
    _send(window, panel, "hello with the environment key")
    assert servers.posts, "Explicit OpenAI connection must permit a prompt"
    assert all(request.headers.get("authorization") == "Bearer " + ENV_KEY
               for request, _ in servers.requests)
    saved = (tmp_path / "settings.json").read_text()
    assert ENV_KEY not in saved and ANTHROPIC_KEY not in saved
    assert OPENAI_KEY in saved, "Only the explicitly entered provider key is persisted"
    assert ENV_KEY not in _visible_text(panel) + _feed(panel)


@pytest.mark.parametrize("failure, expected", [
    (httpx.Response(401, json={"error": {"message": "Incorrect API key: " + OPENAI_KEY}}),
     r"api key|authentication|unauthori[sz]ed"),
    (httpx.ConnectError("Connection unavailable"), r"connect|network|unavailable"),
], ids=["invalid-key", "connection-error"])
def test_openai_errors_identify_the_provider_hide_the_key_and_allow_retry(windows, servers, failure, expected):
    window = windows()
    panel, _ = _connect_openai(window, servers)
    servers.replies = [failure, _answer("Ready again.")]
    _send(window, panel, "try making a box")
    error = _feed(panel)
    assert re.search(expected, error, re.I), "Connection failures need an actionable error"
    assert "openai" in error.lower() and "lm studio" not in error.lower()
    assert OPENAI_KEY not in error, "Provider error bodies must not expose the API key"
    assert not window.scene.all()
    _send(window, panel, "try again")
    assert "Ready again." in _feed(panel)
    assert len(servers.posts) == 2
