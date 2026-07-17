"""Tool definitions the assistant can call, dispatched onto SerpApi.

The same surface the MCP server exposes, expressed as Anthropic
Messages-API tool schemas. `dispatch` runs one call and returns either a
JSON string or an ImageResult (screenshots go back to the model as an
actual image so it can see the viewport).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from ..api import ApiError


@dataclass
class ImageResult:
    data: bytes                     # PNG
    note: str = ""


def _s(**props):
    """Shorthand for an object schema."""
    required = props.pop("_required", [])
    return {"type": "object", "properties": props, "required": required}


_VEC = {"type": "array", "items": {"type": "number"},
        "minItems": 3, "maxItems": 3}
_PTS = {"type": "array", "items": _VEC}
_NAMES = {"type": "array", "items": {"type": "string"}}

TOOLS: list[dict] = [
    {
        "name": "scene_info",
        "description": (
            "Get the current scene: objects (name/kind/layer/bbox), layers, "
            "selection, bounds, and display mode. Call this first when you "
            "need to know what exists or what the user is referring to."),
        "input_schema": _s(),
    },
    {
        "name": "screenshot",
        "description": (
            "Capture the current 3D viewport as an image so you can see the "
            "model. Use after building or changing geometry to visually "
            "verify the result before declaring it done."),
        "input_schema": _s(width={"type": "integer", "default": 1024}),
    },
    {
        "name": "create_curve",
        "description": (
            "Create a NURBS curve from 3D points [[x,y,z], ...]. kind: "
            "'interp' (passes through points), 'control' (points are CVs), "
            "'polyline' (straight segments), 'line' (two points)."),
        "input_schema": _s(points=_PTS,
                           kind={"type": "string", "enum": [
                               "interp", "control", "polyline", "line"]},
                           degree={"type": "integer", "default": 3},
                           closed={"type": "boolean", "default": False},
                           name={"type": "string"},
                           _required=["points"]),
    },
    {
        "name": "create_surface",
        "description": (
            "Create a surface/solid from existing curves (by name).\n"
            "operation:\n"
            "  'extrude'  params: direction [x,y,z] (default [0,0,1]), "
            "distance (default 10), cap (bool, default true — closed "
            "profiles become solids)\n"
            "  'revolve'  params: axis_point, axis_dir, angle (deg, 360)\n"
            "  'loft'     curves: 2+ profiles in order; params: ruled\n"
            "  'planar'   flat surface from one closed planar curve\n"
            "  'sweep'    curves: [profile, rail]"),
        "input_schema": _s(operation={"type": "string", "enum": [
                               "extrude", "revolve", "loft", "planar",
                               "sweep"]},
                           curves=_NAMES,
                           params={"type": "object"},
                           name={"type": "string"},
                           _required=["operation", "curves"]),
    },
    {
        "name": "boolean",
        "description": (
            "Boolean between solids: 'union', 'difference' (targets minus "
            "tools) or 'intersection'. Tool objects are consumed."),
        "input_schema": _s(operation={"type": "string", "enum": [
                               "union", "difference", "intersection"]},
                           targets=_NAMES, tools=_NAMES,
                           _required=["operation", "targets", "tools"]),
    },
    {
        "name": "transform",
        "description": (
            "Transform objects (by name). operation/params:\n"
            "  'move'   offset [dx,dy,dz]\n"
            "  'copy'   offset [dx,dy,dz]\n"
            "  'rotate' center, axis (default Z), angle degrees\n"
            "  'scale'  center, factor (uniform) or factors [sx,sy,sz]\n"
            "  'mirror' plane_point, plane_normal, keep_original"),
        "input_schema": _s(operation={"type": "string", "enum": [
                               "move", "copy", "rotate", "scale", "mirror"]},
                           targets=_NAMES, params={"type": "object"},
                           _required=["operation", "targets"]),
    },
    {
        "name": "run_command",
        "description": (
            "Run any Serpentine3D command exactly as if typed on its command "
            "line, supplying interactive inputs in order. Use for anything "
            "the structured tools don't cover — the full command list is in "
            "your instructions.\n"
            "Examples:\n"
            "  command='circle', inputs=['0,0,0', '5']\n"
            "  command='filletedge', inputs=['Box', '', '2']\n"
            "    (selection, '' ends selection, then radius)\n"
            "  command='zoomextents'\n"
            "Selection prompts accept object names, 'all', or '' to finish. "
            "Points are 'x,y,z'. Option prompts accept the option word."),
        "input_schema": _s(command={"type": "string"},
                           inputs={"type": "array",
                                   "items": {"type": "string"}},
                           _required=["command"]),
    },
    {
        "name": "select",
        "description": (
            "Select objects by names, kind (curve/surface/solid) or layer. "
            "mode: 'replace', 'add', or 'clear'."),
        "input_schema": _s(names=_NAMES, kind={"type": "string"},
                           layer={"type": "string"},
                           mode={"type": "string", "default": "replace"}),
    },
    {
        "name": "layers",
        "description": (
            "Manage layers. action: 'list', 'create', 'rename', 'visible', "
            "'current', 'color' ([r,g,b] 0-1), 'assign' (move objects to a "
            "layer), 'delete'."),
        "input_schema": _s(action={"type": "string"},
                           name={"type": "string"},
                           new_name={"type": "string"},
                           color={"type": "array",
                                  "items": {"type": "number"}},
                           visible={"type": "boolean"},
                           objects=_NAMES,
                           _required=["action"]),
    },
    {
        "name": "measure",
        "description": (
            "Measure geometry. what: 'distance' (points=[[..],[..]]), "
            "'length', 'area', 'volume', 'bbox', 'centroid' (targets)."),
        "input_schema": _s(what={"type": "string"},
                           targets=_NAMES, points=_PTS,
                           _required=["what"]),
    },
    {
        "name": "viewport",
        "description": (
            "Adjust the view. view: top/front/right/left/back/bottom/"
            "perspective. display_mode: wireframe/shaded/ghosted/rendered. "
            "zoom_extents fits everything in view."),
        "input_schema": _s(view={"type": "string"},
                           display_mode={"type": "string"},
                           zoom_extents={"type": "boolean"}),
    },
    {
        "name": "undo",
        "description": "Undo the last operation (redo=true to redo).",
        "input_schema": _s(redo={"type": "boolean", "default": False}),
    },
]


def dispatch(api, name: str, args: dict) -> str | ImageResult:
    """Execute one tool call against a SerpApi. Raises ApiError on failure."""
    args = dict(args or {})
    if name == "scene_info":
        return _j(api.scene_info())
    if name == "screenshot":
        result = api.screenshot(width=int(args.get("width", 1024)))
        with open(result["path"], "rb") as f:
            data = f.read()
        os.unlink(result["path"])
        return ImageResult(data, f"{result['width']}x{result['height']}")
    if name == "create_curve":
        return _j(api.create_curve(
            points=args["points"], kind=args.get("kind", "interp"),
            degree=int(args.get("degree", 3)),
            closed=bool(args.get("closed", False)),
            name=args.get("name") or None))
    if name == "create_surface":
        return _j(api.create_surface(
            operation=args["operation"], curves=args["curves"],
            params=args.get("params") or {},
            name=args.get("name") or None))
    if name == "boolean":
        return _j(api.boolean(operation=args["operation"],
                              targets=args["targets"],
                              tools=args["tools"]))
    if name == "transform":
        return _j(api.transform(operation=args["operation"],
                                targets=args["targets"],
                                params=args.get("params") or {}))
    if name == "run_command":
        return _j(api.command(command=args["command"],
                              inputs=args.get("inputs") or []))
    if name == "select":
        return _j(api.select(names=args.get("names"),
                             kind=args.get("kind") or None,
                             layer=args.get("layer") or None,
                             mode=args.get("mode", "replace")))
    if name == "layers":
        return _j(api.layers(action=args.get("action", "list"),
                             name=args.get("name"),
                             new_name=args.get("new_name"),
                             color=args.get("color"),
                             visible=args.get("visible"),
                             objects=args.get("objects")))
    if name == "measure":
        return _j(api.measure(what=args["what"],
                              targets=args.get("targets"),
                              points=args.get("points")))
    if name == "viewport":
        return _j(api.set_viewport(
            view=args.get("view") or None,
            display_mode=args.get("display_mode") or None,
            zoom_extents=bool(args.get("zoom_extents", False))))
    if name == "undo":
        return _j(api.redo() if args.get("redo") else api.undo())
    raise ApiError(f"Unknown tool '{name}'")


def _j(result) -> str:
    return json.dumps(result, indent=1, default=str)


def summarize_call(name: str, args: dict) -> str:
    """One-line human description of a tool call, for the chat panel."""
    args = args or {}
    if name == "run_command":
        inp = args.get("inputs") or []
        joined = " ".join(str(i) for i in inp if str(i))
        return f"{args.get('command', '?')} {joined}".strip()
    if name == "create_curve":
        return f"curve ({args.get('kind', 'interp')}, " \
               f"{len(args.get('points', []))} pts)"
    if name == "create_surface":
        return f"{args.get('operation', '?')} {', '.join(args.get('curves', []))}"
    if name in ("boolean", "transform"):
        return f"{args.get('operation', '?')} " \
               f"{', '.join(args.get('targets', []))}"
    if name == "screenshot":
        return "looking at the viewport"
    if name == "scene_info":
        return "reading the scene"
    if name == "viewport":
        parts = [args.get("view"), args.get("display_mode"),
                 "zoom extents" if args.get("zoom_extents") else None]
        return "view: " + ", ".join(p for p in parts if p)
    return name
