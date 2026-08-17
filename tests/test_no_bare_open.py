"""No text-mode open() may lean on the platform's default encoding.

open("f", "w") with no encoding writes in whatever the OS locale happens to
be: UTF-8 on the Mac and most Linux boxes, but cp1252 (or worse) on a Windows
box in a non-English locale. A layer named with an accented character, a file
path outside ASCII, and the file round-trips to mojibake or an exception on
one machine and not another.

The fix is boring and total: every text-mode open states encoding="utf-8".
Binary opens are exempt, they carry bytes and take no encoding. This test walks
the source and fails with the offenders listed, so a bare one cannot creep
back in.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN_DIRS = ["serpentine3d", "tests", "docs", "tools", "scripts"]
SKIP_DIRS = {".venv", ".git", "build", "dist", ".idea", "__pycache__"}


def _is_builtin_open(call: ast.Call) -> bool:
    return isinstance(call.func, ast.Name) and call.func.id == "open"


def _text_mode(call: ast.Call) -> bool:
    """True when this open() reads or writes text (so it needs an encoding).

    The mode is the second positional argument or the mode= keyword; an omitted
    mode defaults to text "r". A literal mode with a "b" is binary and exempt. A
    non-literal mode is flagged to be looked at rather than waved through.
    """
    mode_node = None
    if len(call.args) >= 2:
        mode_node = call.args[1]
    else:
        for kw in call.keywords:
            if kw.arg == "mode":
                mode_node = kw.value
                break
    if mode_node is None:
        return True                        # omitted -> text "r"
    if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
        return "b" not in mode_node.value
    return True                            # dynamic mode: flag for a human


def _has_encoding(call: ast.Call) -> bool:
    return any(kw.arg == "encoding" for kw in call.keywords)


def _offenders():
    out = []
    for name in SCAN_DIRS:
        base = ROOT / name
        if not base.is_dir():
            continue
        for path in base.rglob("*.py"):
            if SKIP_DIRS & set(path.parts):
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), str(path))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and _is_builtin_open(node)
                        and _text_mode(node) and not _has_encoding(node)):
                    out.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    return sorted(out)


def test_every_text_open_names_its_encoding():
    bad = _offenders()
    assert not bad, (
        "text-mode open() without encoding=\"utf-8\":\n  "
        + "\n  ".join(bad))
