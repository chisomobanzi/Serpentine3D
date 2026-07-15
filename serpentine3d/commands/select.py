"""Selection commands: filters, inversion, isolation."""

from .base import OptionReq, SelectReq, TextReq, command


def _select_kind(ctx, kind: str, label: str):
    ids = [o.id for o in ctx.scene.selectable_objects() if o.kind == kind]
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
    ids = [o.id for o in ctx.scene.selectable_objects()
           if o.layer_id == layer.id]
    ctx.selection.set(ids)
    ctx.echo(f"Selected {len(ids)} object(s) on '{layer.name}'.")


@command("selname", mutates=False)
def cmd_selname(ctx):
    """Select objects whose name contains the given text."""
    text = yield TextReq("Name contains")
    needle = text.lower()
    ids = [o.id for o in ctx.scene.selectable_objects()
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
    ids = [o.id for o in ctx.scene.selectable_objects()
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


@command("selfilter", aliases=("selectionfilter",), mutates=False)
def cmd_selfilter(ctx):
    """Restrict viewport picking to one kind of object (Off = anything).
    'selfiltertoggle' (F6-style) pauses/resumes without forgetting."""
    kind = yield OptionReq(
        "Selectable objects",
        options=["Off", "Curves", "Surfaces", "Solids", "Meshes", "Points"],
        default="Off")
    sel = ctx.selection
    if kind == "Off":
        sel.filter_active = False
        sel.filter_kinds = set()
        ctx.echo("Selection filter off — clicking selects anything.")
    else:
        sel.filter_kinds = {kind.lower().rstrip("es") if kind == "Meshes"
                            else kind.lower().rstrip("s")}
        sel.filter_active = True
        ctx.echo(f"Selection filter: only {kind.lower()} are clickable "
                 "(sel* commands ignore the filter).")
    if ctx.window is not None:
        ctx.window._update_status()


@command("selfiltertoggle", aliases=("sft",), mutates=False)
def cmd_selfiltertoggle(ctx):
    """Pause/resume the selection filter without changing its kind."""
    sel = ctx.selection
    if not sel.filter_kinds:
        ctx.echo("No selection filter set — choose one with 'selfilter'.")
    else:
        sel.filter_active = not sel.filter_active
        state = "on" if sel.filter_active else "paused"
        kinds = ", ".join(sorted(sel.filter_kinds))
        ctx.echo(f"Selection filter {state} ({kinds}).")
    if ctx.window is not None:
        ctx.window._update_status()
    yield from ()


@command("seldup", mutates=False)
def cmd_seldup(ctx):
    """Select later duplicates of identical, identically-placed objects."""
    from ..core import geometry as g

    def _key(o):
        (mn, mx) = g.bbox(o.shape)
        if o.kind == "solid":
            meas = g.volume(o.shape)
        elif o.kind == "surface":
            meas = g.surface_area(o.shape)
        elif o.kind == "curve":
            meas = g.curve_length(o.shape)
        else:
            meas = 0.0
        return (o.kind,
                tuple(round(v, 4) for v in (*mn, *mx)),
                round(meas, 4))

    seen, dups = set(), []
    for o in ctx.scene.selectable_objects():
        k = _key(o)
        if k in seen:
            dups.append(o.id)
        else:
            seen.add(k)
    ctx.selection.set(dups)
    ctx.echo(f"Selected {len(dups)} duplicate object(s)."
             if dups else "No duplicates found.")
    yield from ()
