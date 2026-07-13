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
        '    defaultPrim = "Serpentine3D"',
        ")",
        "",
        'def Xform "Serpentine3D"',
        "{",
    ]
    used = set()
    mat_blocks = []
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
        m = obj.material or {}
        lines.extend([
            f'    def Mesh "{name}" (',
            f'        prepend apiSchemas = ["MaterialBindingAPI"]',
            "    )",
            "    {",
            f"        point3f[] points = [{pts}]",
            f"        int[] faceVertexCounts = [{counts}]",
            f"        int[] faceVertexIndices = [{indices}]",
            f"        color3f[] primvars:displayColor = "
            f"[({color[0]:.4g}, {color[1]:.4g}, {color[2]:.4g})]",
            '        uniform token subdivisionScheme = "none"',
            f"        rel material:binding = "
            f"</Serpentine3D/Materials/{name}_mat>",
            "    }",
        ])
        mat_blocks.append((name, color, m))
    if mat_blocks:
        lines.append('    def Scope "Materials"')
        lines.append("    {")
        for name, color, m in mat_blocks:
            lines.extend([
                f'        def Material "{name}_mat"',
                "        {",
                "            token outputs:surface.connect = "
                f"</Serpentine3D/Materials/{name}_mat/pbr.outputs:surface>",
                f'            def Shader "pbr"',
                "            {",
                '                uniform token info:id = '
                '"UsdPreviewSurface"',
                f"                color3f inputs:diffuseColor = "
                f"({color[0]:.4g}, {color[1]:.4g}, {color[2]:.4g})",
                f"                float inputs:metallic = "
                f"{float(m.get('metallic', 0.0)):.3g}",
                f"                float inputs:roughness = "
                f"{float(m.get('roughness', 0.8)):.3g}",
                f"                float inputs:opacity = "
                f"{float(m.get('opacity', 1.0)):.3g}",
                "                token outputs:surface",
                "            }",
                "        }",
            ])
        lines.append("    }")
    lines.append("}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
