"""Editing commands: delete, join, hide/show, selection, undo/redo, layers."""

from ..core import geometry as g
from .base import OptionReq, SelectReq, TextReq, command


@command("delete", aliases=("del", "erase"))
def cmd_delete(ctx):
    objs = yield SelectReq("Select objects to delete")
    for o in objs:
        ctx.scene.remove(o.id)
    ctx.echo(f"Deleted {len(objs)} object(s).")


@command("join", aliases=("j",))
def cmd_join(ctx):
    objs = yield SelectReq("Select curves to join", kinds=("curve",),
                           min_count=2)
    joined = g.join_curves([o.shape for o in objs])
    for o in objs[1:]:
        ctx.scene.remove(o.id)
    new = ctx.scene.replace_shape(objs[0].id, joined)
    ctx.echo(f"Joined {len(objs)} curves into {new.name}.")


@command("hide")
def cmd_hide(ctx):
    objs = yield SelectReq("Select objects to hide")
    for o in objs:
        ctx.scene.update(o.id, visible=False)
    ctx.echo(f"Hid {len(objs)} object(s).")


@command("show", aliases=("unhide",))
def cmd_show(ctx):
    n = 0
    for o in ctx.scene.all():
        if not o.visible:
            ctx.scene.update(o.id, visible=True)
            n += 1
    ctx.echo(f"Showed {n} object(s).")
    yield from ()


@command("selall", aliases=("sa",), mutates=False)
def cmd_selall(ctx):
    ctx.selection.select_all()
    ctx.echo(f"Selected {len(ctx.selection.ids)} object(s).")
    yield from ()


@command("selnone", aliases=("sn",), mutates=False)
def cmd_selnone(ctx):
    ctx.selection.clear()
    ctx.echo("Selection cleared.")
    yield from ()


@command("undo", mutates=False)
def cmd_undo(ctx):
    label = ctx.history.undo()
    ctx.echo(f"Undid {label}." if label else "Nothing to undo.")
    yield from ()


@command("redo", mutates=False)
def cmd_redo(ctx):
    label = ctx.history.redo()
    ctx.echo(f"Redid {label}." if label else "Nothing to redo.")
    yield from ()


@command("rename")
def cmd_rename(ctx):
    objs = yield SelectReq("Select object to rename", max_count=1)
    name = yield TextReq("New name", default=objs[0].name)
    ctx.scene.update(objs[0].id, name=name)
    ctx.echo(f"Renamed to {name}.")


@command("layer")
def cmd_layer(ctx):
    action = yield OptionReq(
        "Layer action", options=["New", "Current", "Show", "Hide", "Rename"],
        default="New")
    layers = ctx.scene.layers
    if action == "New":
        name = yield TextReq("Layer name", default="")
        layer = layers.create(name or None)
        layers.current_id = layer.id
        ctx.echo(f"Created layer '{layer.name}' (now current).")
    elif action == "Current":
        name = yield TextReq("Layer to make current")
        layer = layers.find_by_name(name)
        if layer is None:
            ctx.echo(f"No layer named '{name}'.")
        else:
            layers.current_id = layer.id
            ctx.echo(f"Current layer: {layer.name}.")
    elif action in ("Show", "Hide"):
        name = yield TextReq("Layer name")
        layer = layers.find_by_name(name)
        if layer is None:
            ctx.echo(f"No layer named '{name}'.")
        else:
            layers.set_visible(layer.id, action == "Show")
            ctx.echo(f"Layer '{layer.name}' {action.lower()}n.")
    elif action == "Rename":
        old = yield TextReq("Layer to rename")
        layer = layers.find_by_name(old)
        if layer is None:
            ctx.echo(f"No layer named '{old}'.")
        else:
            new = yield TextReq("New name")
            layers.rename(layer.id, new)
            ctx.echo(f"Renamed layer to '{new}'.")
    ctx.scene.notify()
