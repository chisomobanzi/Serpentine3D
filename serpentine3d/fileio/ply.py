"""PLY point clouds: the exchange format every scanner and every
point-cloud tool reads.

Reader and writer of our own, so there is no dependency to add: the
format is a header naming typed columns followed by rows, either as text
or as packed binary, and numpy reads both in one call. Only the vertex
element is used. A PLY carrying faces is a mesh in another format's
clothes and is refused with a pointer to the formats that carry meshes.
"""

from __future__ import annotations

import numpy as np

from ..core.pointcloud import PointCloudShape

_TYPES = {
    "char": "i1", "int8": "i1", "uchar": "u1", "uint8": "u1",
    "short": "i2", "int16": "i2", "ushort": "u2", "uint16": "u2",
    "int": "i4", "int32": "i4", "uint": "u4", "uint32": "u4",
    "float": "f4", "float32": "f4", "double": "f8", "float64": "f8",
}

# The names the world uses for the same columns.
_RED = ("red", "r", "diffuse_red")
_GREEN = ("green", "g", "diffuse_green")
_BLUE = ("blue", "b", "diffuse_blue")
_CONF = ("confidence", "conf", "quality", "intensity")
_LEVEL = ("level", "lod")


def _parse_header(f) -> tuple[str, list, list]:
    """(format, elements, header_lines): elements are
    (name, count, [(prop, dtype)]) with a list property recorded as
    ("list", count_dtype, item_dtype, name)."""
    magic = f.readline()
    if magic.strip() != b"ply":
        raise ValueError("Not a PLY file")
    fmt = None
    elements = []
    while True:
        line = f.readline()
        if not line:
            raise ValueError("PLY header never ends")
        words = line.decode("ascii", "replace").split()
        if not words:
            continue
        if words[0] == "format":
            fmt = words[1]
        elif words[0] == "element":
            elements.append((words[1], int(words[2]), []))
        elif words[0] == "property":
            if words[1] == "list":
                elements[-1][2].append(("list", _TYPES[words[2]],
                                        _TYPES[words[3]], words[4]))
            else:
                elements[-1][2].append((words[2], _TYPES[words[1]]))
        elif words[0] == "end_header":
            break
    if fmt not in ("ascii", "binary_little_endian", "binary_big_endian"):
        raise ValueError(f"Unknown PLY format {fmt!r}")
    return fmt, elements


def _pick(names: dict, wanted) -> str | None:
    for w in wanted:
        if w in names:
            return w
    return None


def import_ply(path: str) -> list:
    """Returns [(name, PointCloudShape)] — one cloud from the vertex
    element."""
    import os
    with open(path, "rb") as f:
        fmt, elements = _parse_header(f)
        vertex = next((e for e in elements if e[0] == "vertex"), None)
        if vertex is None:
            raise ValueError("PLY has no vertex element")
        faces = next((e for e in elements if e[0] == "face"), None)
        if faces is not None and faces[1] > 0:
            raise ValueError("This PLY carries faces: Serpentine3D reads "
                             "PLY as point clouds. Export the mesh as OBJ "
                             "or STL instead.")
        if any(p[0] == "list" for p in vertex[2]):
            raise ValueError("PLY vertex element with list properties is "
                             "not supported")
        if elements[0] is not vertex:
            # Only vertex-first files, which is every one a scanner writes.
            raise ValueError("PLY vertex element must come first")
        n = vertex[1]
        if fmt == "ascii":
            text = f.read().decode("ascii", "replace")
            cols = len(vertex[2])
            raw = np.fromstring(text, sep=" ", dtype=np.float64)
            if len(raw) < n * cols:
                raise ValueError("PLY has fewer vertices than its header says")
            table = raw[:n * cols].reshape(n, cols)
            columns = {name: table[:, i]
                       for i, (name, _) in enumerate(vertex[2])}
        else:
            endian = "<" if fmt == "binary_little_endian" else ">"
            dtype = np.dtype([(name, endian + t) for name, t in vertex[2]])
            data = f.read(dtype.itemsize * n)
            if len(data) < dtype.itemsize * n:
                raise ValueError("PLY has fewer vertices than its header says")
            rows = np.frombuffer(data, dtype=dtype, count=n)
            columns = {name: rows[name] for name, _ in vertex[2]}

    for axis in ("x", "y", "z"):
        if axis not in columns:
            raise ValueError(f"PLY vertices have no {axis} column")
    xyz = np.column_stack([columns["x"], columns["y"], columns["z"]])
    r, g, b = _pick(columns, _RED), _pick(columns, _GREEN), _pick(columns, _BLUE)
    rgb = None
    if r and g and b:
        rgb = np.column_stack([columns[r], columns[g], columns[b]])
        if rgb.dtype.kind == "f":          # 0..1 floats, as some tools write
            rgb = np.clip(rgb * 255.0, 0, 255)
        rgb = rgb.astype(np.uint8)
    conf_name = _pick(columns, _CONF)
    conf = None
    if conf_name:
        conf = columns[conf_name].astype(np.float32)
        if conf.dtype.kind != "f" or (len(conf) and conf.max() > 1.0):
            hi = float(conf.max()) if len(conf) else 1.0
            conf = conf / (hi or 1.0)      # bring 0..255 or 0..65535 to 0..1
    level_name = _pick(columns, _LEVEL)
    level = None if not level_name else \
        np.clip(columns[level_name], 0, 255).astype(np.uint8)
    name = os.path.splitext(os.path.basename(path))[0]
    return [(name, PointCloudShape(xyz, rgb, conf, level))]


def export_ply(items, path: str):
    """Write point clouds as one binary little-endian PLY.

    `items` is [(name, PointCloudShape)]; several are concatenated, since
    a PLY holds one vertex element. Colour, confidence and level columns
    are written when every cloud carries them."""
    clouds = [c for _, c in items if isinstance(c, PointCloudShape)]
    if not clouds:
        raise ValueError("Nothing to export: PLY carries point clouds only")
    xyz = np.concatenate([c.xyz for c in clouds]).astype("<f4")
    n = len(xyz)
    fields = [("x", "<f4"), ("y", "<f4"), ("z", "<f4")]
    props = ["property float x", "property float y", "property float z"]
    rgb = conf = level = None
    if all(c.rgb is not None for c in clouds):
        rgb = np.concatenate([c.rgb for c in clouds]).astype(np.uint8)
        fields += [("red", "u1"), ("green", "u1"), ("blue", "u1")]
        props += ["property uchar red", "property uchar green",
                  "property uchar blue"]
    if all(c.conf is not None for c in clouds):
        conf = np.concatenate([c.conf for c in clouds]).astype("<f4")
        fields.append(("confidence", "<f4"))
        props.append("property float confidence")
    if all(c.level is not None for c in clouds):
        level = np.concatenate([c.level for c in clouds]).astype(np.uint8)
        fields.append(("level", "u1"))
        props.append("property uchar level")
    rows = np.empty(n, dtype=np.dtype(fields))
    rows["x"], rows["y"], rows["z"] = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    if rgb is not None:
        rows["red"], rows["green"], rows["blue"] = rgb[:, 0], rgb[:, 1], rgb[:, 2]
    if conf is not None:
        rows["confidence"] = conf
    if level is not None:
        rows["level"] = level
    header = "\n".join(["ply", "format binary_little_endian 1.0",
                        "comment Serpentine3D point cloud",
                        f"element vertex {n}", *props, "end_header"]) + "\n"
    with open(path, "wb") as f:
        f.write(header.encode("ascii"))
        f.write(rows.tobytes())
