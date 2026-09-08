"""External tools share the user's history and respect an in-progress command.

The real RPC dispatcher runs from a worker while the test pumps Qt events.
No listening socket or user's RPC port is needed. Only the MCP transport is
replaced when testing the registered script tool end to end into the window.
"""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QTabBar, QTextEdit, QWidget

from serpentine3d.app import MainWindow
from serpentine3d.commands.base import PointReq
from serpentine3d.mcp_server import server as mcp_server
from serpentine3d.rpc import RpcServer


CURVE = {"points": [[0, 0, 0], [12, 0, 0]], "kind": "line", "name": "MCP guide"}
SCRIPT = 'doc.add(geo.make_box((0, 0, 0), 2, 3, 4), name="Prepared box")\n'


@pytest.fixture
def session(monkeypatch, tmp_path):
    monkeypatch.setenv("SERP3D_NO_RPC", "1")
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    monkeypatch.setenv("SERP3D_PLUGIN_DIR", str(tmp_path / "plugins"))
    window = MainWindow()
    rpc = RpcServer(window)
    yield window, rpc
    window.processor.cancel()
    window.mark_saved()
    window.close()
    QApplication.processEvents()


def _background(fn):
    """Exercise BlockingQueuedConnection without blocking its owning thread."""
    result = {}
    done = threading.Event()

    def run():
        try:
            result["value"] = fn()
        except BaseException as exc:
            result["error"] = exc
        finally:
            done.set()

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    until = time.monotonic() + 6
    while not done.is_set() and time.monotonic() < until:
        QTest.qWait(5)
    assert done.is_set(), "The RPC call must finish while the Qt thread handles its job"
    worker.join(timeout=1)
    if "error" in result:
        raise result["error"]
    return result["value"]


def _request(rpc, method, params=None, request_id=41):
    raw = json.dumps({"id": request_id, "method": method, "params": params or {}}).encode()
    response = json.loads(_background(lambda: rpc._handle_line(raw)))
    assert response["id"] == request_id, "RPC responses must retain their request id"
    return response


def _history(window):
    return window.command_line.echo_view.toPlainText()


def _mcp_lines(window):
    return [line for line in _history(window).splitlines()
            if re.search(r"\bmcp\b", line, re.I)]


def _pending_line(window):
    window.processor.run("line")
    window.processor.provide_text("1,2,3")
    assert isinstance(window.processor.request, PointReq)
    return window.processor.request, list(window.processor.picked_points)


def _assert_pending(window, request, points):
    assert window.processor.busy and window.processor.request is request, \
        "MCP must not replace or cancel the user's pending CAD prompt"
    assert window.processor.picked_points == points


def _editor(window):
    pane = window.command_workspace.script_pane
    editors = [editor for editor in pane.findChildren(QWidget)
               if isinstance(editor, (QPlainTextEdit, QTextEdit))
               and not editor.isReadOnly() and editor.isVisibleTo(pane)]
    assert len(editors) == 1, "Script must expose one active editable source document"
    return editors[0]


def test_rpc_geometry_is_attributed_in_common_history_and_remains_undoable(session):
    window, rpc = session
    result = _background(lambda: rpc.call("create_curve", CURVE))
    assert result["name"] == "MCP guide"
    assert len(window.scene.all()) == 1
    assert result["bbox"][0] == pytest.approx([0, 0, 0], abs=1e-6)
    assert result["bbox"][1] == pytest.approx([12, 0, 0], abs=1e-6)
    assert window.history.can_undo
    undone = _background(lambda: rpc.call("undo", {}))
    assert undone["undone"] and window.scene.all() == []
    redone = _background(lambda: rpc.call("redo", {}))
    assert redone["redone"] and len(window.scene.all()) == 1
    lines = _mcp_lines(window)
    assert any("curve" in line.lower() for line in lines), \
        "Successful MCP geometry work must be identifiable in the shared command history"
    assert any("undo" in line.lower() for line in lines)
    assert any("redo" in line.lower() for line in lines)


