"""A Rhino mesh's vertices and faces, read straight from its .3dm.

rhino3dm hands a mesh over one vertex and one face at a time, about 5us
each, and has no bulk accessor; its own Encode() is slower still. A .3dm
written by Rhino 5 or later keeps each mesh as openNURBS writes it
(ON_Mesh::Write, version 3.x): the faces as a packed array of 1, 2 or 4
byte indices, the single-precision vertices as a compressed buffer. So
they are read from there, in one go, for an object in the file's object
table by its index, which is its index in rhino3dm's object list.

Anything this cannot follow, an older file or a record laid out some other
way, answers None, and the caller reads the mesh as before.
"""
from __future__ import annotations

import os
import struct
import threading
import zlib

import numpy as np

_SHORT = 0x80000000                    # TCODE_SHORT: no body follows
_OBJECT_TABLE = 0x10000013
_OBJECT_RECORD = 0x20008070
_END_OF_TABLE = 0xFFFFFFFF
_CLASS = 0x27FFA                       # TCODE_OPENNURBS_CLASS
_CLASS_UUID = 0x2FFFB
_CLASS_DATA = 0x2FFFC
_ANONYMOUS = 0x40008000                # TCODE_ANONYMOUS_CHUNK, CRC'd
# ON_Mesh's class id as the file writes it
_MESH = bytes.fromhex("e4d4d74e47e9d311bfe50010830122f0")
_HEAD = 12 + 12 + 32 + 12              # a record's type, class, id, data

_SCANS: dict = {}
_LOCK = threading.Lock()


def object_count(path: str) -> int | None:
    """How many records the file's object table holds, or None."""
    scan = _records(path)
    return None if scan is None else scan[1]


def mesh_arrays_at(path: str, index: int):
    """(vertices (N, 3) float, faces (M, 4) int64) of the mesh at `index`
    in the .3dm at `path`, or None."""
    scan = _records(path)
    if scan is None or index not in scan[0]:
        return None
    offset, size = scan[0][index]
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            body = f.read(size)
    except OSError:
        return None
    return mesh_arrays(body)


def mesh_arrays(body: bytes):
    """(vertices, faces) from an ON_Mesh's class data, or None."""
    try:
        if not body or body[0] >> 4 != 3:
            return None
        vcount, fcount = struct.unpack_from("<ii", body, 1)
        # version, counts, packed texture and surface domains, surface
        # scale, vertex, normal and texture boxes, and whether it is closed
        at = 1 + 8 + 32 + 32 + 16 + 24 + 24 + 16 + 4
        for _ in range(5):         # mesh parameters and four curvature stats
            present = body[at]
            at += 1
            if present:
                at += 12 + struct.unpack_from("<Q", body, at + 4)[0]
        width = struct.unpack_from("<i", body, at)[0]
        at += 4
        kind = {1: np.uint8, 2: np.uint16, 4: np.int32}.get(width)
        if kind is None:
            return None
        faces = np.frombuffer(body, kind, fcount * 4, at).reshape(-1, 4)
        at += fcount * 4 * width
        if vcount == 0:
            return np.zeros((0, 3)), faces.astype(np.int64)
        nbytes = struct.unpack_from("<I", body, at)[0]
        if nbytes != vcount * 12:
            return None
        method = body[at + 8]
        at += 9
        if method == 0:
            raw = body[at:at + nbytes]
        else:
            code, size = struct.unpack_from("<IQ", body, at)
            if code != _ANONYMOUS:
                return None
            raw = zlib.decompress(body[at + 12:at + 12 + size - 4])
        verts = np.frombuffer(raw, "<f4", vcount * 3).reshape(-1, 3)
        return verts.astype(float), faces.astype(np.int64)
    except (IndexError, struct.error, zlib.error, ValueError):
        return None


def _records(path: str):
    """({object index: (offset, size) of its mesh class data}, how many
    object records there are), for the file as it is now; scanned once and
    kept while the file is unchanged."""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    key = (os.path.abspath(path), stat.st_size, stat.st_mtime_ns)
    with _LOCK:
        if key not in _SCANS:
            _SCANS.clear()                  # one file at a time is plenty
            _SCANS[key] = _scan(path)
        return _SCANS[key]


def _scan(path: str):
    """Walk the object table's records, reading only their first bytes."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if not head.startswith(b"3D Geometry File Format ") or \
                    int(head[24:32]) < 50:
                return None               # 4-byte chunk lengths before V5
            while True:
                hdr = f.read(12)
                if len(hdr) < 12:
                    return None
                code, size = struct.unpack("<IQ", hdr)
                if code == _OBJECT_TABLE:
                    end = f.tell() + size
                    break
                if not code & _SHORT:
                    f.seek(size, 1)
            found, index = {}, 0
            while f.tell() + 12 <= end:
                at = f.tell()
                code, size = struct.unpack("<IQ", f.read(12))
                if code == _END_OF_TABLE or code & _SHORT:
                    if code == _END_OF_TABLE:
                        break
                    continue
                if code == _OBJECT_RECORD:
                    data = _mesh_data(f.read(min(size, _HEAD)), at + 12)
                    if data is not None:
                        found[index] = data
                    index += 1
                f.seek(at + 12 + size)
            return found, index
    except (OSError, ValueError, struct.error):
        return None


def _mesh_data(head: bytes, start: int):
    """(offset, size) of a record's class data if it is a mesh."""
    at = 0
    while at + 12 <= len(head):
        code, size = struct.unpack_from("<IQ", head, at)
        if code == _CLASS:
            at += 12
            break
        at += 12 if code & _SHORT else 12 + size
    else:
        return None
    code, size = struct.unpack_from("<IQ", head, at)
    if code != _CLASS_UUID or head[at + 12:at + 28] != _MESH:
        return None
    at += 12 + size
    if at + 12 > len(head):
        return None
    code, size = struct.unpack_from("<IQ", head, at)
    if code != _CLASS_DATA:
        return None
    return start + at + 12, size - 4     # the body, less its CRC
