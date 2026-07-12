"""File commands: save, open, import, export, new.

Each takes a typed path; the window's menu actions call these with dialogs.
"""

import os

from .. import fileio
from .base import OptionReq, SelectReq, TextReq, command


def _expand(path: str) -> str:
    return os.path.abspath(os.path.expanduser(path.strip()))


@command("save", mutates=False)
def cmd_save(ctx):
    default = getattr(ctx, "current_path", None)
    path = yield TextReq("Save as (.serp path)", default=default)
    path = _expand(path)
    if not path.endswith(".serp"):
        path += ".serp"
    fileio.export_file(ctx.scene, path)
    ctx.current_path = path
    ctx.echo(f"Saved {len(ctx.scene.all())} object(s) to {path}")


@command("open", mutates=True)
def cmd_open(ctx):
    path = yield TextReq("File to open (.serp)")
    path = _expand(path)
    if not os.path.exists(path):
        ctx.echo(f"File not found: {path}")
        return
    fileio.import_file(ctx.scene, path)
    ctx.current_path = path if path.endswith(".serp") else None
    ctx.echo(f"Opened {path}: {len(ctx.scene.all())} object(s).")
    if ctx.viewport:
        ctx.viewport.zoom_extents()


@command("import", aliases=("imp",), mutates=True)
def cmd_import(ctx):
    path = yield TextReq("File to import (.step/.stp/.obj/.serp)")
    path = _expand(path)
    if not os.path.exists(path):
        ctx.echo(f"File not found: {path}")
        return
    n = fileio.import_file(ctx.scene, path)
    ctx.echo(f"Imported {n} object(s) from {os.path.basename(path)}.")
    if ctx.viewport:
        ctx.viewport.zoom_extents()


@command("export", aliases=("exp",), mutates=False)
def cmd_export(ctx):
    scope = yield OptionReq("Export", options=["All", "Selected"],
                            default="All")
    ids = None
    if scope == "Selected":
        objs = yield SelectReq("Select objects to export")
        ids = [o.id for o in objs]
    path = yield TextReq("Export path (.step/.stp/.obj/.serp)")
    path = _expand(path)
    fileio.export_file(ctx.scene, path, only_ids=ids)
    ctx.echo(f"Exported to {path}")


@command("new", mutates=True)
def cmd_new(ctx):
    confirm = yield OptionReq("Clear the scene?", options=["Yes", "No"],
                              default="No")
    if confirm == "Yes":
        ctx.scene.clear()
        ctx.current_path = None
        ctx.echo("New document.")
    else:
        ctx.echo("Cancelled.")
