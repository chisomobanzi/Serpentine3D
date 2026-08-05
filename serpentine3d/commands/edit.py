"""Editing commands: delete, join, hide/show, selection, undo/redo, layers."""

from ..core import geometry as g
from .base import NumberReq, OptionReq, SelectReq, TextReq, command


@command("delete", aliases=("del", "erase"), space="any", repeatable=False)
def cmd_delete(ctx):
    lv = ctx.sheet_view()
    if lv is not None:
        # what is picked on a sheet is the sheet's own, and the sheet is what
        # knows how to take a frame or an annotation out of itself
        count = len(lv.selected)
        if not lv.delete_selected():
            ctx.echo("Nothing is picked on this sheet — click the geometry, "
                     "a detail frame or an annotation first.")
            return
        ctx.echo(f"Deleted {count} sheet item(s).")
        return
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


@command("offset")
def cmd_offset(ctx):
    objs = yield SelectReq("Select curve to offset", kinds=("curve",),
                           max_count=1)
    from . import dragging
    from .base import PointReq
    shape = objs[0].shape
    mid = dragging.curve_middle(shape)
    out = dragging.offset_direction(shape, tuple(ctx.cplane.normal))
    read = dragging.signed_along(mid, out)

    def _offset_to(p):
        v = read(p)
        if abs(v) < 1e-9:
            return None
        try:
            return g.offset_curve(shape, v)
        except g.GeometryError:
            return None

    dp = yield PointReq("Offset distance (click a side, or type a number)",
                        axis_lock=(mid, out),
                        number_from=(mid, out), rubber_from=mid,
                        preview_fn=_offset_to)
    dist = read(dp)
    if abs(dist) < 1e-9:
        ctx.echo("Zero offset — nothing created.")
        return
    new_shape = g.offset_curve(shape, dist)
    obj = ctx.scene.add(new_shape, layer_id=objs[0].layer_id)
    ctx.echo(f"Offset -> {obj.name}.")


@command("fillet")
def cmd_fillet(ctx):
    a = yield SelectReq("Select first curve to fillet", kinds=("curve",),
                        max_count=1)
    b = yield SelectReq("Select second curve", kinds=("curve",),
                        max_count=1, allow_preselected=False)
    from . import dragging
    from .base import PointReq
    # the corner comes first: until we know which one, there is no fillet to
    # show, and once we do the radius can be dragged straight out of it
    corner = yield PointReq("Point near the corner to fillet")
    read = dragging.distance_from(corner)

    def _fillet_to(p):
        r = read(p)
        if r < 1e-9:
            return None
        try:
            return g.join_curves(list(
                g.fillet_curves(a[0].shape, b[0].shape, r, corner)))
        except g.GeometryError:
            return None

    rp = yield PointReq("Fillet radius (click, or type a number)",
                        number_from=(corner, tuple(ctx.cplane.xdir)),
                        rubber_from=corner, preview_fn=_fillet_to)
    radius = read(rp)
    if radius < 1e-9:
        ctx.echo("Zero radius — nothing filleted.")
        return
    ea, arc, eb = g.fillet_curves(a[0].shape, b[0].shape, radius, corner)
    joined = g.join_curves([ea, arc, eb])
    ctx.scene.remove(b[0].id)
    new = ctx.scene.replace_shape(a[0].id, joined)
    ctx.echo(f"Filleted into {new.name} (r={radius:g}).")


@command("explode", aliases=("x",))
def cmd_explode(ctx):
    objs = yield SelectReq("Select objects to explode")
    total = 0
    for o in objs:
        parts = g.explode(o.shape)
        if not parts:
            ctx.echo(f"{o.name} cannot be exploded further.")
            continue
        for p in parts:
            ctx.scene.add(p, layer_id=o.layer_id)
        ctx.scene.remove(o.id)
        total += len(parts)
    if total:
        ctx.echo(f"Exploded into {total} object(s).")


@command("split")
def cmd_split(ctx):
    targets = yield SelectReq("Select curve or surface to split",
                              kinds=("curve", "surface", "solid"),
                              max_count=1)
    cutters = yield SelectReq("Select cutting objects",
                              allow_preselected=False)
    target = targets[0]
    pieces = g.split_shape(target.shape, [c.shape for c in cutters])
    for p in pieces:
        ctx.scene.add(p, layer_id=target.layer_id)
    ctx.scene.remove(target.id)
    ctx.echo(f"Split {target.name} into {len(pieces)} pieces.")


