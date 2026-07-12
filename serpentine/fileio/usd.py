"""USD export as plain-text .usda — no dependencies.

One UsdGeomMesh per object under a root Xform, with display colours.
USD is Y-up by default; we declare Z-up so coordinates pass through."""

from __future__ import annotations

import re

from ..core.tessellate import tessellate


def _safe(name: str) -> str:
    out = re.sub(r"[^A-Za-z0-9_]", "_", name)
    if not out or out[0].isdigit():
        out = "_" + out
    return out


def export_usda(scene, path: str, only_ids: list | None = None):
    objs = scene.all()
    if only_ids:
        objs = [o for o in objs if o.id in only_ids]

    lines = [
        "#usda 1.0",
        "(",
        '    upAxis = "Z"',
        '    metersPerUnit = 0.001',
        '    defaultPrim = "Serpentine"',
        ")",
        "",
        'def Xform "Serpentine"',
        "{",
    ]
    used = set()
    for obj in objs:
        mesh = tessellate(obj.shape)
        if not mesh.has_faces:
            continue
        name = _safe(obj.name)
        while name in used:
            name += "_"
        used.add(name)
        color = scene.color_of(obj)
        pts = ", ".join(f"({v[0]:.6g}, {v[1]:.6g}, {v[2]:.6g})"
                        for v in mesh.vertices)
        counts = ", ".join("3" for _ in mesh.triangles)
        indices = ", ".join(str(int(i)) for t in mesh.triangles for i in t)
        lines.extend([
            f'    def Mesh "{name}"',
            "    {",
            f"        point3f[] points = [{pts}]",
            f"        int[] faceVertexCounts = [{counts}]",
            f"        int[] faceVertexIndices = [{indices}]",
            f"        color3f[] primvars:displayColor = "
            f"[({color[0]:.4g}, {color[1]:.4g}, {color[2]:.4g})]",
            '        uniform token subdivisionScheme = "none"',
            "    }",
        ])
    lines.append("}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
