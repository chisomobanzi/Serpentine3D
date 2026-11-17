"""End the installer's version strings where their text ends.

Inno Setup's setup stub carries a version resource whose strings are 60-space
placeholders, and ISCC writes each VersionInfo* value over the start of one
without shortening it, so ProductName comes out as "Serpentine3D" followed by
48 spaces. Explorer hides that; SignPath reads it, and its metadata check
rejects the installer.

This rewrites each string in place: the trailing spaces become terminators
and the declared length shrinks to match. Nothing in the file moves, which
matters because setup.exe finds its payload by offset. ISCC patches the same
resource the same way, outside anything setup.exe checksums.

build-installer.ps1 runs it on the installer right after ISCC:
    python trim_version_info.py Output\\Serpentine3D-Setup-x86_64.exe
"""
import struct
import sys
from pathlib import Path

RT_VERSION = 16


def _version_resources(data: bytes) -> list[tuple[int, int]]:
    """(file offset, size) of every RT_VERSION resource in a PE file."""
    if len(data) < 0x40 or data[:2] != b"MZ":
        raise ValueError("not a PE file")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("not a PE file")
    sections, optional_size = struct.unpack_from("<H12xH", data, pe + 6)
    optional = pe + 24
    magic = struct.unpack_from("<H", data, optional)[0]
    if magic not in (0x10B, 0x20B):
        raise ValueError("unknown PE optional header")
    directories = optional + (96 if magic == 0x10B else 112)
    rsrc_rva = struct.unpack_from("<I", data, directories + 2 * 8)[0]
    if not rsrc_rva:
        raise ValueError("the file has no resources")

    table = [struct.unpack_from("<IIII", data, optional + optional_size + 40 * i + 8)
             for i in range(sections)]

    def offset(rva: int) -> int:
        for vsize, va, rawsize, raw in table:
            if va <= rva < va + max(vsize, rawsize):
                return raw + rva - va
        raise ValueError(f"RVA {rva:#x} is in no section")

    base = offset(rsrc_rva)

    def entries(at: int):
        named, ids = struct.unpack_from("<HH", data, base + at + 12)
        for i in range(named + ids):
            yield struct.unpack_from("<II", data, base + at + 16 + 8 * i)

    def leaves(target: int):
        if target & 0x80000000:
            for _, child in entries(target & 0x7FFFFFFF):
                yield from leaves(child)
        else:
            rva, size = struct.unpack_from("<II", data, base + target)
            yield offset(rva), size

    found = [leaf for name, target in entries(0) if name == RT_VERSION
             for leaf in leaves(target)]
    if not found:
        raise ValueError("the file has no version resource")
    return found


def _strings(data: bytes):
    """Every string in every version resource's StringFileInfo, as
    (key, text, declared length, header offset, text offset).

    The text runs to its terminator, the way Windows hands it out."""
    for start, _ in _version_resources(data):
        def align(pos: int) -> int:
            return start + (pos - start + 3) // 4 * 4

        def node(pos: int):
            """(key, end of node, declared value length, value offset)"""
            length, declared, _ = struct.unpack_from("<HHH", data, pos)
            if length < 6:
                raise ValueError("malformed version resource")
            end = pos + 6
            while data[end:end + 2] != b"\0\0":
                end += 2
            key = data[pos + 6:end].decode("utf-16-le")
            return key, pos + length, declared, align(end + 2)

        def children(pos: int, end: int):
            while pos < end:
                child = node(pos)
                yield pos, child
                pos = align(child[1])

        _, root_end, fixed_size, fixed_at = node(start)
        for _, (key, end, _, first) in children(align(fixed_at + fixed_size), root_end):
            if key != "StringFileInfo":
                continue
            for _, (_, table_end, _, first_string) in children(first, end):
                for pos, (name, string_end, declared, text_at) in children(
                        first_string, table_end):
                    text = data[text_at:string_end]
                    stop = next((i for i in range(0, len(text) - 1, 2)
                                 if text[i:i + 2] == b"\0\0"), len(text) // 2 * 2)
                    yield name, text[:stop].decode("utf-16-le"), declared, pos, text_at


def string_entries(data: bytes) -> list[tuple[str, str, int]]:
    """(key, text, declared length) for each version string."""
    return [(key, text, declared) for key, text, declared, _, _ in _strings(data)]


def version_strings(path) -> dict[str, str]:
    """The version strings of the PE file at `path`."""
    return {key: text for key, text, _ in string_entries(Path(path).read_bytes())}


def trim(path) -> dict[str, str]:
    """Strip trailing whitespace from every version string of the file at
    `path`, in place, and return the strings as they now read."""
    path = Path(path)
    data = path.read_bytes()
    patches = []
    for _, text, declared, pos, text_at in _strings(data):
        kept = text.rstrip()
        cut = len(kept.encode("utf-16-le"))
        if kept != text:
            patches.append((text_at + cut, b"\0" * (len(text.encode("utf-16-le")) - cut)))
        if declared != len(kept) + 1:
            patches.append((pos + 2, struct.pack("<H", len(kept) + 1)))
    if patches:
        with open(path, "r+b") as fh:
            for at, raw in patches:
                fh.seek(at)
                fh.write(raw)
    return version_strings(path)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: trim_version_info.py <installer.exe>", file=sys.stderr)
        return 2
    strings = trim(argv[0])
    for key, text in strings.items():
        print(f"{key}: {text!r}")
    padded = [key for key, text in strings.items() if text != text.strip()]
    if padded:
        print(f"still padded: {', '.join(padded)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
