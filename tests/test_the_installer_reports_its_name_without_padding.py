"""The installer says it is "Serpentine3D", not "Serpentine3D" and 48 spaces.

Inno Setup's setup stub ships a version resource whose strings are
placeholders of 60 spaces, and ISCC writes each VersionInfo* value over the
start of its placeholder without shortening it. So every string in the
installer's version resource keeps the rest of the spaces: ProductName comes
out as "Serpentine3D" padded to 60 characters, OriginalFileName as nothing
but spaces. Explorer hides that. SignPath does not, and refused the first
test-signing request with "unexpected product name 'Serpentine3D '".

trim_version_info.py fixes the installer after ISCC and before it is signed:
it ends each string where its text ends, in place, so no offset in the file
moves. These tests build a small PE file carrying a version resource padded
the way Inno pads it, because the real installer only exists on Windows.
"""
import importlib.util
import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = ROOT / "packaging" / "windows"

PLACEHOLDER = 60          # Inno's Setup.version.rc: 60 spaces per string
SECTION_RVA = 0x1000
SECTION_OFFSET = 0x400


def _load():
    path = WINDOWS / "trim_version_info.py"
    spec = importlib.util.spec_from_file_location("trim_version_info", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# -- a PE file with a version resource, built the way rc.exe lays one out ---

def _pad4(b: bytes) -> bytes:
    return b + b"\0" * (-len(b) % 4)


def _node(key: str, value: bytes, value_len: int, wtype: int,
          children: tuple[bytes, ...] = ()) -> bytes:
    body = _pad4(b"\0" * 6 + (key + "\0").encode("utf-16-le"))
    body += value
    if children:
        body = _pad4(body) + b"".join(_pad4(c) for c in children[:-1]) + children[-1]
    return struct.pack("<HHH", len(body), value_len, wtype) + body[6:]


def _string(key: str, text: str) -> bytes:
    raw = (text + "\0").encode("utf-16-le")
    return _node(key, raw, len(text) + 1, 1)


def _version_resource(strings: dict[str, str]) -> bytes:
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x10000, 0, 0, 0, 0, 0,
                        0x3F, 0, 0x40004, 1, 0, 0)
    table = _node("000004b0", b"", 0, 1,
                  tuple(_string(k, v) for k, v in strings.items()))
    sfi = _node("StringFileInfo", b"", 0, 1, (table,))
    var = _node("VarFileInfo", b"", 0, 1,
                (_node("Translation", struct.pack("<HH", 0, 0x4B0), 4, 0),))
    return _node("VS_VERSION_INFO", fixed, len(fixed), 0, (sfi, var))


def _pe(resource: bytes, overlay: bytes = b"") -> bytes:
    """A PE32+ file with one .rsrc section holding RT_VERSION #1, lang 0."""
    def directory(entry_id: int, target: int, subdir: bool) -> bytes:
        return (struct.pack("<IIHHHH", 0, 0, 0, 0, 0, 1)
                + struct.pack("<II", entry_id,
                              target | (0x80000000 if subdir else 0)))
    rsrc = directory(16, 24, True) + directory(1, 48, True) + directory(0, 72, False)
    rsrc += struct.pack("<IIII", SECTION_RVA + 88, len(resource), 0, 0)
    rsrc += resource
    rsrc = rsrc + b"\0" * (-len(rsrc) % 0x200)

    optional = bytearray(240)
    struct.pack_into("<H", optional, 0, 0x20B)
    struct.pack_into("<I", optional, 108, 16)
    struct.pack_into("<II", optional, 112 + 2 * 8, SECTION_RVA, len(rsrc))
    section = struct.pack("<8sIIIIIIHHI", b".rsrc", len(rsrc), SECTION_RVA,
                          len(rsrc), SECTION_OFFSET, 0, 0, 0, 0, 0x40000040)
    head = bytearray(0x40)
    head[:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, 0x40)
    head += b"PE\0\0" + struct.pack("<HHIIIHH", 0x8664, 1, 0, 0, 0, 240, 0x22)
    head += bytes(optional) + section
    head += b"\0" * (SECTION_OFFSET - len(head))
    return bytes(head) + rsrc + overlay


