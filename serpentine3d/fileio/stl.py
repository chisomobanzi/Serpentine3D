"""STL import/export (mesh-based) — the 3D-printing interchange format.

Serpentine3D is a BREP modeller; STL is a flat triangle soup, so this mirrors
the OBJ path: export tessellates each shape and merges every triangle into one
STL (slicers want a single watertight mesh, not per-object structure); import
parses binary *and* ASCII STL and welds the loose triangles back into an
indexed MeshShape.

Export writes **binary** STL by default — it is what slicers expect and is far
smaller than ASCII. `binary=False` writes ASCII for human-readable output.
"""

from __future__ import annotations

import os
import struct

import numpy as np

from ..core.mesh import MeshShape
from ..core.tessellate import tessellate

_HEADER = b"Serpentine3D binary STL"


def export_stl(named_shapes: list, path: str, *, binary: bool = True):
    """named_shapes: [(name, shape)] or [(name, shape, color)] — colour is
    ignored (STL stores none). All shapes are tessellated and merged into one
    triangle soup."""
    blocks = []
    for entry in named_shapes:
        shape = entry[1]
        mesh = tessellate(shape)
        if not mesh.has_faces:
            continue
        v = np.asarray(mesh.vertices, np.float64)
        t = np.asarray(mesh.triangles, np.int64)
        if len(t):
            blocks.append(v[t])                     # (T, 3, 3)
    if blocks:
        tris = np.concatenate(blocks, axis=0)       # (M, 3, 3)
    else:
        tris = np.zeros((0, 3, 3), np.float64)

    normals = _facet_normals(tris)
    # drop degenerate (zero-area) triangles: they print as nothing and some
    # slicers choke on them.
    keep = np.any(normals != 0.0, axis=1) if len(normals) else np.zeros(0, bool)
    tris, normals = tris[keep], normals[keep]

    name = os.path.splitext(os.path.basename(path))[0] or "Serpentine3D"
    if binary:
        _write_binary(tris, normals, path)
    else:
        _write_ascii(tris, normals, path, name)


def import_stl(path: str) -> list:
    """Returns [(name, MeshShape)] — a single welded mesh."""
    with open(path, "rb") as f:
        data = f.read()
    if _is_binary(data):
        tris = _read_binary(data)
    else:
        tris = _read_ascii(data.decode("utf-8", "replace"))
    name = os.path.splitext(os.path.basename(path))[0] or "stl"
    verts, faces = _weld(tris)
    return [(name, MeshShape(verts, faces))]


# --------------------------------------------------------------------- helpers

def _facet_normals(tris: np.ndarray) -> np.ndarray:
    """Unit face normals from triangle winding; (M,3), zero for degenerates."""
    if not len(tris):
        return np.zeros((0, 3), np.float64)
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return np.divide(n, ln, out=np.zeros_like(n), where=ln > 0)


def _weld(tris: np.ndarray):
    """Collapse a (M,3,3) triangle soup into (unique verts, (M,3) indices)."""
    if not len(tris):
        return np.zeros((0, 3), np.float64), np.zeros((0, 3), np.int64)
    flat = tris.reshape(-1, 3)
    verts, inv = np.unique(flat, axis=0, return_inverse=True)
    return verts, inv.reshape(-1, 3)


def _is_binary(data: bytes) -> bool:
    """Binary STL is exactly 84 + 50*ntri bytes; the size check is the robust
    way to disambiguate (an ASCII file's size never matches that formula, and
    some binary files start with the word 'solid')."""
    if len(data) < 84:
        return False
    ntri = struct.unpack("<I", data[80:84])[0]
    return len(data) == 84 + ntri * 50


def _write_binary(tris: np.ndarray, normals: np.ndarray, path: str):
    n = len(tris)
    floats = np.empty((n, 12), np.float32)
    floats[:, 0:3] = normals
    floats[:, 3:6] = tris[:, 0]
    floats[:, 6:9] = tris[:, 1]
    floats[:, 9:12] = tris[:, 2]
    rows = np.zeros((n, 50), np.uint8)
    rows[:, 0:48] = floats.view(np.uint8).reshape(n, 48)   # [48:50] attr = 0
    with open(path, "wb") as f:
        f.write(_HEADER.ljust(80, b"\0")[:80])
        f.write(struct.pack("<I", n))
        f.write(rows.tobytes())


def _write_ascii(tris: np.ndarray, normals: np.ndarray, path: str, name: str):
    out = [f"solid {name}"]
    for (a, b, c), nrm in zip(tris, normals):
        out.append(f"  facet normal {nrm[0]:.6e} {nrm[1]:.6e} {nrm[2]:.6e}")
        out.append("    outer loop")
        for v in (a, b, c):
            out.append(f"      vertex {v[0]:.6e} {v[1]:.6e} {v[2]:.6e}")
        out.append("    endloop")
        out.append("  endfacet")
    out.append(f"endsolid {name}")
    with open(path, "w") as f:
        f.write("\n".join(out) + "\n")


def _read_binary(data: bytes) -> np.ndarray:
    ntri = struct.unpack("<I", data[80:84])[0]
    raw = np.frombuffer(data, np.uint8, count=ntri * 50, offset=84)
    raw = raw.reshape(ntri, 50)
    floats = np.ascontiguousarray(raw[:, 0:48]).view(np.float32).reshape(ntri, 12)
    return floats[:, 3:12].reshape(ntri, 3, 3).astype(np.float64)


def _read_ascii(text: str) -> np.ndarray:
    verts = []
    for line in text.splitlines():
        parts = line.split()
        if parts and parts[0].lower() == "vertex" and len(parts) >= 4:
            verts.append([float(parts[1]), float(parts[2]), float(parts[3])])
    n = len(verts) - (len(verts) % 3)
    return np.asarray(verts[:n], np.float64).reshape(-1, 3, 3)
