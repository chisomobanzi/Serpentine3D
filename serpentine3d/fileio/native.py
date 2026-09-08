"""Native .serp format: JSON scene description with base64 BREP geometry.

Versions: 1 was bare JSON; 2 is the zip container (document.json,
meta.json, thumbnail.png); 3 adds point clouds, trajectories and a session
record, with the big arrays as binary members under blobs/ — see
protocol/SERP-SESSION-RECORD.md in the Mica repository, which this module
implements the reader and writer of. A document without any of the new
kinds is still written as version 2, so nothing older than this reader
notices.
"""

from __future__ import annotations

import base64
import json

from ..core import geometry
from ..core.layers import Layer

# The newest version this reader understands. Anything newer is refused
# with the version it asks for, never a traceback.
FORMAT_VERSION = 3
# What a document with none of the version-3 kinds is written as.
PLAIN_VERSION = 2
# The Serpentine3D release a version-3 file asks its reader to be.
REQUIRES = "0.8.4"


def _write_container(doc: dict, path: str, thumbnail: bytes | None,
                     blobs: dict | None = None):
    """.serp v2/v3: a zip with document.json, meta.json, a thumbnail and,
    for v3, the point-cloud arrays as binary members."""
    import datetime
    import zipfile
    version = doc.get("version", PLAIN_VERSION)
    meta = {
        "format": "serpentine3d",
        "version": version,
        "saved": datetime.datetime.now().isoformat(timespec="seconds"),
        "objects": len(doc.get("objects", [])),
        "layouts": len(doc.get("layouts", [])),
    }
    if version >= 3:
        clouds = doc.get("pointclouds", [])
        meta["pointclouds"] = len(clouds)
        meta["points"] = int(sum(c.get("count", 0) for c in clouds))
        meta["trajectories"] = len(doc.get("trajectories", []))
        session = doc.get("session")
        if session:
            meta["session"] = {k: session[k] for k in
                               ("id", "engine", "backbone") if k in session}
    tmp = path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("meta.json", json.dumps(meta, indent=1))
        z.writestr("document.json", json.dumps(doc))
        if thumbnail:
            z.writestr("thumbnail.png", thumbnail)
        # Stored, not deflated: float32 coordinates barely compress and a
        # million-point scan would spend seconds finding that out.
        for name, data in (blobs or {}).items():
            z.writestr(name, data, compress_type=zipfile.ZIP_STORED)
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
    clouds = [o for o in scene.all() if o.kind == "pointcloud"]
    trajectories = list(getattr(scene, "trajectories", None) or [])
    session = getattr(scene, "session", None) or None
    blobs = {}
    doc = {
        "format": "serpentine3d",
        "version": PLAIN_VERSION,
        "named_views": scene.named_views,
        "units": scene.units,
        "image_planes": _image_planes_to_json(scene.image_planes, blobs),
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
                "linetype": layer.linetype,
                "print_width": layer.print_width,
                "hatch": layer.hatch,
                "parent": layer.parent,
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
                "annotation": (dict(obj.annotation) if obj.annotation
                               else None),
                "locked": obj.locked,
                "linetype": obj.linetype,
                "draw_order": obj.draw_order,
                "group": obj.group_id,
                "block": obj.block_id,
                "brep": (None if obj.kind == "mesh" else
                         base64.b64encode(geometry.shape_to_bytes(
                             obj.shape)).decode("ascii")),
                "mesh": (_mesh_to_json(obj.shape)
                         if obj.kind == "mesh" else None),
            }
            for obj in scene.all()
            # In their own list below, so a reader older than version 3
            # opens the rest of the drawing with the scan simply absent.
            if obj.kind != "pointcloud"
        ],
    }
    if clouds or trajectories or session:
        doc["version"] = 3
        doc["requires"] = REQUIRES
        doc["pointclouds"] = [_cloud_to_json(obj, blobs) for obj in clouds]
        doc["trajectories"] = trajectories
        if session:
            doc["session"] = session
    _write_container(doc, path, thumbnail, blobs)


