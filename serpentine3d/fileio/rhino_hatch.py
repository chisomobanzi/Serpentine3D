"""The hatch pattern table of a .3dm file (#92).

rhino3dm reads a hatch's plane, pattern index, scale, rotation and base
point, and gives its region as a Brep, but has no word for the patterns
those indexes point at. They are read here from the file itself, so a
hatch comes in drawn with the lines Rhino draws it with.

A .3dm file is a run of chunks: a type code, a length (or, for a short
chunk, a value), then the body. The hatch pattern table is one top-level
chunk holding a record per pattern, and each record holds the pattern as
an openNURBS object, in the layout ON_HatchPattern::Write gives it:
version 6 and later as model component attributes (id, index, name), the
fill type, the description and the lines; version 5 as the same things
written one after another. Every chunk says how long it is, so whatever
this does not read is stepped over rather than misread.
"""

from __future__ import annotations

import math
import struct

from ..core.hatch_patterns import HatchPattern, PatternLine

TCODE_SHORT = 0x80000000
TCODE_CRC = 0x8000
TCODE_ENDOFFILE = 0x00007FFF
TCODE_HATCHPATTERN_TABLE = 0x10000000 | 0x0022
TCODE_HATCHPATTERN_RECORD = 0x20000000 | TCODE_CRC | 0x0077
TCODE_OPENNURBS_CLASS = 0x00020000 | 0x7FFA
TCODE_OPENNURBS_CLASS_DATA = 0x00020000 | TCODE_CRC | 0x7FFC

FILL_SOLID, FILL_LINES = 0, 1


class _Reader:
    """Little-endian values off a byte string, from `at`."""

    def __init__(self, data: bytes, at: int = 0, end: int | None = None,
                 wide: bool = True):
        self.data = data
        self.at = at
        self.end = len(data) if end is None else end
        self.wide = wide            # 8-byte chunk lengths, version 5 and on

    def take(self, fmt: str):
        size = struct.calcsize(fmt)
        if self.at + size > self.end:
            raise ValueError("read past the end of a chunk")
        values = struct.unpack_from("<" + fmt, self.data, self.at)
        self.at += size
        return values

    def int(self) -> int:
        return self.take("i")[0]

    def uint(self) -> int:
        return self.take("I")[0]

    def double(self) -> float:
        return self.take("d")[0]

    def byte(self) -> int:
        return self.take("B")[0]

    def string(self) -> str:
        """An ON_wString: its UTF-16 length, null and all, then the text."""
        count = self.uint()
        if count == 0:
            return ""
        raw = self.data[self.at:self.at + 2 * count]
        self.at += 2 * count
        return raw.decode("utf-16-le", errors="replace").rstrip("\x00")

    def doubles(self) -> tuple:
        count = self.int()
        return self.take(f"{count}d") if count > 0 else ()

    def chunk(self):
        """(type code, a reader over its body) for the chunk here, and the
        reader moved past it; a short chunk's body is empty."""
        tcode = self.uint()
        value = self.take("q" if self.wide else "i")[0]
        if tcode & TCODE_SHORT:
            return tcode, _Reader(self.data, self.at, self.at, self.wide)
        start, stop = self.at, self.at + value
        if stop > self.end or value < 0:
            raise ValueError("a chunk runs past the one it is in")
        self.at = stop
        # a chunk with a CRC has its four bytes at the end of the body
        body_end = stop - 4 if tcode & TCODE_CRC else stop
        return tcode, _Reader(self.data, start, body_end, self.wide)


def read_hatch_patterns(path: str) -> dict:
    """{index: HatchPattern} for the hatch pattern table of a .3dm file,
    by the index a hatch's PatternIndex names. A file with no table, or
    one written before version 5, gives an empty dict."""
    with open(path, "rb") as fh:
        data = fh.read()
    if not data.startswith(b"3D Geometry File Format "):
        return {}
    try:
        version = int(data[24:32].decode("ascii").strip())
    except ValueError:
        return {}
    if version < 5:
        return {}
    top = _Reader(data, 32, wide=version >= 5)
    patterns = {}
    while top.at < top.end:
        try:
            tcode, body = top.chunk()
        except (ValueError, struct.error):
            break
        if tcode == TCODE_ENDOFFILE:
            break
        if tcode != TCODE_HATCHPATTERN_TABLE:
            continue
        order = 0
        while body.at < body.end:
            try:
                rtcode, record = body.chunk()
            except (ValueError, struct.error):
                break
            if rtcode != TCODE_HATCHPATTERN_RECORD:
                continue
            try:
                index, pattern = _record(record, version)
            except (ValueError, struct.error, UnicodeError):
                index, pattern = None, None
            if pattern is not None:
                patterns[order if index is None or index < 0
                         else index] = pattern
            order += 1
        break
    return patterns


def _record(record: _Reader, version: int):
    """(index, HatchPattern) out of a hatch pattern record."""
    while record.at < record.end:
        tcode, klass = record.chunk()
        if tcode != TCODE_OPENNURBS_CLASS:
            continue
        while klass.at < klass.end:
            ctcode, data = klass.chunk()
            if ctcode == TCODE_OPENNURBS_CLASS_DATA:
                return (_pattern_v6(data) if version >= 60
                        else _pattern_v5(data))
    return None, None


def _pattern_v6(r: _Reader):
    _tcode, body = r.chunk()                 # the pattern's own chunk
    body.int(), body.int()                   # its version
    _tcode, attrs = body.chunk()             # id, index, name
    attrs.int(), attrs.int()
    bits = attrs.uint()
    index, name = None, ""
    if bits & 0x01:
        attrs.take("16s")
    if bits & 0x02:
        attrs.take("16s")
    if bits & 0x04:
        index = attrs.int()
    if bits & 0x08:
        name = attrs.string()
    fill = body.uint()
    description = body.string()
    _tcode, block = body.chunk()
    count = block.int()
    lines = []
    for _ in range(max(count, 0)):
        _tcode, ln = block.chunk()
        ln.int(), ln.int()
        lines.append(_line(ln))
    return index, _pattern(name, description, fill, lines)


def _pattern_v5(r: _Reader):
    r.byte()                                 # chunk version
    index = r.int()
    fill = r.uint()
    name = r.string()
    description = r.string()
    lines = []
    if fill == FILL_LINES:
        for _ in range(max(r.int(), 0)):
            r.byte()
            lines.append(_line(r))
    return index, _pattern(name, description, fill, lines)


def _line(r: _Reader) -> PatternLine:
    angle = r.double()
    base = r.take("dd")
    offset = r.take("dd")
    dashes = r.doubles()
    return PatternLine(math.degrees(angle), tuple(base), tuple(offset),
                       tuple(dashes))


def _pattern(name, description, fill, lines):
    if not name:
        return None
    if fill == FILL_LINES and lines:
        return HatchPattern(name, description, tuple(lines))
    # Solid, and a gradient, which is drawn here as the solid it starts as
    return HatchPattern(name, description, solid=True)