def test_rpc_failure_returns_useful_json_and_an_attributed_history_error(session):
    window, rpc = session
    response = _request(rpc, "transform", {
        "operation": "move", "targets": ["Missing guide"],
        "params": {"offset": [1, 0, 0]},
    })
    assert "result" not in response and "Missing guide" in response["error"]
    assert window.scene.all() == [] and not window.history.can_undo
    assert any("Missing guide" in line and "transform" in line.lower()
               for line in _mcp_lines(window)), \
        "The user must see the failing MCP operation and reason in command history"


@pytest.mark.parametrize("method,params", [
    ("command", {"command": "box", "inputs": ["0,0,0", "4,5,0", "6"]}),
    ("create_curve", CURVE),
    ("layers", {"action": "create", "name": "From MCP"}),
])
def test_rpc_mutation_cannot_displace_a_pending_cad_command(session, method, params):
    window, rpc = session
    request, points = _pending_line(window)
    layers_before = [(layer.id, layer.name) for layer in window.scene.layers.all()]
    response = _request(rpc, method, params)
    assert "error" in response, "Conflicting MCP edits must be rejected while a CAD command awaits input"
    message = response["error"].lower()
    assert "command" in message and any(word in message for word in ("finish", "active", "pending", "busy"))
    _assert_pending(window, request, points)
    assert window.scene.all() == []
    assert [(layer.id, layer.name) for layer in window.scene.layers.all()] == layers_before
    assert any("command" in line.lower() for line in _mcp_lines(window))
    window.processor.provide_text("5,2,3")
    assert len(window.scene.all()) == 1, "The user's original Line must still be finishable"


def test_rpc_queries_remain_available_during_a_cad_prompt(session):
    window, rpc = session
    request, points = _pending_line(window)
    info = _request(rpc, "scene_info")
    layers = _request(rpc, "layers", {"action": "list"})
    measured = _request(rpc, "measure", {
        "what": "distance", "points": [[0, 0, 0], [3, 4, 0]],
    })
    assert info["result"]["object_count"] == 0
    assert "result" in layers and "error" not in layers
    assert measured["result"]["distance"] == pytest.approx(5)
    _assert_pending(window, request, points)
    assert window.scene.all() == []
    assert any("scene_info" in line for line in _mcp_lines(window)), \
        "Read operations also belong to the shared MCP history"


@pytest.mark.parametrize("mode", ["command", "ai"])
@pytest.mark.parametrize("pending", [False, True])
def test_registered_mcp_tool_prepares_an_editable_draft_without_running_it(
        session, monkeypatch, mode, pending):
    window, rpc = session
    workspace = window.command_workspace
    workspace.set_pane_visible("script", True)
    original = "# Unfinished user draft\nwidth = 123\n"
    _editor(window).setPlainText(original)
    workspace.set_pane_visible("script", False)
    workspace.set_mode(mode)
    if pending:
        request, points = _pending_line(window)
    can_undo_before = window.history.can_undo

    registered = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}
    assert "serp_prepare_script" in registered, \
        "External MCP agents need a discoverable script handoff tool"
    schema = registered["serp_prepare_script"].input_schema
    assert {"source", "title"} <= set(schema["properties"])
    assert "source" in schema["required"]
    assert registered["serp_prepare_script"].description
    monkeypatch.setattr(mcp_server._bridge, "call", lambda method, **params: rpc.call(method, params))
    output = _background(lambda: mcp_server.serp_prepare_script(
        source=SCRIPT, title="Prepared box.py"))
    result = json.loads(output)
    assert result["executed"] is False and result["status"] == "draft"
    assert workspace.script_pane.isVisibleTo(workspace)
    assert _editor(window).toPlainText() == SCRIPT
    _editor(window).insertPlainText("# editable\n")
    assert "# editable" in _editor(window).toPlainText()
    found_original = False
    for tabs in workspace.script_pane.findChildren(QTabBar):
        for index in range(tabs.count()):
            tabs.setCurrentIndex(index)
            QApplication.processEvents()
            found_original |= _editor(window).toPlainText() == original
    assert found_original, "MCP script handoff must preserve the user's existing draft"
    assert workspace.mode == mode, "External work must not switch Command / Ask AI routing"
    assert window.scene.all() == [] and window.history.can_undo == can_undo_before
    assert any("script" in line.lower() for line in _mcp_lines(window))
    if pending:
        _assert_pending(window, request, points)
        window.processor.provide_text("5,2,3")
        assert len(window.scene.all()) == 1
