"""Number Slider, Boolean Toggle, Panel and Geometry Pipeline."""

from __future__ import annotations

import math
import re

from . import COMPONENTS, Component, Result
from ..kinds import HydraError, Port
from ..tree import Tree


MAX_DECIMALS = 6


COMPONENTS["toggle"] = Component(
    "toggle", "Boolean Toggle", "Input",
    outputs=(Port("Boolean", "boolean", description="True or False"),),
    icon="toggle", params={"value": False},
    description="True or False; double-click it to switch")


# what each type a Geometry Pipeline can take is, among the model's kinds
PIPE_TYPES = {"point": ("point",), "curve": ("curve",),
              "brep": ("surface", "solid"), "mesh": ("mesh",)}


def piped(scene, params) -> list:
    """The model's objects a Geometry Pipeline takes: on its layer, the
    layers under it counted, or on any with none chosen; and of its
    types."""
    kinds = {k for t in params.get("types", ()) for k in PIPE_TYPES.get(t, ())}
    path = params.get("layer")
    layers = None
    if path is not None:
        layer = scene.layers.find_by_path(path)
        if layer is None:
            return []
        layers = scene.layers.with_descendants([layer.id])
    return [obj for obj in scene.all()
            if obj.kind in kinds and not getattr(obj, "clip_plane", None)
            and (layers is None or obj.layer_id in layers)]


def _pipeline(graph, node, scene, results) -> Result:
    found = piped(scene, node.params)
    result = Result({"Geometry": Tree.of([o.shape for o in found])})
    path = node.params.get("layer")
    if path is not None and scene.layers.find_by_path(path) is None:
        result.status = "warning"
        result.message = f"There is no layer {path} in the model"
    elif not node.params.get("types"):
        result.status = "warning"
        result.message = "Right-click and choose the types to take"
    return result


COMPONENTS["pipeline"] = Component(
    "pipeline", "Geometry Pipeline", "Input",
    outputs=(Port("Geometry", "geometry",
                  description="Everything in the model that fits"),),
    icon="pipeline", params={"layer": None, "types": list(PIPE_TYPES)},
    made=_pipeline,
    description="Every object in the model on a layer, of the types "
                "chosen, kept up to date as the model changes")


def panel_lines(text: str) -> list:
    """A panel's typed text as items, a line each, blank lines left out."""
    return [line for line in text.splitlines() if line.strip()]


def _panel(graph, node, scene, results) -> Result:
    """What comes in, handed on as it is; with no wire, the text."""
    port = node.component.inputs[0]
    tree, wired = graph.input_values(node.id, port, results)
    if wired:
        return Result({"Out": tree})
    return Result({"Out": Tree.of(panel_lines(node.params.get("text", "")))})


COMPONENTS["panel"] = Component(
    "panel", "Panel", "Input",
    inputs=(Port("In", "any", access="list", label="Data",
                 description="Whatever is to be shown"),),
    outputs=(Port("Out", "any", label="Data",
                  description="What comes in, or the text typed, a line an "
                              "item"),),
    icon="panel", params={"text": ""}, made=_panel,
    description="Shows what comes in, as Rhino's panel does; with nothing "
                "wired, holds text typed into it, a line an item")


def panel_from_text(text: str):
    """A panel's settings from what was typed into the search after a
    quotation mark, "Hallo or "12; None if it does not start with one."""
    if not text.startswith(('"', "\u201c", "\u201e")):
        return None
    content = text[1:]
    if content.endswith(('"', "\u201d", "\u201c")):
        content = content[:-1]
    return {"text": content}


COMPONENTS["slider"] = Component(
    "slider", "Number Slider", "Input",
    outputs=(Port("Number", "number", description="The slider's number"),),
    icon="sliders", description="A number, set by dragging the slider",
    params={"value": 5.0, "min": 0.0, "max": 10.0, "decimals": 2})


def set_slider(params: dict, value: float):
    """Put a slider at `value`, kept in its range and to its decimals."""
    value = min(max(float(value), params["min"]), params["max"])
    params["value"] = round(value, params["decimals"])


def set_range(params: dict, low: float, high: float):
    if not low < high:
        raise HydraError("The minimum has to be below the maximum")
    params["min"], params["max"] = float(low), float(high)
    set_slider(params, params["value"])


def set_decimals(params: dict, decimals: int):
    decimals = min(max(int(decimals), 0), MAX_DECIMALS)
    params["decimals"] = decimals
    params["min"] = round(params["min"], decimals)
    params["max"] = round(params["max"], decimals)
    if params["min"] >= params["max"]:
        params["max"] = params["min"] + 10 ** -decimals
    set_slider(params, params["value"])


_NUMBER = r"\s*(-?\d+(?:[.,]\d*)?|-?[.,]\d+)\s*"


_RANGE = re.compile(_NUMBER + r"(?:-|–|\.\.|to)" + _NUMBER + r"$")


def type_into_slider(params: dict, text: str) -> str:
    """What is typed straight into a slider: one number sets its value, two
    with a dash between, as in 0.0-12, set its range and decimal places.
    Says which it was, "value" or "range"; ValueError if it was neither."""
    match = _RANGE.match(text)
    if match is not None:
        (low, a), (high, b) = (parse_number(t) for t in match.groups())
        set_range(params, low, high)
        set_decimals(params, max(a, b))
        return "range"
    value, _places = parse_number(text)
    # a value past either end widens the range to reach it
    params["min"] = min(params["min"], value)
    params["max"] = max(params["max"], value)
    set_slider(params, value)
    return "value"


def slider_from_text(text: str):
    """The settings of a slider typed as a number or a range, 7.25 or
    0.0-12, to as many decimal places as typed; None if it is neither."""
    params = dict(COMPONENTS["slider"].params)
    try:
        kind = type_into_slider(params, text)
    except (ValueError, HydraError):
        return None
    if not all(math.isfinite(params[k]) for k in ("value", "min", "max")):
        return None
    if kind == "value":
        value, places = parse_number(text)
        set_decimals(params, places)
        set_slider(params, value)
    return params


def parse_number(text: str) -> tuple[float, int]:
    """A typed number and how many decimal places it was typed to. A
    comma counts as the decimal point, as it is typed in much of Europe."""
    text = text.strip().replace(",", ".")
    value = float(text)
    places = len(text.split(".", 1)[1]) if "." in text else 0
    return value, min(places, MAX_DECIMALS)