@command("trim", aliases=("tr",))
def cmd_trim(ctx):
    cutters = yield SelectReq("Select cutting objects")
    targets = yield SelectReq("Select object to trim",
                              kinds=("curve", "surface", "solid"),
                              max_count=1, allow_preselected=False)
    target = targets[0]
    pieces = g.split_shape(target.shape, [c.shape for c in cutters])
    added = [ctx.scene.add(p, layer_id=target.layer_id) for p in pieces]
    ctx.scene.remove(target.id)
    doomed = yield SelectReq(
        "Select the piece(s) to trim away", allow_preselected=False)
    kept = 0
    for o in doomed:
        ctx.scene.remove(o.id)
    kept = sum(1 for a in added if ctx.scene.get(a.id))
    ctx.echo(f"Trimmed {len(doomed)} piece(s); {kept} kept.")


@command("rebuild")
def cmd_rebuild(ctx):
    objs = yield SelectReq("Select curves to rebuild", kinds=("curve",))
    from .base import IntReq
    count = yield IntReq("Point count", default=10, minimum=2)
    degree = yield IntReq("Degree", default=3, minimum=1)
    for o in objs:
        ctx.scene.replace_shape(
            o.id, g.rebuild_curve(o.shape, point_count=count, degree=degree))
    ctx.echo(f"Rebuilt {len(objs)} curve(s) with {count} points, "
             f"degree {degree}.")


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


# Not repeatable: both have a key and a button of their own, so a
# right-click meant for something else should not walk the drawing
# back a step, and undo must not become the repeat target either: after
# undoing a bad circle you want another circle to get right, not the loss
# of the one before it.
@command("undo", mutates=False, repeatable=False)
def cmd_undo(ctx):
    label = ctx.history.undo()
    ctx.echo(f"Undid {label}." if label else "Nothing to undo.")
    yield from ()


@command("redo", mutates=False, repeatable=False)
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
        "Layer action", options=["New", "Current", "Show", "Hide", "Rename",
                                 "Weight", "Linetype"],
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
    elif action == "Weight":
        name = yield TextReq("Layer name")
        layer = layers.find_by_name(name)
        if layer is None:
            ctx.echo(f"No layer named '{name}'.")
        else:
            w = yield NumberReq("Edge width on screen (pixels)",
                                default=layer.lineweight, minimum=0.2)
            layers.set_lineweight(layer.id, float(w))
            ctx.echo(f"Layer '{layer.name}' draws {w:g}px edges.")
    elif action == "Linetype":
        from ..core import linetype as lt
        name = yield TextReq("Layer name")
        layer = layers.find_by_name(name)
        if layer is None:
            ctx.echo(f"No layer named '{name}'.")
        else:
            style = yield OptionReq("Linetype", options=list(lt.LINETYPES),
                                    default=layer.linetype)
            layers.set_linetype(layer.id, style)
            ctx.echo(f"Layer '{layer.name}' draws {style} lines.")
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


_MATERIAL_PRESETS = {
    "Matte":   {"metallic": 0.0, "roughness": 0.9, "opacity": 1.0},
    "Plastic": {"metallic": 0.0, "roughness": 0.35, "opacity": 1.0},
    "Metal":   {"metallic": 1.0, "roughness": 0.25, "opacity": 1.0},
    "Glass":   {"metallic": 0.0, "roughness": 0.05, "opacity": 0.35},
}


@command("material", aliases=("mat",))
def cmd_material(ctx):
    """Assign a look (metallic/roughness/opacity) for rendered display
    and GLB/USD export."""
    objs = yield SelectReq("Select objects for the material")
    preset = yield OptionReq(
        "Material", options=[*_MATERIAL_PRESETS, "Custom", "Remove"],
        default="Matte")
    if preset == "Remove":
        for o in objs:
            ctx.scene.update(o.id, material=None)
        ctx.echo(f"Cleared material on {len(objs)} object(s).")
        return
    if preset == "Custom":
        metallic = yield NumberReq("Metallic (0-1)", default=0.0, minimum=0.0)
        roughness = yield NumberReq("Roughness (0-1)", default=0.5,
                                    minimum=0.0)
        opacity = yield NumberReq("Opacity (0-1)", default=1.0, minimum=0.05)
        mat = {"metallic": min(float(metallic), 1.0),
               "roughness": min(float(roughness), 1.0),
               "opacity": min(float(opacity), 1.0)}
    else:
        mat = dict(_MATERIAL_PRESETS[preset])
    for o in objs:
        ctx.scene.update(o.id, material=mat)
    ctx.echo(f"{preset if preset != 'Custom' else 'Custom'} material on "
             f"{len(objs)} object(s) — see it with 'rendered'.")


