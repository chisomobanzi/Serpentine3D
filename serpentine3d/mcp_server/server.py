"""Serpentine3D MCP server.

Runs as a stdio MCP process and forwards tool calls to a running Serpentine3D
GUI via its localhost RPC bridge. Start Serpentine3D first (`serp3d`), then
register this server with your MCP client:

    claude mcp add serpentine3d -- serp3d-mcp
"""

from __future__ import annotations

import base64
import json
import os
import socket
from typing import Any

from mcp.server.fastmcp import FastMCP, Image

PORT_FILE = os.path.expanduser("~/.serpentine3d/rpc.port")

mcp = FastMCP(
    "serpentine3d",
    instructions=(
        "Control the Serpentine3D NURBS 3D modeller. Objects are referenced "
        "by name (e.g. 'Curve 01') or id. Typical flow: serp_scene_info to "
        "see what exists, create geometry, then serp_screenshot to look at "
        "the result. Units are generic model units; the construction plane "
        "is world XY with Z up."
    ),
)


class _Bridge:
    def __init__(self):
        self.sock = None
        self.buf = b""
        self.next_id = 0

    def connect(self):
        port = os.environ.get("SERP3D_RPC_PORT")
        if not port:
            try:
                port = open(PORT_FILE).read().strip()
            except OSError as exc:
                raise RuntimeError(
                    "Serpentine3D is not running (no RPC port file). "
                    "Launch the app with `serp3d` first.") from exc
        self.sock = socket.create_connection(("127.0.0.1", int(port)),
                                             timeout=180)

    def call(self, method: str, **params) -> Any:
        for attempt in (1, 2):
            if self.sock is None:
                self.connect()
            try:
                return self._roundtrip(method, params)
            except (OSError, ConnectionError):
                self.sock = None
                if attempt == 2:
                    raise RuntimeError(
                        "Lost connection to Serpentine3D — is the app running?")

    def _roundtrip(self, method: str, params: dict) -> Any:
        self.next_id += 1
        msg = json.dumps({"method": method, "params": params,
                          "id": self.next_id})
        self.sock.sendall(msg.encode() + b"\n")
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("closed")
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        resp = json.loads(line)
        if "error" in resp:
            raise RuntimeError(resp["error"])
        return resp["result"]


_bridge = _Bridge()


def _call(method: str, **params) -> str:
    try:
        result = _bridge.call(method, **params)
        return json.dumps(result, indent=1)
    except RuntimeError as exc:
        return f"Error: {exc}"


# ------------------------------------------------------------------- tools

@mcp.tool()
def serp_scene_info() -> str:
    """Get the current scene: objects (name/kind/layer/bbox), layers,
    selection, bounds, and display mode."""
    return _call("scene_info")


@mcp.tool()
def serp_screenshot(width: int = 1200) -> Image:
    """Capture the current 3D viewport so you can see the model.
    Returns a PNG image. Use after making changes to check the result."""
    result = _bridge.call("screenshot", width=width)
    with open(result["path"], "rb") as f:
        data = f.read()
    os.unlink(result["path"])
    return Image(data=data, format="png")


@mcp.tool()
def serp_create_curve(points: list[list[float]], kind: str = "interp",
                      degree: int = 3, closed: bool = False,
                      name: str = "") -> str:
    """Create a NURBS curve from 3D points [[x,y,z], ...].

    kind: 'interp' (curve passes through the points), 'control' (points are
    control vertices), 'polyline' (straight segments), 'line' (two points).
    """
    return _call("create_curve", points=points, kind=kind, degree=degree,
                 closed=closed, name=name or None)


@mcp.tool()
def serp_create_surface(operation: str, curves: list[str],
                        params: dict | None = None, name: str = "") -> str:
    """Create a surface/solid from existing curves (referenced by name).

    operation:
      'extrude'  params: direction [x,y,z] (default [0,0,1]),
                 distance (default 10), cap (bool, default true - closed
                 profiles become solids)
      'revolve'  params: axis_point, axis_dir, angle (degrees, default 360)
      'loft'     curves: 2+ profiles in order; params: ruled (bool)
      'planar'   flat surface from one closed planar curve
      'sweep'    curves: [profile, rail]
    """
    return _call("create_surface", operation=operation, curves=curves,
                 params=params or {}, name=name or None)


