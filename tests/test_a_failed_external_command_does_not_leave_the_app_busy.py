"""A command started over RPC or MCP that fails part-way is cancelled.

`command` feeds its inputs one by one. When one of them raised, the command
it had started was still waiting at its prompt, and every later external
call was refused with "Finish or cancel the active CAD command", undo
included. Nothing outside the window could cancel it; the modeller had to
come back and press Escape. The command belongs to the call that started it,
so a call that fails cleans up after itself.

A command the modeller has running is still left alone: the call is refused
before it can start anything.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.api import ApiError
from serpentine3d.app import MainWindow
from serpentine3d.rpc import RpcServer


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("SERP3D_NO_RPC", "1")
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    monkeypatch.setenv("SERP3D_PLUGIN_DIR", str(tmp_path / "plugins"))
    window = MainWindow()
    yield RpcServer(window).api
    window.processor.cancel()
    window.mark_saved()
    window.close()
    QApplication.processEvents()


def test_an_input_that_raises_cancels_the_command_it_was_fed_to(api, monkeypatch):
    feed = api.processor.provide_text
    calls = {"n": 0}

    def fails_on_the_second_input(text):
        calls["n"] += 1
        if calls["n"] == 2:
            raise AttributeError("a snap that could not read this object")
        return feed(text)

    monkeypatch.setattr(api.processor, "provide_text", fails_on_the_second_input)

    with pytest.raises(AttributeError):
        api.command("line", inputs=["0,0,0", "10,0,0"])

    assert not api.processor.busy
    monkeypatch.setattr(api.processor, "provide_text", feed)
    api.command("line", inputs=["0,0,0", "10,0,0"])
    assert len(api.scene.all()) == 1


def test_a_command_the_modeller_has_running_is_still_refused_not_cancelled(api):
    api.processor.run("line")
    assert api.processor.busy

    with pytest.raises(ApiError, match="Finish or cancel"):
        with api.external_operation("command", {}, source="MCP"):
            api.command("circle", inputs=["0,0,0", "5"])

    assert api.processor.busy
