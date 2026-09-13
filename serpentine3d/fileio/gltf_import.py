"""Read static GLB 2.0 meshes without external tools or file/network requests.

Positions are metres in glTF's Y-up frame. Bake the selected scene's node
transforms into independent native meshes, then convert to document units and
Z-up. Textures, animation and skins are not evaluated; meshes use their stored
geometry and base material factors. Required extensions are refused explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path
import struct

import numpy as np

from ..core.mesh import MeshShape
from ..utils.units import convert
from .progress import Progress

_YUP_TO_ZUP = np.array([[1, 0, 0], [0, 0, -1], [0, 1, 0]], float)
_DTYPES = {5120: "i1", 5121: "u1", 5122: "<i2", 5123: "<u2",
           5125: "<u4", 5126: "<f4"}
# Sparse accessors can describe huge implicit zero arrays using a tiny file.
# Bound decoded storage before allocating, including repeated mesh instances.
_MAX_DECODED_BYTES = 512 * 1024 * 1024


def _integer(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"GLB {label} must be an integer >= {minimum}")
    return value


def _mapping(value, label):
    if not isinstance(value, dict):
        raise ValueError(f"GLB {label} must be an object")
    return value


def _array(value, label):
    if not isinstance(value, list):
        raise ValueError(f"GLB {label} must be an array")
    return value


def _ref(doc, collection, index):
    values = _array(doc.get(collection, []), collection)
    index = _integer(index, f"{collection} index")
    if index >= len(values):
        raise ValueError(f"GLB {collection} index {index} is out of range")
    return _mapping(values[index], f"{collection}[{index}]")


def _numbers(value, size, label):
    values = _array(value, label)
    if len(values) != size or any(type(v) not in (int, float) for v in values):
        raise ValueError(f"GLB {label} requires {size} numbers")
    result = np.asarray(values, dtype=float)
    if not np.isfinite(result).all():
        raise ValueError(f"GLB {label} contains nonfinite numbers")
    return result


def _container(path):
    raw = Path(path).read_bytes()
    if len(raw) < 20:
        raise ValueError("GLB container is truncated")
    magic, version, length = struct.unpack_from("<4sII", raw)
    if magic != b"glTF" or version != 2:
        raise ValueError("Expected a binary glTF (GLB) version 2 container")
    if length != len(raw):
        raise ValueError("GLB container length does not match the file")
    offset, chunks = 12, {}
    while offset < length:
        if offset + 8 > length:
            raise ValueError("GLB chunk header is truncated")
        size, kind = struct.unpack_from("<I4s", raw, offset)
        offset += 8
        if size % 4 or offset + size > length:
            raise ValueError("GLB chunk length is invalid or truncated")
        if not chunks and kind != b"JSON":
            raise ValueError("GLB first chunk must contain JSON")
        if kind in (b"JSON", b"BIN\0"):
            if kind in chunks:
                raise ValueError("GLB contains a duplicate JSON or binary chunk")
            chunks[kind] = memoryview(raw)[offset:offset + size]
        offset += size
    try:
        doc = _mapping(json.loads(bytes(chunks[b"JSON"])), "document")
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError("GLB JSON metadata is invalid") from exc
    asset = _mapping(doc.get("asset"), "asset")
    if asset.get("version") != "2.0" or asset.get("minVersion", "2.0") != "2.0":
        raise ValueError("Only glTF 2.0 assets are supported")
    required = _array(doc.get("extensionsRequired", []), "extensionsRequired")
    if required:
        raise ValueError("GLB requires unsupported extension(s): "
                         + ", ".join(str(name) for name in required))
    buffers = _array(doc.get("buffers", []), "buffers")
    if len(buffers) != 1:
        raise ValueError("GLB mesh import requires one embedded binary buffer")
    buffer = _mapping(buffers[0], "buffer")
    if "uri" in buffer:
        raise ValueError("GLB external buffers are not supported; embed mesh data in the GLB")
    declared = _integer(buffer.get("byteLength"), "buffer byteLength")
    binary = chunks.get(b"BIN\0", memoryview(b""))
    if not declared <= len(binary) <= declared + 3:
        raise ValueError("GLB binary buffer length is invalid")
    return doc, binary[:declared]


class _Accessors:
    """Decode only mesh attributes, checking bounds before NumPy views/arrays."""

    def __init__(self, doc, binary):
        self.doc, self.binary = doc, binary
        self.cache = {}
        self.decoded_bytes = 0

    def reserve(self, size):
        self.decoded_bytes += size
        if self.decoded_bytes > _MAX_DECODED_BYTES:
            raise ValueError("GLB decoded mesh data exceeds the 512 MiB import limit")

    def _read(self, view_index, byte_offset, count, components, dtype, *, sparse=False):
        view = _ref(self.doc, "bufferViews", view_index)
        if _integer(view.get("buffer"), "buffer index") != 0:
            raise ValueError("GLB bufferView references an unavailable buffer")
        start = _integer(view.get("byteOffset", 0), "bufferView byteOffset")
        length = _integer(view.get("byteLength"), "bufferView byteLength")
        if start + length > len(self.binary):
            raise ValueError("GLB bufferView is outside binary buffer bounds")
        offset = _integer(byte_offset, "accessor byteOffset")
        width = dtype.itemsize * components
        stride = _integer(view.get("byteStride", width), "accessor byteStride", 1)
        if stride < width or stride % dtype.itemsize or (sparse and "byteStride" in view):
            raise ValueError("GLB accessor has an invalid byte stride")
        if (start + offset) % dtype.itemsize:
            raise ValueError("GLB accessor offset is not component-aligned")
        end = offset + (count - 1) * stride + width if count else offset
        if end > length:
            raise ValueError("GLB accessor is outside bufferView bounds")
        return np.ndarray((count, components), dtype=dtype, buffer=self.binary,
                          offset=start + offset, strides=(stride, dtype.itemsize))

    def read(self, index, semantic):
        accessor = _ref(self.doc, "accessors", index)
        component = _integer(accessor.get("componentType"), "accessor componentType")
        expected = "SCALAR" if semantic == "indices" else "VEC3"
        allowed = (5121, 5123, 5125) if semantic == "indices" else (5126,)
        if accessor.get("type") != expected or component not in allowed:
            raise ValueError(f"GLB {semantic} accessor must be {expected} with "
                             f"componentType {allowed}")
        if accessor.get("normalized", False) is not False:
            raise ValueError(f"GLB {semantic} accessor cannot be normalized")
        if index in self.cache:
            return self.cache[index]
        count = _integer(accessor.get("count"), "accessor count", 1)
        components = 1 if expected == "SCALAR" else 3
        dtype = np.dtype(_DTYPES[component])
        self.reserve(count * components * 8)
        if "bufferView" in accessor:
            data = self._read(accessor["bufferView"], accessor.get("byteOffset", 0),
                              count, components, dtype).copy()
        else:
            if accessor.get("byteOffset", 0) != 0:
                raise ValueError("GLB accessor without a bufferView cannot have an offset")
            data = np.zeros((count, components), dtype=dtype)
        if "sparse" in accessor:
            sparse = _mapping(accessor["sparse"], "sparse accessor")
            n = _integer(sparse.get("count"), "sparse count", 1)
            if n > count:
                raise ValueError("GLB sparse count exceeds accessor count")
            indices = _mapping(sparse.get("indices"), "sparse indices")
            values = _mapping(sparse.get("values"), "sparse values")
            kind = _integer(indices.get("componentType"), "sparse index componentType")
            if kind not in (5121, 5123, 5125):
                raise ValueError("GLB sparse indices require an unsigned integer componentType")
            ids = self._read(indices.get("bufferView"), indices.get("byteOffset", 0),
                             n, 1, np.dtype(_DTYPES[kind]), sparse=True).ravel()
            if ids[-1] >= count or np.any(ids[1:] <= ids[:-1]):
                raise ValueError("GLB sparse indices must increase and stay within accessor range")
            data[ids] = self._read(values.get("bufferView"), values.get("byteOffset", 0),
                                   n, components, dtype, sparse=True)
        if not np.isfinite(data).all():
            raise ValueError(f"GLB {semantic} accessor contains nonfinite data")
        self.cache[index] = data
        return data


def _node_matrix(node):
    if "matrix" in node:
        if any(key in node for key in ("translation", "rotation", "scale")):
            raise ValueError("GLB node cannot combine matrix and TRS transforms")
        matrix = _numbers(node["matrix"], 16, "node matrix").reshape(4, 4).T
        if not np.allclose(matrix[3], (0, 0, 0, 1)):
            raise ValueError("GLB node matrix must be affine")
        return matrix
    t = _numbers(node.get("translation", [0, 0, 0]), 3, "node translation")
    s = _numbers(node.get("scale", [1, 1, 1]), 3, "node scale")
    q = _numbers(node.get("rotation", [0, 0, 0, 1]), 4, "node rotation")
    length = np.linalg.norm(q)
    if not np.isfinite(length) or length == 0:
        raise ValueError("GLB node rotation must be a nonzero quaternion")
    x, y, z, w = q / length
    rotation = np.array([
        [1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
        [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
        [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]])
    matrix = np.eye(4)
    matrix[:3, :3] = rotation * s
    matrix[:3, 3] = t
    return matrix


def _scene_nodes(doc):
    """Yield unique selected-scene nodes and world transforms, without recursion."""
    nodes = _array(doc.get("nodes", []), "nodes")
    scenes = _array(doc.get("scenes", []), "scenes")
    if scenes:
        scene = _ref(doc, "scenes", doc.get("scene", 0))
        roots = _array(scene.get("nodes", []), "scene nodes")
    else:
        # Exporters may omit a default scene. Use unparented nodes in that case.
        children = set()
        for node in nodes:
            for child in _array(_mapping(node, "node").get("children", []), "node children"):
                _ref(doc, "nodes", child)
                children.add(child)
        roots = [i for i in range(len(nodes)) if i not in children]
        if nodes and not roots:
            raise ValueError("GLB node graph contains a cycle")
    stack = [(index, np.eye(4)) for index in reversed(roots)]
    visited = set()
    while stack:
        index, parent = stack.pop()
        node = _ref(doc, "nodes", index)
        if index in visited:
            raise ValueError("GLB node graph contains a cycle or multiple parents")
        visited.add(index)
        world = parent @ _node_matrix(node)
        if not np.isfinite(world).all():
            raise ValueError("GLB node transform contains nonfinite values")
        yield node, world
        children = _array(node.get("children", []), "node children")
        stack.extend((child, world) for child in reversed(children))


def _material(doc, primitive):
    source = (_ref(doc, "materials", primitive["material"])
              if "material" in primitive else {})
    pbr = _mapping(source.get("pbrMetallicRoughness", {}), "PBR material")
    rgba = _numbers(pbr.get("baseColorFactor", [1, 1, 1, 1]), 4, "baseColorFactor")
    factors = _numbers([pbr.get("metallicFactor", 1), pbr.get("roughnessFactor", 1)],
                       2, "material factors")
    if np.any((rgba < 0) | (rgba > 1)) or np.any((factors < 0) | (factors > 1)):
        raise ValueError("GLB material factors must be between zero and one")
    mode = source.get("alphaMode", "OPAQUE")
    if mode not in ("OPAQUE", "MASK", "BLEND"):
        raise ValueError("GLB material has an invalid alphaMode")
    return {"color": tuple(rgba[:3]), "metallic": float(factors[0]),
            "roughness": float(factors[1]),
            "opacity": float(rgba[3]) if mode == "BLEND" else 1.0}


def _triangles(primitive, accessors, vertex_count):
    mode = _integer(primitive.get("mode", 4), "primitive mode")
    if mode not in (4, 5, 6):
        raise ValueError("GLB mesh import supports triangles, triangle strips and fans; "
                         "point/line primitives are not supported")
    if "indices" in primitive:
        indices = accessors.read(primitive["indices"], "indices").ravel()
    else:
        indices = np.arange(vertex_count, dtype=np.uint32)
    if len(indices) < 3 or int(indices.max()) >= vertex_count:
        raise ValueError("GLB triangle indices are empty or outside the vertex range")
    if mode == 4:
        if len(indices) % 3:
            raise ValueError("GLB triangle index count must be divisible by three")
        return indices.reshape(-1, 3).copy()
    if mode == 5:
        triangles = np.column_stack((indices[:-2], indices[1:-1], indices[2:]))
        triangles[1::2, :2] = triangles[1::2, 1::-1]
        return triangles
    return np.column_stack((np.full(len(indices)-2, indices[0], dtype=np.uint32),
                            indices[1:-1], indices[2:]))


def import_glb(path, *, units="mm", progress=None):
    """Return validated (name, MeshShape, material) items; never mutate a scene."""
    report = progress if isinstance(progress, Progress) else Progress(progress)
    doc, binary = _container(path)
    report(0.1, "Reading GLB meshes…")
    accessors = _Accessors(doc, binary)
    basis = _YUP_TO_ZUP * convert(1.0, "m", units)
    result = []
    node_count = max(len(_array(doc.get("nodes", []), "nodes")), 1)
    for done, (node, world) in enumerate(_scene_nodes(doc), 1):
        report(0.1 + 0.8 * done / node_count, "Reading GLB meshes…")
        if "mesh" not in node:
            continue
        mesh = _ref(doc, "meshes", node["mesh"])
        primitives = _array(mesh.get("primitives"), "mesh primitives")
        for number, primitive in enumerate(primitives, 1):
            primitive = _mapping(primitive, "mesh primitive")
            attributes = _mapping(primitive.get("attributes"), "primitive attributes")
            if "POSITION" not in attributes:
                raise ValueError("GLB primitive has no POSITION accessor; compressed meshes "
                                 "must be exported without compression")
            vertices = accessors.read(attributes["POSITION"], "POSITION")
            triangles = _triangles(primitive, accessors, len(vertices))
            accessors.reserve(vertices.size * 8 + triangles.size * 4)
            linear = basis @ world[:3, :3]
            with np.errstate(over="ignore", invalid="ignore"):
                transformed = vertices @ linear.T + basis @ world[:3, 3]
            if not np.isfinite(transformed).all():
                raise ValueError("GLB transformed positions contain nonfinite values")
            if np.linalg.det(linear) < 0:
                triangles = triangles[:, [0, 2, 1]]
            normals = None
            if "NORMAL" in attributes:
                source_normals = accessors.read(attributes["NORMAL"], "NORMAL")
                if len(source_normals) != len(vertices):
                    raise ValueError("GLB NORMAL and POSITION accessor counts differ")
                try:
                    normals = source_normals @ np.linalg.inv(linear)
                    lengths = np.linalg.norm(normals, axis=1, keepdims=True)
                    if not np.isfinite(lengths).all() or np.any(lengths == 0):
                        normals = None
                    else:
                        normals /= lengths
                except np.linalg.LinAlgError:
                    pass  # A flattened instance gets normals from its triangles.
            name = node.get("name") or mesh.get("name") or Path(path).stem
            if not isinstance(name, str):
                raise ValueError("GLB node/mesh name must be text")
            if len(primitives) > 1:
                name = f"{name} {number:02d}"
            result.append((name, MeshShape(transformed, triangles, normals),
                           _material(doc, primitive)))
    if not result:
        raise ValueError("GLB selected scene contains no triangle meshes")
    report(1.0, "GLB meshes ready")
    return result
