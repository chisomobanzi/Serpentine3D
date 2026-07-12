"""Selection commands: filters, inversion, isolation."""

from .base import SelectReq, TextReq, command


def _select_kind(ctx, kind: str, label: str):
    ids = [o.id for o in ctx.scene.visible_objects() if o.kind == kind]
    ctx.selection.set(ids)
    ctx.echo(f"Selected {len(ids)} {label}.")


@command("selcrv", aliases=("selcurves",), mutates=False)
def cmd_selcrv(ctx):
    _select_kind(ctx, "curve", "curve(s)")
    yield from ()


@command("selsrf", aliases=("selsurfaces",), mutates=False)
def cmd_selsrf(ctx):
    _select_kind(ctx, "surface", "surface(s)")
    yield from ()


@command("selsolid", aliases=("selsolids",), mutates=False)
def cmd_selsolid(ctx):
    _select_kind(ctx, "solid", "solid(s)")
    yield from ()


@command("sellayer", mutates=False)
def cmd_sellayer(ctx):
    name = yield TextReq("Layer name")
    layer = ctx.scene.layers.find_by_name(name)
    if layer is None:
        ctx.echo(f"No layer named '{name}'.")
        return
    ids = [o.id for o in ctx.scene.visible_objects()
           if o.layer_id == layer.id]
    ctx.selection.set(ids)
    ctx.echo(f"Selected {len(ids)} object(s) on '{layer.name}'.")


@command("selname", mutates=False)
def cmd_selname(ctx):
    """Select objects whose name contains the given text."""
    text = yield TextReq("Name contains")
    needle = text.lower()
    ids = [o.id for o in ctx.scene.visible_objects()
           if needle in o.name.lower()]
    ctx.selection.set(ids)
    ctx.echo(f"Selected {len(ids)} object(s) matching '{text}'.")


@command("sellast", mutates=False)
def cmd_sellast(ctx):
    objs = ctx.scene.all()
    if objs:
        ctx.selection.set([objs[-1].id])
        ctx.echo(f"Selected {objs[-1].name}.")
    else:
        ctx.echo("Scene is empty.")
    yield from ()


@command("invert", aliases=("selinv",), mutates=False)
def cmd_invert(ctx):
    current = set(ctx.selection.ids)
    ids = [o.id for o in ctx.scene.visible_objects()
           if o.id not in current]
    ctx.selection.set(ids)
    ctx.echo(f"Selection inverted: {len(ids)} object(s).")
    yield from ()


@command("isolate")
def cmd_isolate(ctx):
    objs = yield SelectReq("Select objects to isolate")
    keep = {o.id for o in objs}
    hidden = []
    for o in ctx.scene.all():
        if o.id not in keep and o.visible:
            ctx.scene.update(o.id, visible=False)
            hidden.append(o.id)
    ctx._isolated = getattr(ctx, "_isolated", [])
    ctx._isolated.extend(hidden)
    ctx.echo(f"Isolated {len(keep)} object(s); {len(hidden)} hidden. "
             "Run 'unisolate' to restore.")


@command("unisolate")
def cmd_unisolate(ctx):
    hidden = getattr(ctx, "_isolated", [])
    n = 0
    for obj_id in hidden:
        if ctx.scene.get(obj_id):
            ctx.scene.update(obj_id, visible=True)
            n += 1
    ctx._isolated = []
    ctx.echo(f"Restored {n} object(s).")
    yield from ()