@command("recordhistory", aliases=("history",), mutates=False)
def cmd_recordhistory(ctx):
    """Toggle record history: loft/extrude/revolve outputs rebuild when
    their input curves are edited."""
    ctx.scene.record_history = not ctx.scene.record_history
    n = len(ctx.scene.history_records)
    state = "ON" if ctx.scene.record_history else "OFF"
    ctx.echo(f"Record history {state}"
             + (f" ({n} recorded object(s) stay live)." if n else "."))
    yield from ()


@command("plugins", mutates=False)
def cmd_plugins(ctx):
    """List loaded plugins and where they came from."""
    from ..plugins import load_plugins, loaded_plugins, plugin_dir
    load_plugins(ctx.window)               # pick up newly dropped files
    plugs = loaded_plugins()
    if not plugs:
        ctx.echo(f"No plugins. Drop .py files defining "
                 f"serpentine3d_plugin(ctx) into {plugin_dir()} or install "
                 "packages with a 'serpentine3d.plugins' entry point.")
    else:
        for name, origin in plugs:
            ctx.echo(f"{name} — {origin}")
    yield from ()


@command("boundingbox", aliases=("bb",))
def cmd_boundingbox(ctx):
    """Create the world-aligned bounding box of the selection."""
    objs = yield SelectReq("Select objects for the bounding box")
    import numpy as np
    mins = np.full(3, np.inf)
    maxs = np.full(3, -np.inf)
    for o in objs:
        mn, mx = g.bbox(o.shape)
        mins = np.minimum(mins, mn)
        maxs = np.maximum(maxs, mx)
    size = maxs - mins
    if min(size) < 1e-9:
        ctx.echo("Selection is flat — bounding box would be degenerate.")
        return
    obj = ctx.scene.add(g.make_box(tuple(mins), *map(float, size)))
    ctx.echo(f"Created {obj.name} "
             f"({size[0]:g} x {size[1]:g} x {size[2]:g}).")


@command("smooth")
def cmd_smooth(ctx):
    """Relax a curve's control points toward their neighbours."""
    objs = yield SelectReq("Select curves to smooth", kinds=("curve",))

    def _preview(s):
        try:
            return g.make_compound(
                [g.smooth_curve(o.shape, s, 5) for o in objs])
        except g.GeometryError:
            return None

    strength = yield NumberReq("Smooth factor (0–1)", default=0.2,
                               minimum=0.0, preview_fn=_preview)
    n = 0
    for o in objs:
        try:
            ctx.scene.replace_shape(o.id,
                                    g.smooth_curve(o.shape, strength, 5))
            n += 1
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    ctx.echo(f"Smoothed {n} curve(s).")


@command("chamfer")
def cmd_chamfer(ctx):
    """Bevel the corner between two curves with straight cut-offs."""
    a = yield SelectReq("Select first curve to chamfer", kinds=("curve",),
                        max_count=1)
    b = yield SelectReq("Select second curve", kinds=("curve",),
                        max_count=1, allow_preselected=False)
    from .base import TextReq
    from ..utils.units import parse_length
    t = yield TextReq("Chamfer distance (or d1,d2)", default="1")
    if "," in t:
        s1, _, s2 = t.partition(",")
        d1 = parse_length(s1, ctx.scene.units)
        d2 = parse_length(s2, ctx.scene.units)
    else:
        d1 = parse_length(t, ctx.scene.units)
        d2 = None
    if d1 is None:
        ctx.echo("Could not parse distance.")
        return
    ea, bevel, eb = g.chamfer_curves(a[0].shape, b[0].shape, d1, d2)
    joined = g.join_curves([ea, bevel, eb])
    ctx.scene.remove(b[0].id)
    new = ctx.scene.replace_shape(a[0].id, joined)
    ctx.echo(f"Chamfered into {new.name}.")
