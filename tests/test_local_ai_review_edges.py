"""Regression coverage for the local-provider integration review."""

import json
import copy
import threading
import time

import httpx
import pytest
from PySide6.QtWidgets import QApplication, QWidget
from shiboken6 import delete

from serpentine3d.ai.agent import Agent
from serpentine3d.ai.client import AiError
from serpentine3d.ai.local_client import LocalClient
from serpentine3d.api import SerpApi
from serpentine3d.app import MainWindow
from serpentine3d.ui.settings_dialog import SettingsDialog, _ModelDiscovery


@pytest.fixture
def window(monkeypatch, tmp_path):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RPC", "1")
    window = MainWindow()
    yield window
    window.mark_saved()
    window.close()


def test_discovery_can_finish_after_its_dialog_is_destroyed(monkeypatch):
    from serpentine3d.ai import local_client

    entered, release = threading.Event(), threading.Event()
    failures, threads = [], []
    real_thread = threading.Thread

    def new_thread(*args, **kwargs):
        thread = real_thread(*args, **kwargs)
        threads.append(thread)
        return thread

    def discover(endpoint):
        entered.set()
        assert release.wait(2)
        return []

    monkeypatch.setattr(local_client, "discover_models", discover)
    monkeypatch.setattr(threading, "Thread", new_thread)
    monkeypatch.setattr(threading, "excepthook", lambda args: failures.append(args.exc_value))
    owner = QWidget()
    discovery = _ModelDiscovery(owner)
    discovery.start("http://127.0.0.1:1234")
    assert entered.wait(2)
    delete(owner)
    release.set()
    threads[0].join(timeout=2)
    assert not threads[0].is_alive()
    assert failures == []


def test_changing_servers_invalidates_discovered_vision_metadata(window):
    window.cfg.set("ai", "provider", "lmstudio")
    window.cfg.set("ai", "local_endpoint", "http://127.0.0.1:1234")
    window.cfg.set("ai", "local_model", "shared-model-id")
    window.cfg.set("ai", "local_models", [{"id": "shared-model-id", "vision": True}])
    window.show_ai_panel()
    panel = window.command_workspace.assistant
    dialog = SettingsDialog(window)
    assert panel._settings()[-1] is True

    dialog.ed_ai_endpoint.setText("http://127.0.0.1:4321")
    dialog.ed_ai_endpoint.editingFinished.emit()

    assert window.cfg.get("ai", "local_models") == []
    assert panel._settings() == ("lmstudio", "http://127.0.0.1:4321", "shared-model-id", False)
    assert "Refresh" in dialog.ai_discovery_status.text()
    # An old in-flight discovery cannot restore the previous capabilities.
    dialog._ai_models_discovered("http://127.0.0.1:1234",
                                 [{"id": "shared-model-id", "vision": True}], "")
    assert window.cfg.get("ai", "local_models") == []
    dialog.close()


def test_failed_followup_keeps_the_tools_that_already_changed_geometry(window):
    class FailingFollowup:
        calls = 0

        def stream_message(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {"stop_reason": "tool_use", "content": [{
                    "type": "tool_use", "id": "created-box", "name": "run_command",
                    "input": {"command": "Box", "inputs": ["0,0,0", "4,5,0", "6"]}}]}
            raise AiError("local server disconnected")

    agent = Agent(SerpApi(window), FailingFollowup(), parent=window)
    failures = []
    agent.errorRaised.connect(failures.append)
    agent.send("Make a box")
    deadline = time.monotonic() + 5
    while agent.busy and time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.002)
    QApplication.processEvents()
    assert not agent.busy
    assert failures == ["local server disconnected"]
    assert len(window.scene.all()) == 1
    assert [message["role"] for message in agent.messages] == ["user", "assistant", "user"]
    assert agent.messages[-1]["content"][0]["tool_use_id"] == "created-box"
    assert not agent.messages[-1]["content"][0].get("is_error")


def test_incomplete_box_returns_an_explicit_correlated_tool_error(window, monkeypatch):
    agent = Agent(SerpApi(window), object(), parent=window)
    # This test already runs on Qt's main thread, where API dispatch belongs.
    monkeypatch.setattr(agent, "_on_main", lambda invoke: invoke())
    result = agent._run_tool({"id": "missing-height", "name": "run_command",
                              "input": {"command": "Box",
                                        "inputs": ["0,0,0", "40,30,20"]}})
    assert result["tool_use_id"] == "missing-height"
    assert result["is_error"] is True
    assert "Height" in result["content"]
    assert "additional values" in result["content"]
    assert window.scene.all() == []
    assert not window.processor.busy


def test_new_chat_during_a_response_clears_history_and_ignores_late_updates(window):
    entered, release = threading.Event(), threading.Event()

    class DelayedReply:
        def __init__(self):
            self.requests = []

        def stream_message(self, messages, on_text, **kwargs):
            self.requests.append(copy.deepcopy(messages))
            if len(self.requests) == 1:
                entered.set()
                assert release.wait(3)
                # An HTTP chunk can arrive after New chat requested Stop.
                on_text("OLD RESPONSE ARRIVED LATE")
                return {"stop_reason": "end_turn", "content": [
                    {"type": "text", "text": "OLD RESPONSE ARRIVED LATE"}],
                    "usage": {"input_tokens": 1000, "output_tokens": 1000}}
            on_text("Fresh answer")
            return {"stop_reason": "end_turn", "content": [
                {"type": "text", "text": "Fresh answer"}]}

    def settle(predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.002)
        QApplication.processEvents()
        assert predicate()

    window.cfg.set("ai", "provider", "anthropic")
    window.cfg.set("ai", "api_key", "test-key")
    window.show_ai_panel()
    panel = window.command_workspace.assistant
    agent = panel._ensure_agent()
    agent.client.close()
    client = DelayedReply()
    agent.client = client
    panel.input.setPlainText("OLD REQUEST")
    panel._send()
    try:
        assert entered.wait(2)
        panel._new_chat()
    finally:
        release.set()
    settle(lambda: not agent.busy and panel.input.isEnabled())
    assert agent.messages == []
    assert panel.feed.count() == 1, "Only the feed's spacer belongs in a fresh chat"
    assert panel.usage.text() == ""
    assert panel.btn_send.text() == "Send"
    assert panel._chips == []

    panel.input.setPlainText("NEW REQUEST")
    panel._send()
    settle(lambda: not agent.busy and panel.input.isEnabled())
    assert client.requests[-1] == [{"role": "user", "content": "NEW REQUEST"}]
    assert panel._stream_label is None
    assert agent.messages[-1]["content"] == [{"type": "text", "text": "Fresh answer"}]


@pytest.mark.parametrize("finish, expected", [("length", "output limit"), ("stop", "empty response")])
def test_invisible_reasoning_is_not_presented_as_an_empty_success(finish, expected):
    events = [
        {"choices": [{"delta": {"reasoning_content": "private thought"}, "finish_reason": None}]},
        {"choices": [{"delta": {}, "finish_reason": finish}]},
    ]
    stream = "".join("data: " + json.dumps(event) + "\n\n" for event in events) + "data: [DONE]\n\n"
    response = httpx.Response(200, content=stream)
    client = LocalClient("http://127.0.0.1:1234", "local-model")
    emitted = []
    try:
        with pytest.raises(AiError, match=expected):
            client._consume(response, emitted.append, None)
    finally:
        client.close()
    assert emitted == []