def _image_planes_to_json(planes, blobs: dict) -> list[dict]:
    """Move embedded picture bytes out of JSON and into archive members."""
    import hashlib
    import os

    entries = []
    for index, plane in enumerate(planes):
        data = plane.get("image_data")
        entry = {key: value for key, value in plane.items()
                 if key not in ("image_data", "image")}
        if isinstance(data, (bytes, bytearray, memoryview)):
            data = bytes(data)
            suffix = os.path.splitext(str(plane.get("path", "")))[1].lower()
            if suffix not in (".png", ".jpg", ".jpeg", ".bmp", ".gif",
                              ".webp", ".tif", ".tiff"):
                suffix = ".img"
            digest = hashlib.sha256(data).hexdigest()[:16]
            member = f"images/{index:04d}-{digest}{suffix}"
            blobs[member] = data
            entry.pop("path", None)
            entry["image"] = member
        entries.append(entry)
    return entries


def _cloud_to_json(obj, blobs: dict) -> dict:
    """One point cloud's entry, its arrays added to `blobs` by member name.

    Little-endian, contiguous, in the file's own dtypes: what was read is
    what is written."""
    import numpy as np
    cloud = obj.shape
    base = f"blobs/{obj.id}/"
    names = {"xyz": base + "xyz.f32"}
    blobs[names["xyz"]] = np.ascontiguousarray(cloud.xyz, "<f4").tobytes()
    if cloud.rgb is not None:
        names["rgb"] = base + "rgb.u8"
        blobs[names["rgb"]] = np.ascontiguousarray(
            cloud.rgb, np.uint8).tobytes()
    if cloud.conf is not None:
        names["conf"] = base + "conf.f32"
        blobs[names["conf"]] = np.ascontiguousarray(
            cloud.conf, "<f4").tobytes()
    if cloud.level is not None:
        names["level"] = base + "level.u8"
        blobs[names["level"]] = np.ascontiguousarray(
            cloud.level, np.uint8).tobytes()
    mn, mx = cloud.bbox()
    entry = {
        "id": obj.id,
        "name": obj.name,
        "layer": obj.layer_id,
        "visible": obj.visible,
        "count": int(cloud.count),
        "bbox": [list(mn), list(mx)],
        "blobs": names,
    }
    if cloud.provenance:
        entry["provenance"] = dict(cloud.provenance)
    if obj.color:
        entry["color"] = list(obj.color)
    if obj.locked:
        entry["locked"] = True
    return entry


def load_scene(scene, path: str):
    """Replace scene contents with the file's contents (v1 JSON, v2 zip
    container, or v3 container with point-cloud blobs)."""
    import zipfile
    if zipfile.is_zipfile(path):          # v2 / v3 container
        with zipfile.ZipFile(path) as z:
            doc = json.loads(z.read("document.json"))
            _check_version(doc)
            _load_doc(scene, doc, blobs=z)
    else:                                 # v1: bare JSON
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
        _check_version(doc)
        _load_doc(scene, doc)


def _check_version(doc: dict):
    """Refuse a file from the future by name, before touching the scene.

    A newer writer says which release reads it (`requires`); an older
    reader that has none of that vocabulary would otherwise fail somewhere
    inside the load with a traceback about a key it never heard of."""
    try:
        version = int(doc.get("version", 1))
    except (TypeError, ValueError):
        version = 1
    if version > FORMAT_VERSION:
        needs = doc.get("requires") or f"a newer release (file version {version})"
        raise ValueError(f"This file needs Serpentine3D {needs} or newer")