@mcp.tool()
def serp_boolean(operation: str, targets: list[str],
                 tools: list[str]) -> str:
    """Boolean operation between solids: 'union', 'difference' (targets
    minus tools), or 'intersection'. Tools are consumed."""
    return _call("boolean", operation=operation, targets=targets,
                 tools=tools)


@mcp.tool()
def serp_transform(operation: str, targets: list[str],
                   params: dict | None = None) -> str:
    """Transform objects (by name).

    operation/params:
      'move'   offset [dx,dy,dz]
      'copy'   offset [dx,dy,dz]
      'rotate' center [x,y,z], axis [x,y,z] (default Z), angle degrees
      'scale'  center, factor (uniform) or factors [sx,sy,sz]
      'mirror' plane_point, plane_normal, keep_original (bool)
    """
    return _call("transform", operation=operation, targets=targets,
                 params=params or {})


@mcp.tool()
def serp_select(names: list[str] | None = None, kind: str = "",
                layer: str = "", mode: str = "replace") -> str:
    """Select objects by names, kind (curve/surface/solid), or layer name.
    mode: 'replace', 'add', or 'clear' (clear ignores other args)."""
    return _call("select", names=names, kind=kind or None,
                 layer=layer or None, mode=mode)


@mcp.tool()
def serp_command(command: str, inputs: list[str] | None = None) -> str:
    """Run any Serpentine3D command exactly as if typed in the command line,
    supplying its interactive inputs in order.

    Examples:
      command='circle', inputs=['0,0,0', '5']
      command='extrude', inputs=['Curve 01', '', '20', 'Yes']
        (object name(s), then '' to end selection, then distance, then cap)
      command='zoomextents'

    Selection prompts accept object names, 'all', or '' to finish.
    """
    return _call("command", command=command, inputs=inputs or [])


@mcp.tool()
def serp_layers(action: str = "list", name: str = "", new_name: str = "",
                color: list[float] | None = None, visible: bool = True,
                objects: list[str] | None = None) -> str:
    """Manage layers. action: 'list', 'create', 'rename', 'visible',
    'current', 'color' (color as [r,g,b] 0-1), 'assign' (move objects to
    layer), 'delete'."""
    return _call("layers", action=action, name=name or None,
                 new_name=new_name or None, color=color, visible=visible,
                 objects=objects)


@mcp.tool()
def serp_import(path: str) -> str:
    """Import a file into the scene (.serp, .step/.stp, .obj)."""
    return _call("import_file", path=path)


@mcp.tool()
def serp_export(path: str, selected_only: bool = False) -> str:
    """Export the scene (or current selection) to .serp, .step/.stp or
    .obj — format chosen by extension."""
    return _call("export_file", path=path, selected_only=selected_only)


@mcp.tool()
def serp_measure(what: str, targets: list[str] | None = None,
                 points: list[list[float]] | None = None) -> str:
    """Measure geometry. what: 'distance' (needs points=[[..],[..]]),
    'length', 'area', 'volume', 'bbox', 'centroid' (need targets)."""
    return _call("measure", what=what, targets=targets, points=points)


@mcp.tool()
def serp_undo(redo: bool = False) -> str:
    """Undo the last operation (or redo with redo=true)."""
    return _call("redo" if redo else "undo")


@mcp.tool()
def serp_viewport(view: str = "", display_mode: str = "",
                  zoom_extents: bool = False) -> str:
    """Adjust the viewport. view: top/front/right/left/back/bottom/
    perspective. display_mode: wireframe/shaded/ghosted.
    zoom_extents fits all objects in view."""
    return _call("set_viewport", view=view or None,
                 display_mode=display_mode or None,
                 zoom_extents=zoom_extents)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