INTENDED = {
    "CompanyName": "Chisomo Banzi",
    "FileDescription": "Serpentine3D Setup",
    "FileVersion": "0.13.0",
    "LegalCopyright": "MIT Licensed. Copyright © Chisomo Banzi.",
    "ProductName": "Serpentine3D",
    "OriginalFileName": "",
    "ProductVersion": "0.13.0",
}


def _as_inno_writes_it(tmp_path) -> Path:
    padded = {k: v.ljust(PLACEHOLDER) for k, v in INTENDED.items()}
    path = tmp_path / "Serpentine3D-Setup-x86_64.exe"
    # setup.exe carries its compressed payload after the PE image
    path.write_bytes(_pe(_version_resource(padded), overlay=b"\x5a" * 4096))
    return path


# -- the behaviour --------------------------------------------------------

def test_the_padding_is_read_as_inno_leaves_it(tmp_path):
    """The reader sees what SignPath saw, or the fix proves nothing."""
    strings = _load().version_strings(_as_inno_writes_it(tmp_path))
    assert strings["ProductName"] == "Serpentine3D".ljust(PLACEHOLDER)
    assert strings["OriginalFileName"] == " " * PLACEHOLDER


def test_every_string_ends_where_its_text_ends(tmp_path):
    mod = _load()
    path = _as_inno_writes_it(tmp_path)
    assert mod.trim(path) == INTENDED
    assert mod.version_strings(path) == INTENDED


def test_the_declared_lengths_match_the_text(tmp_path):
    """A reader that trusts wValueLength rather than the terminator must get
    the same answer."""
    mod = _load()
    path = _as_inno_writes_it(tmp_path)
    mod.trim(path)
    for key, value, declared in mod.string_entries(path.read_bytes()):
        assert declared == len(value) + 1, key


def test_nothing_in_the_file_moves(tmp_path):
    """setup.exe finds its payload by offset; the file must keep its size
    and every byte outside the strings."""
    path = _as_inno_writes_it(tmp_path)
    before = path.read_bytes()
    _load().trim(path)
    after = path.read_bytes()
    assert len(after) == len(before)
    assert after[:SECTION_OFFSET] == before[:SECTION_OFFSET]
    assert after[-4096:] == before[-4096:]
    # only the resource changes: spaces become terminators, and each
    # string's declared length shrinks to match
    start = SECTION_OFFSET + 88
    end = start + len(_version_resource(
        {k: v.ljust(PLACEHOLDER) for k, v in INTENDED.items()}))
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert changed and all(start <= i < end for i in changed)
    assert all(after[i] == 0 for i in changed if before[i] == 0x20)


def test_trimming_twice_changes_nothing(tmp_path):
    mod = _load()
    path = _as_inno_writes_it(tmp_path)
    mod.trim(path)
    once = path.read_bytes()
    mod.trim(path)
    assert path.read_bytes() == once


def test_a_file_without_a_version_resource_is_an_error(tmp_path):
    path = tmp_path / "plain.exe"
    path.write_bytes(b"MZ" + b"\0" * 200)
    with pytest.raises(ValueError):
        _load().trim(path)


def test_the_command_line_trims_and_prints_the_result(tmp_path, capsys):
    path = _as_inno_writes_it(tmp_path)
    assert _load().main([str(path)]) == 0
    out = capsys.readouterr().out
    assert "ProductName: 'Serpentine3D'" in out


# -- the build uses it ----------------------------------------------------

def test_the_build_trims_the_installer_after_iscc():
    ps1 = (WINDOWS / "build-installer.ps1").read_text(encoding="utf-8")
    iscc = ps1.index("& $iscc installer.iss")
    trim = ps1.index("trim_version_info.py")
    assert iscc < trim < ps1.index("INSTALLER OK")
    assert re.search(r"trim_version_info\.py.*\n.*LASTEXITCODE", ps1)


def test_the_build_checks_the_names_windows_reports():
    """Read back through Windows' own API, compared case- and
    space-exactly, so a bad name fails the build rather than a signing
    request."""
    ps1 = (WINDOWS / "build-installer.ps1").read_text(encoding="utf-8")
    assert ".VersionInfo" in ps1
    for field, expected in (("ProductName", "Serpentine3D"),
                            ("CompanyName", "Chisomo Banzi")):
        assert re.search(rf"{field} -cne '{expected}'", ps1), field
    assert re.search(r"ProductVersion -cne \$version", ps1)
    assert "make_version_info.py --version" in ps1