def _load_doc(scene, doc: dict, blobs=None):
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
            layers.set_linetype("default", ld.get("linetype", "Continuous"))
            layers.set_print_width("default", ld.get("print_width", 0.0))
            layers.set_hatch("default", ld.get("hatch", ""))
            id_map[ld["id"]] = "default"
        else:
            layer = layers.create(ld["name"], tuple(ld["color"]))
            layers.set_visible(layer.id, ld.get("visible", True))
            layers.set_lineweight(layer.id, ld.get("lineweight", 1.4))
            layers.set_linetype(layer.id, ld.get("linetype", "Continuous"))
            layers.set_locked(layer.id, ld.get("locked", False))
            layers.set_print_width(layer.id, ld.get("print_width", 0.0))
            layers.set_hatch(layer.id, ld.get("hatch", ""))
            id_map[ld["id"]] = layer.id

    # The file's order is the user's, arrows and all: Default is not
    # nailed to the top, and creating the rest around it would put it back
    # there.
    layers.set_order([id_map[ld["id"]] for ld in doc.get("layers", [])
                      if ld["id"] in id_map])

    # Parents in a second pass: a file lists its layers in the order they
    # were made, which a move can put out of order, so the parent of the
    # first layer read may be the last one made.
    for ld in doc.get("layers", []):
        parent = ld.get("parent")
        if parent:
            layers.set_parent(id_map[ld["id"]], id_map.get(parent))

    current = doc.get("current_layer", "default")
    layers.current_id = id_map.get(current, "default")
    scene.named_views = dict(doc.get("named_views", {}))
    scene.units = doc.get("units", scene.units)
    scene.image_planes = _image_planes_from_json(
        doc.get("image_planes", []), blobs)
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

    object_id_map = {}
    for od in doc.get("objects", []):
        if od.get("mesh"):
            shape = _mesh_from_json(od["mesh"])
        else:
            shape = geometry.shape_from_bytes(base64.b64decode(od["brep"]))
        obj = scene.add(shape, name=od["name"],
                        layer_id=id_map.get(od["layer"], "default"))
        if od.get("id"):
            object_id_map[od["id"]] = obj.id
        updates = {}
        if not od.get("visible", True):
            updates["visible"] = False
        if od.get("color"):
            updates["color"] = tuple(od["color"])
        if od.get("material"):
            updates["material"] = dict(od["material"])
        if od.get("clip_plane"):
            updates["clip_plane"] = dict(od["clip_plane"])
        if od.get("annotation"):
            updates["annotation"] = dict(od["annotation"])
        if od.get("linetype") and od["linetype"] != "ByLayer":
            updates["linetype"] = od["linetype"]
        if od.get("draw_order"):
            updates["draw_order"] = int(od["draw_order"])
        if od.get("locked"):
            updates["locked"] = True
        if od.get("group"):
            updates["group_id"] = od["group"]
        if od.get("block"):
            updates["block_id"] = od["block"]
        if updates:
            scene.update(obj.id, **updates)

    for cd in doc.get("pointclouds", []):
        cloud = _cloud_from_json(cd, blobs)
        if cloud is None:
            continue
        obj = scene.add(cloud, name=cd.get("name") or None,
                        layer_id=id_map.get(cd.get("layer"), "default"))
        if cd.get("id"):
            object_id_map[cd["id"]] = obj.id
        updates = {}
        if not cd.get("visible", True):
            updates["visible"] = False
        if cd.get("color"):
            updates["color"] = tuple(cd["color"])
        if cd.get("locked"):
            updates["locked"] = True
        if updates:
            scene.update(obj.id, **updates)

    # Loading assigns fresh scene IDs. Regeneration and script ownership must
    # follow the loaded objects, rather than retain the file's obsolete IDs.
    for record in scene.history_records:
        record["inputs"] = [object_id_map.get(oid, oid)
                            for oid in record.get("inputs", [])]
        if "output" in record:
            record["output"] = object_id_map.get(record["output"], record["output"])

    scene.trajectories = list(doc.get("trajectories", []))
    scene.session = doc.get("session") or None


def _image_planes_from_json(planes, blobs=None) -> list[dict]:
    """Restore embedded pictures, leaving legacy external paths untouched."""
    restored = []
    for saved_plane in planes:
        plane = dict(saved_plane)
        member = plane.pop("image", None)
        if member and blobs is not None:
            try:
                data = blobs.read(member)
            except (KeyError, OSError, RuntimeError):
                data = None
            if data is not None:
                plane["image_data"] = data
        restored.append(plane)
    return restored


def _cloud_from_json(cd: dict, blobs):
    """A PointCloudShape from its entry and the container's blobs, or None
    when the arrays it names are not in the file."""
    import numpy as np
    from ..core.pointcloud import PointCloudShape
    names = cd.get("blobs") or {}
    if blobs is None or "xyz" not in names:
        return None
    members = set(blobs.namelist())

    def read(key, dtype, cols=None):
        name = names.get(key)
        if not name or name not in members:
            return None
        arr = np.frombuffer(blobs.read(name), dtype=dtype)
        return arr.reshape(-1, cols) if cols else arr

    xyz = read("xyz", "<f4", 3)
    if xyz is None:
        return None
    n = len(xyz)

    def sized(arr):
        # An array of the wrong length is worse than none: it would pair
        # colours with the wrong points from the first row.
        return arr if arr is not None and len(arr) == n else None

    return PointCloudShape(xyz, sized(read("rgb", np.uint8, 3)),
                           sized(read("conf", "<f4")),
                           sized(read("level", np.uint8)),
                           provenance=cd.get("provenance"))


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
