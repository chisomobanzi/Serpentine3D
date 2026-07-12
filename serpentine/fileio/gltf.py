"""Binary glTF (.glb) export — hand-written, no dependencies.

One mesh node per object, tessellated, with per-object base colours.
Y-up conversion (glTF convention) from Serpentine's Z-up."""

from __future__ import annotations

import json
import struct

import numpy as np

from ..core.tessellate import tessellate

# Z-up -> Y-up: (x, y, z) -> (x, z, -y)
_ZUP_TO_YUP = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], np.float32)


def export_glb(scene, path: str, only_ids: list | None = None):
    objs = scene.all()
    if only_ids:
        objs = [o for o in objs if o.id in only_ids]

    buffers = bytearray()
    accessors, buffer_views, meshes, nodes, materials = [], [], [], [], []

    def add_view(data: bytes, target: int | None) -> int:
        # 4-byte alignment
        while len(buffers) % 4:
            buffers.append(0)
        offset = len(buffers)
        buffers.extend(data)
        view = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
        if target:
            view["target"] = target
        buffer_views.append(view)
        return len(buffer_views) - 1

    for obj in objs:
        mesh = tessellate(obj.shape)
        if not mesh.has_faces:
            continue
        verts = (mesh.vertices @ _ZUP_TO_YUP.T).astype(np.float32)
        norms = (mesh.normals @ _ZUP_TO_YUP.T).astype(np.float32)
        idx = mesh.triangles.astype(np.uint32).ravel()

        v_view = add_view(verts.tobytes(), 34962)
        n_view = add_view(norms.tobytes(), 34962)
        i_view = add_view(idx.tobytes(), 34963)

        accessors.append({
            "bufferView": v_view, "componentType": 5126,
            "count": len(verts), "type": "VEC3",
            "min": [float(v) for v in verts.min(axis=0)],
            "max": [float(v) for v in verts.max(axis=0)],
        })
        v_acc = len(accessors) - 1
        accessors.append({"bufferView": n_view, "componentType": 5126,
                          "count": len(norms), "type": "VEC3"})
        n_acc = len(accessors) - 1
        accessors.append({"bufferView": i_view, "componentType": 5125,
                          "count": int(len(idx)), "type": "SCALAR"})
        i_acc = len(accessors) - 1

        color = scene.color_of(obj)
        m = obj.material or {}
        opacity = float(m.get("opacity", 1.0))
        mat = {
            "name": f"{obj.name} material",
            "pbrMetallicRoughness": {
                "baseColorFactor": [color[0], color[1], color[2], opacity],
                "metallicFactor": float(m.get("metallic", 0.0)),
                "roughnessFactor": float(m.get("roughness", 0.8)),
            },
        }
        if opacity < 1.0:
            mat["alphaMode"] = "BLEND"
        materials.append(mat)
        meshes.append({
            "name": obj.name,
            "primitives": [{
                "attributes": {"POSITION": v_acc, "NORMAL": n_acc},
                "indices": i_acc,
                "material": len(materials) - 1,
            }],
        })
        nodes.append({"name": obj.name, "mesh": len(meshes) - 1})

    doc = {
        "asset": {"version": "2.0", "generator": "Serpentine"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes))),
                    "name": "Serpentine scene"}],
        "nodes": nodes,
        "meshes": meshes,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(buffers)}],
    }

    json_bytes = json.dumps(doc, separators=(",", ":")).encode()
    while len(json_bytes) % 4:
        json_bytes += b" "
    bin_bytes = bytes(buffers)
    while len(bin_bytes) % 4:
        bin_bytes += b"\x00"

    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    with open(path, "wb") as f:
        f.write(struct.pack("<III", 0x46546C67, 2, total))
        f.write(struct.pack("<II", len(json_bytes), 0x4E4F534A))
        f.write(json_bytes)
        f.write(struct.pack("<II", len(bin_bytes), 0x004E4942))
        f.write(bin_bytes)
