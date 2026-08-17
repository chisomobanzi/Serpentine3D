"""What we import, we declare.

A package that imports something it never asked for is living on someone
else's dependency list, and that list can change without warning: `mcp` 2.0
swapped `httpx` for `httpx2`, and every install that had been getting httpx
for free suddenly did not have it.
"""

import ast
import os
import subprocess
import sys
import tomllib

import importlib.metadata as md

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "serpentine3d")
CI = os.path.join(ROOT, ".github", "workflows", "ci.yml")


def _read(path: str) -> str:
    """Our own source, read as what it is.

    Without the encoding, open() asks the locale, and the locale on a
    Windows box is cp1252: the curly quotes in ai/panel.py and the bullet
    in ui/layers_panel.py are then undecodable and this file's tests die
    on a UnicodeDecodeError before they test anything.
    """
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _normalise(name: str) -> str:
    return name.lower().replace("_", "-")


def _imported_roots() -> set[str]:
    """Top-level names imported anywhere in the package, our own aside."""
    roots: set[str] = set()
    for dirpath, _, files in os.walk(PKG):
        for f in files:
            if not f.endswith(".py"):
                continue
            tree = ast.parse(_read(os.path.join(dirpath, f)))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        roots.add(alias.name.split(".")[0])
                elif isinstance(node, ast.ImportFrom):
                    if node.level == 0 and node.module:
                        roots.add(node.module.split(".")[0])
    return {r for r in roots
            if r not in sys.stdlib_module_names and r != "serpentine3d"}


def _declared() -> set[str]:
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        data = tomllib.load(fh)
    reqs = list(data["project"]["dependencies"])
    for extra in data["project"].get("optional-dependencies", {}).values():
        reqs.extend(extra)
    out = set()
    for req in reqs:
        # "PySide6>=6.6" / "mcp>=1.0,<2" / "httpx" -> the name alone
        name = req.split(";")[0].strip()
        for sep in ("<", ">", "=", "!", "~", "[", " "):
            name = name.split(sep)[0]
        out.add(_normalise(name))
    return out


def test_every_third_party_import_is_a_declared_dependency():
    declared = _declared()
    providers = md.packages_distributions()
    missing = []
    for root in sorted(_imported_roots()):
        dists = providers.get(root)
        if not dists:                       # not installed here; nothing to say
            continue
        if not any(_normalise(d) in declared for d in dists):
            missing.append(f"  import {root}  (comes from "
                           f"{', '.join(sorted(dists))})")
    assert not missing, (
        "the package imports these but pyproject.toml never asks for them:\n"
        + "\n".join(missing)
        + "\n\nAdd them to [project] dependencies. Right now they only arrive "
          "as somebody else's transitive dependency, which is not a promise.")


def test_ci_installs_the_versions_the_lock_file_pins():
    """A green build should mean the code works, not that today's resolution
    happened to be kind.

    Twice now a release landed mid-morning and broke a build that had passed
    an hour earlier on the same commit — nothing here changed, the answer to
    "what does `mcp` mean" did. Resolving afresh on every run makes the whole
    of PyPI an untracked input. uv.lock is the record of what we actually
    tested against; `--locked` is what makes CI read it instead of guessing,
    and makes a stale lock a failure rather than a silent re-resolve.
    """
    text = _read(CI)

    assert "pip install -e" not in text, (
        "a CI job installs with pip, which cannot read uv.lock and so "
        "resolves dependencies fresh on every run. Use "
        "`uv sync --locked` (add `--extra dev` where tests need it).")

    installs = [ln.strip() for ln in text.splitlines() if "uv sync" in ln]
    assert installs, "no job installs anything with uv sync"
    unpinned = [ln for ln in installs if "--locked" not in ln]
    assert not unpinned, (
        "these install without --locked, so uv is free to resolve something "
        "other than what the lock pins:\n  " + "\n  ".join(unpinned))


def test_the_source_walk_says_what_encoding_it_is_reading():
    """A bare open() reads in whatever the locale says, and this file walks
    every module in the package.

    On Linux that locale is UTF-8 and nothing is ever wrong. On Windows it
    is cp1252, which cannot decode the curly quotes in ai/panel.py or the
    bullet in ui/layers_panel.py, so the walk died on a UnicodeDecodeError
    before it checked a single import. Running the walk under
    PYTHONWARNDEFAULTENCODING is how that shows up here rather than only
    on somebody else's machine.
    """
    proc = subprocess.run(
        [sys.executable, "-X", "warn_default_encoding",
         "-W", "error::EncodingWarning", "-c",
         "import test_dependencies as t; t._imported_roots()"],
        cwd=os.path.dirname(os.path.abspath(__file__)),
        capture_output=True, text=True, check=False)   # the code is the result
    assert proc.returncode == 0, (
        "the package source is read without an encoding, so a Windows run "
        "reads it as cp1252:\n" + proc.stderr[-1500:])


def test_mcp_is_pinned_to_the_api_the_server_is_written_against():
    """mcp 1.x and 2.x do not offer the same module: `mcp.server.fastmcp`
    became `mcp.server.mcpserver`. Whichever one the server imports, the
    version range has to be the one that has it — an unbounded range lets a
    fresh install pick the other and fail at import."""
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        deps = tomllib.load(fh)["project"]["dependencies"]
    spec = next(d for d in deps if d.split(">")[0].split("<")[0] == "mcp")
    source = _read(os.path.join(PKG, "mcp_server", "server.py"))

    if "mcp.server.fastmcp" in source:
        wanted, era = "<2", "mcp.server.fastmcp, which 2.x removed"
    elif "mcp.server.mcpserver" in source:
        wanted, era = ">=2", "mcp.server.mcpserver, which 1.x does not have"
    else:
        raise AssertionError("the MCP server imports neither known module")

    assert wanted in spec.replace(" ", ""), (
        f"mcp is declared as {spec!r}, but "
        f"serpentine3d/mcp_server/server.py imports {era}")
