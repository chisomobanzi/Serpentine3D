"""Native .serp format: JSON scene description with base64 BREP geometry."""

from __future__ import annotations

import base64
import json

FORMAT_VERSION = 1

from ..core import geometry
from ..core.layers import Layer


FORMAT_VERSION = 2


def _write_container(doc: dict, path: str, thumbnail: bytes | None):
    """.serp v2: a zip with document.json, meta.json and a thumbnail."""
    import datetime
    import zipfile
    meta = {
        "format": "serpentine3d",
        "version": FORMAT_VERSION,
        "saved": datetime.datetime.now().isoformat(timespec="seconds"),
        "objects": len(doc.get("objects", [])),
        "layouts": len(doc.get("layouts", [])),
    }
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("meta.json", json.dumps(meta, indent=1))
        z.writestr("document.json", json.dumps(doc))
        if thumbnail:
            z.writestr("thumbnail.png", thumbnail)
    import os
    os.replace(tmp, path)          # atomic: a crash never corrupts the file


def read_meta(path: str) -> dict | None:
    """Container metadata without loading geometry (None for v1 files)."""
    import zipfile
    if not zipfile.is_zipfile(path):
        return None
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("meta.json"))


def read_thumbnail(path: str) -> bytes | None:
    import zipfile
    if not zipfile.is_zipfile(path):
        return None
    with zipfile.ZipFile(path) as z:
        if "thumbnail.png" in z.namelist():
            return z.read("thumbnail.png")
    return None


def save_scene(scene, path: str, thumbnail: bytes | None = None):
    from ..core.layout import layouts_to_json
    doc = {
        "format": "serpentine3d",
        "version": FORMAT_VERSION,
        "named_views": scene.named_views,
        "units": scene.units,
        "image_planes": scene.image_planes,
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
        "annot_styles": {k: dict(v) for k, v in scene.annot_styles.items()},
        "history_records": scene.history_records,
        "layers": [
            {
                "id": layer.id,
                "name": layer.name,
                "color": list(layer.color),
                "visible": layer.visible,
                "locked": layer.locked,
                "lineweight": layer.lineweight,
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
                "material": dict(obj.material) if obj.material else None,
                "clip_plane": (dict(obj.clip_plane) if obj.clip_plane
                               else None),
                "locked": obj.locked,
                "group": obj.group_id,
                "block": obj.block_id,
                "brep": (None if obj.kind == "mesh" else
                         base64.b64encode(geometry.shape_to_bytes(
                             obj.shape)).decode("ascii")),
                "mesh": (_mesh_to_json(obj.shape)
                         if obj.kind == "mesh" else None),
            }
            for obj in scene.all()
        ],
    }
    _write_container(doc, path, thumbnail)


def load_scene(scene, path: str):
    """Replace scene contents with the file's contents (v1 JSON or
    v2 zip container)."""
    import zipfile
    if zipfile.is_zipfile(path):          # v2 container
        with zipfile.ZipFile(path) as z:
            doc = json.loads(z.read("document.json"))
    else:                                 # v1: bare JSON
        with open(path) as f:
            doc = json.load(f)
    _load_doc(scene, doc)


def _load_doc(scene, doc: dict):
    # "serpentine" is the pre-rebrand identifier; those files stay valid
    if doc.get("format") not in ("serpentine3d", "serpentine"):
        raise ValueError("Not a Serpentine3D file")

    scene.clear()
    layers = scene.layers
    id_map = {}
    for ld in doc.get("layers", []):
        if ld["id"] == "default" or ld["name"].lower() == "default":
            layers.rename("default", ld["name"])
            layers.set_color("default", tuple(ld["color"]))
            layers.set_visible("default", ld.get("visible", True))
            layers.set_lineweight("default", ld.get("lineweight", 1.4))
            id_map[ld["id"]] = "default"
        else:
            layer = layers.create(ld["name"], tuple(ld["color"]))
            layers.set_visible(layer.id, ld.get("visible", True))
            layers.set_lineweight(layer.id, ld.get("lineweight", 1.4))
            layers.set_locked(layer.id, ld.get("locked", False))
            id_map[ld["id"]] = layer.id

    current = doc.get("current_layer", "default")
    layers.current_id = id_map.get(current, "default")
    scene.named_views = dict(doc.get("named_views", {}))
    scene.units = doc.get("units", scene.units)
    scene.image_planes = list(doc.get("image_planes", []))
    for bid, bd in doc.get("block_defs", {}).items():
        scene.block_defs[bid] = {
            "name": bd["name"],
            "shapes": [geometry.shape_from_bytes(base64.b64decode(s))
                       for s in bd["shapes"]],
        }
    from ..core.layout import layouts_from_json
    scene.layouts = layouts_from_json(doc.get("layouts", []))
    scene.annot_styles = {k: dict(v) for k, v in
                          doc.get("annot_styles", {}).items()}
    scene.history_records = list(doc.get("history_records", []))

    for od in doc.get("objects", []):
        if od.get("mesh"):
            shape = _mesh_from_json(od["mesh"])
        else:
            shape = geometry.shape_from_bytes(base64.b64decode(od["brep"]))
        obj = scene.add(shape, name=od["name"],
                        layer_id=id_map.get(od["layer"], "default"))
        updates = {}
        if not od.get("visible", True):
            updates["visible"] = False
        if od.get("color"):
            updates["color"] = tuple(od["color"])
        if od.get("material"):
            updates["material"] = dict(od["material"])
        if od.get("clip_plane"):
            updates["clip_plane"] = dict(od["clip_plane"])
        if od.get("locked"):
            updates["locked"] = True
        if od.get("group"):
            updates["group_id"] = od["group"]
        if od.get("block"):
            updates["block_id"] = od["block"]
        if updates:
            scene.update(obj.id, **updates)


def _mesh_to_json(mesh) -> dict:
    import numpy as np
    return {
        "v": base64.b64encode(
            mesh.vertices.astype("<f4").tobytes()).decode("ascii"),
        "t": base64.b64encode(
            mesh.triangles.astype("<u4").tobytes()).decode("ascii"),
    }


def _mesh_from_json(data: dict):
    import numpy as np
    from ..core.mesh import MeshShape
    v = np.frombuffer(base64.b64decode(data["v"]),
                      dtype="<f4").reshape(-1, 3)
    t = np.frombuffer(base64.b64decode(data["t"]),
                      dtype="<u4").reshape(-1, 3)
    return MeshShape(v, t)
