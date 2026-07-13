"""Wavefront OBJ import/export.

Export tessellates BREP shapes to meshes. Import produces mesh-backed
scene entries by building OCCT faces from triangles (kept lightweight:
one sewn shell per OBJ object).
"""

from __future__ import annotations

import numpy as np

from ..core import geometry, occ
from ..core.tessellate import tessellate


def export_obj(named_shapes: list, path: str):
    """named_shapes: [(name, TopoDS_Shape)] or [(name, shape, color)]"""
    import os
    lines = ["# Serpentine3D OBJ export"]
    mtl_lines = []
    mtl_path = os.path.splitext(path)[0] + ".mtl"
    has_colors = any(len(t) > 2 for t in named_shapes)
    if has_colors:
        lines.append(f"mtllib {os.path.basename(mtl_path)}")
    v_offset = 1
    for entry in named_shapes:
        name, shape = entry[0], entry[1]
        color = entry[2] if len(entry) > 2 else None
        mesh = tessellate(shape)
        if not mesh.has_faces:
            continue
        safe = name.replace(" ", "_")
        lines.append(f"o {safe}")
        if color is not None:
            mtl_lines.extend([
                f"newmtl {safe}_mat",
                f"Kd {color[0]:.4g} {color[1]:.4g} {color[2]:.4g}",
                "Ka 0 0 0", "Ks 0.05 0.05 0.05", "Ns 32", "",
            ])
            lines.append(f"usemtl {safe}_mat")
        for v in mesh.vertices:
            lines.append(f"v {v[0]:.8g} {v[1]:.8g} {v[2]:.8g}")
        for n in mesh.normals:
            lines.append(f"vn {n[0]:.6g} {n[1]:.6g} {n[2]:.6g}")
        for t in mesh.triangles:
            a, b, c = (int(i) + v_offset for i in t)
            lines.append(f"f {a}//{a} {b}//{b} {c}//{c}")
        v_offset += len(mesh.vertices)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")
    if has_colors and mtl_lines:
        with open(mtl_path, "w") as f:
            f.write("\n".join(mtl_lines) + "\n")


def import_obj(path: str, as_mesh: bool = True) -> list:
    """Returns [(name, shape)] — native MeshShape objects by default
    (instant), or sewn BREP shells with as_mesh=False."""
    verts: list = []
    groups: dict[str, list] = {}
    current = "obj"
    with open(path) as f:
        for line in f:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == "v":
                verts.append([float(x) for x in parts[1:4]])
            elif parts[0] in ("o", "g") and len(parts) > 1:
                current = parts[1]
            elif parts[0] == "f":
                idx = []
                for token in parts[1:]:
                    i = int(token.split("/")[0])
                    idx.append(i - 1 if i > 0 else len(verts) + i)
                # fan-triangulate polygons
                for k in range(1, len(idx) - 1):
                    groups.setdefault(current, []).append(
                        (idx[0], idx[k], idx[k + 1]))

    va = np.asarray(verts, float)
    out = []
    for name, tris in groups.items():
        if as_mesh:
            from ..core.mesh import MeshShape
            # compact vertices used by this group
            t = np.asarray(tris, np.int64)
            used = np.unique(t)
            remap = np.zeros(len(va), np.int64)
            remap[used] = np.arange(len(used))
            out.append((name, MeshShape(va[used], remap[t])))
        else:
            shell = _shell_from_triangles(va, tris)
            if shell is not None:
                out.append((name, shell))
    return out


def _shell_from_triangles(verts: np.ndarray, tris: list) -> object | None:
    from ..core.occ import (
        BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace,
        BRepBuilderAPI_Sewing, gp_Pnt,
    )
    sew = BRepBuilderAPI_Sewing(1e-6)
    count = 0
    for (a, b, c) in tris:
        pa, pb, pc = (gp_Pnt(*verts[i]) for i in (a, b, c))
        if pa.Distance(pb) < 1e-12 or pb.Distance(pc) < 1e-12 \
                or pa.Distance(pc) < 1e-12:
            continue
        poly = BRepBuilderAPI_MakePolygon(pa, pb, pc, True)
        if not poly.IsDone():
            continue
        face = BRepBuilderAPI_MakeFace(poly.Wire(), True)
        if face.IsDone():
            sew.Add(face.Face())
            count += 1
    if count == 0:
        return None
    sew.Perform()
    return sew.SewedShape()
