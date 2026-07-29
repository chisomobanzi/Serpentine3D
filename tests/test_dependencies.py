"""What we import, we declare.

A package that imports something it never asked for is living on someone
else's dependency list, and that list can change without warning: `mcp` 2.0
swapped `httpx` for `httpx2`, and every install that had been getting httpx
for free suddenly did not have it.
"""

import ast
import os
import sys
import tomllib

import importlib.metadata as md

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "serpentine3d")


def _normalise(name: str) -> str:
    return name.lower().replace("_", "-")


def _imported_roots() -> set[str]:
    """Top-level names imported anywhere in the package, our own aside."""
    roots: set[str] = set()
    for dirpath, _, files in os.walk(PKG):
        for f in files:
            if not f.endswith(".py"):
                continue
            tree = ast.parse(open(os.path.join(dirpath, f)).read())
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


def test_mcp_is_pinned_to_the_api_the_server_is_written_against():
    """`mcp.server.fastmcp` is gone in mcp 2.x — it is `mcp.server.mcpserver`
    now. Until the server is ported, an unbounded `mcp>=1.0` lets a fresh
    install pick up 2.x and fail at import."""
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        deps = tomllib.load(fh)["project"]["dependencies"]
    spec = next(d for d in deps if d.split(">")[0].split("<")[0] == "mcp")
    assert "<2" in spec, (
        f"mcp is declared as {spec!r} with no upper bound, but "
        "serpentine3d/mcp_server/server.py imports mcp.server.fastmcp, "
        "which 2.x removed")
