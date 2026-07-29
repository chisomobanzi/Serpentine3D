"""The MCP server's shape, without a running app behind it.

Every tool here is a thin wrapper over one RPC call, so what is worth
pinning down is the wiring: that the module imports against the mcp version
we actually depend on, that the tools are registered under the names a
client will look for, and that a dead bridge is reported rather than raised
into the client's face.
"""

import asyncio
import json

from serpentine3d.mcp_server import server as S

EXPECTED_TOOLS = {
    "serp_scene_info", "serp_screenshot", "serp_create_curve",
    "serp_create_surface", "serp_boolean", "serp_transform", "serp_select",
    "serp_command", "serp_layers", "serp_import", "serp_export",
    "serp_measure", "serp_undo", "serp_viewport",
}


def _tools():
    """The registry is async in mcp 2.x; nothing here needs a live loop."""
    return asyncio.run(S.mcp.list_tools())


def test_every_tool_is_registered_under_the_name_clients_call():
    assert {t.name for t in _tools()} == EXPECTED_TOOLS


def test_every_tool_tells_the_client_what_it_is_for():
    """A tool with no description is a tool the model will not reach for."""
    bare = [t.name for t in _tools()
            if not (t.description or "").strip()]
    assert not bare


def test_the_server_announces_itself_with_instructions():
    assert "Serpentine3D" in (S.mcp.instructions or "")


def test_a_dead_bridge_comes_back_as_text_not_an_exception(monkeypatch):
    """The app is a separate process and may simply not be running. That is
    an answer the model can act on, not a crash for the client to handle."""
    def _boom(method, **params):
        raise RuntimeError("Serpentine3D is not running (no RPC port file).")

    monkeypatch.setattr(S._bridge, "call", _boom)
    out = S._call("scene_info")
    assert out.startswith("Error: ")
    assert "not running" in out


def test_a_result_comes_back_as_readable_json(monkeypatch):
    monkeypatch.setattr(S._bridge, "call",
                        lambda method, **p: {"objects": ["Curve 01"]})
    assert json.loads(S._call("scene_info")) == {"objects": ["Curve 01"]}


def test_a_screenshot_is_returned_as_an_image_and_the_file_cleaned_up(
        tmp_path, monkeypatch):
    """The bridge writes a PNG to disk; leaving it there would litter the
    user's temp dir once per look."""
    png = tmp_path / "shot.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    monkeypatch.setattr(S._bridge, "call",
                        lambda method, **p: {"path": str(png)})
    img = S.serp_screenshot(width=800)
    assert img.data == b"\x89PNG\r\n\x1a\nfake"
    assert img._mime_type == "image/png"
    assert not png.exists()
