"""Native .serp format: JSON scene description with base64 BREP geometry."""

from __future__ import annotations

import base64
import json

FORMAT_VERSION = 1

from ..core import geometry
from ..core.layers import Layer


def save_scene(scene, path: str):
    from ..core.layout import layouts_to_json
    doc = {
        "format": "serpentine",
        "version": FORMAT_VERSION,
        "named_views": scene.named_views,
        "units": scene.units,
        "block_defs": {
            bid: {
                "name": bd["name"],
                "shapes": [base64.b64encode(
                    geometry.shape_to_bytes(s)).decode("ascii")
                    for s in bd["shapes"]],
            }
            for bid, bd in scene.block_defs.items()
        },
        "layouts": layouts_to_json(scene.layouts),
        "layers": [
            {
                "id": layer.id,
                "name": layer.name,
                "color": list(layer.color),
                "visible": layer.visible,
                "locked": layer.locked,
            }
            for layer in scene.layers.all()
        ],
        "current_layer": scene.layers.current_id,
        "objects": [
            {
                "id": obj.id,
                "name": obj.name,
                "layer": obj.layer_id,
                "visible": obj.visible,
                "color": list(obj.color) if obj.color else None,
                "locked": obj.locked,
                "group": obj.group_id,
                "block": obj.block_id,
                "brep": base64.b64encode(
                    geometry.shape_to_bytes(obj.shape)).decode("ascii"),
            }
            for obj in scene.all()
        ],
    }
    with open(path, "w") as f:
        json.dump(doc, f)


def load_scene(scene, path: str):
    """Replace scene contents with the file's contents."""
    with open(path) as f:
        doc = json.load(f)
    if doc.get("format") != "serpentine":
        raise ValueError("Not a Serpentine file")

    scene.clear()
    layers = scene.layers
    id_map = {}
    for ld in doc.get("layers", []):
        if ld["id"] == "default" or ld["name"].lower() == "default":
            layers.rename("default", ld["name"])
            layers.set_color("default", tuple(ld["color"]))
            layers.set_visible("default", ld.get("visible", True))
            id_map[ld["id"]] = "default"
        else:
            layer = layers.create(ld["name"], tuple(ld["color"]))
            layers.set_visible(layer.id, ld.get("visible", True))
            layers.set_locked(layer.id, ld.get("locked", False))
            id_map[ld["id"]] = layer.id

    current = doc.get("current_layer", "default")
    layers.current_id = id_map.get(current, "default")
    scene.named_views = dict(doc.get("named_views", {}))
    scene.units = doc.get("units", scene.units)
    for bid, bd in doc.get("block_defs", {}).items():
        scene.block_defs[bid] = {
            "name": bd["name"],
            "shapes": [geometry.shape_from_bytes(base64.b64decode(s))
                       for s in bd["shapes"]],
        }
    from ..core.layout import layouts_from_json
    scene.layouts = layouts_from_json(doc.get("layouts", []))

    for od in doc.get("objects", []):
        shape = geometry.shape_from_bytes(base64.b64decode(od["brep"]))
        obj = scene.add(shape, name=od["name"],
                        layer_id=id_map.get(od["layer"], "default"))
        updates = {}
        if not od.get("visible", True):
            updates["visible"] = False
        if od.get("color"):
            updates["color"] = tuple(od["color"])
        if od.get("locked"):
            updates["locked"] = True
        if od.get("group"):
            updates["group_id"] = od["group"]
        if od.get("block"):
            updates["block_id"] = od["block"]
        if updates:
            scene.update(obj.id, **updates)
