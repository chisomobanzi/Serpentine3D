"""Organisation: groups, locking, blocks."""

import uuid

from ..core import geometry as g
from .base import (NumberReq, OptionReq, PointReq, SelectReq,
                   TextReq, command)


@command("group")
def cmd_group(ctx):
    objs = yield SelectReq("Select objects to group", min_count=2)
    gid = uuid.uuid4().hex[:8]
    ctx.scene.update_many([o.id for o in objs], group_id=gid)
    ctx.select_result(objs)
    ctx.echo(f"Grouped {len(objs)} object(s) — clicking one now selects "
             "them all.")


@command("ungroup")
def cmd_ungroup(ctx):
    objs = yield SelectReq("Select grouped objects to ungroup")
    n = ctx.scene.update_many([o.id for o in objs if o.group_id],
                              group_id=None)
    ctx.select_result(objs)
    ctx.echo(f"Ungrouped {n} object(s).")


@command("lock")
def cmd_lock(ctx):
    objs = yield SelectReq("Select objects to lock")
    ctx.scene.update_many([o.id for o in objs], locked=True)
    ctx.selection.clear()
    ctx.echo(f"Locked {len(objs)} object(s) — visible but unselectable. "
             "'unlockall' releases them.")


@command("lockother")
def cmd_lockother(ctx):
    """Lock everything except what you picked, as Rhino's LockOther does.

    The other half of isolate. Isolate takes the rest of the drawing off the
    screen; this leaves it up to line the new work against, and only stops
    you picking it, which is what you actually wanted when the thing you
    keep catching is a background curve you have no intention of moving.

    What you picked stays picked, so you can get straight on with it.
    """
    objs = yield SelectReq("Select objects to leave unlocked")
    keep = {o.id for o in objs}
    n = ctx.scene.update_many([o.id for o in ctx.scene.all()
                               if o.id not in keep and not o.locked],
                              locked=True)
    # a command normally lets go of the selection on the way out, and here
    # that would leave you holding nothing and everything else unpickable
    ctx.select_result(list(keep))
    ctx.echo(f"Locked {n} object(s); {len(keep)} left to work on. "
             "'unlockall' releases them.")


@command("unlockall", aliases=("unlock",))
def cmd_unlockall(ctx):
    n = ctx.scene.update_many([o.id for o in ctx.scene.all() if o.locked],
                              locked=False)
    ctx.echo(f"Unlocked {n} object(s).")
    yield from ()


# ---------------------------------------------------------------- blocks

@command("block")
def cmd_block(ctx):
    """Turn a selection into a reusable block definition + one instance."""
    objs = yield SelectReq("Select objects for the block", min_count=1)
    name = yield TextReq("Block name",
                         default=f"Block {len(ctx.scene.block_defs) + 1}")
    if any(bd["name"].lower() == name.lower()
           for bd in ctx.scene.block_defs.values()):
        ctx.echo(f"A block named '{name}' already exists.")
        return
    bid = uuid.uuid4().hex[:8]
    ctx.scene.block_defs[bid] = {
        "name": name,
        "shapes": [o.shape for o in objs],
    }
    layer_id = objs[0].layer_id
    compound = g.make_compound([o.shape for o in objs])
    for o in objs:
        ctx.scene.remove(o.id)
    inst = ctx.scene.add(compound, name=f"{name} 01", layer_id=layer_id)
    ctx.scene.update(inst.id, block_id=bid)
    ctx.echo(f"Block '{name}' defined ({len(ctx.scene.block_defs[bid]['shapes'])} "
             "shape(s)). Place more copies with 'insert'.")


@command("insert")
def cmd_insert(ctx):
    defs = ctx.scene.block_defs
    if not defs:
        ctx.echo("No block definitions yet — create one with 'block'.")
        return
        yield  # pragma: no cover
    names = [bd["name"] for bd in defs.values()]
    choice = yield OptionReq("Block to insert", options=names,
                             default=names[0])
    point = yield PointReq("Insertion point")
    bid, bd = next((k, v) for k, v in defs.items()
                   if v["name"] == choice)
    compound = g.make_compound(bd["shapes"])
    placed = g.translate(compound, point)
    count = sum(1 for o in ctx.scene.all() if o.block_id == bid) + 1
    inst = ctx.scene.add(placed, name=f"{choice} {count:02d}")
    ctx.scene.update(inst.id, block_id=bid)
    ctx.echo(f"Inserted '{choice}' at {point}.")


@command("blocklist", aliases=("blockmanager",), mutates=False)
def cmd_blocklist(ctx):
    defs = ctx.scene.block_defs
    if not defs:
        ctx.echo("No block definitions.")
    else:
        lines = []
        for bid, bd in defs.items():
            n = sum(1 for o in ctx.scene.all() if o.block_id == bid)
            lines.append(f"{bd['name']}: {n} instance(s), "
                         f"{len(bd['shapes'])} shape(s)")
        ctx.echo("Blocks — " + "; ".join(lines))
    yield from ()


@command("count", mutates=False)
def cmd_count(ctx):
    """Count objects: totals by block, kind and layer (for takeoffs)."""
    objs = ctx.scene.visible_objects()
    by_block = {}
    by_kind = {}
    for o in objs:
        by_kind[o.kind] = by_kind.get(o.kind, 0) + 1
        if o.block_id and o.block_id in ctx.scene.block_defs:
            bname = ctx.scene.block_defs[o.block_id]["name"]
            by_block[bname] = by_block.get(bname, 0) + 1
    parts = [f"{n}× {k}" for k, n in sorted(by_kind.items())]
    ctx.echo(f"{len(objs)} visible object(s): " + ", ".join(parts))
    if by_block:
        ctx.echo("Blocks: " + ", ".join(
            f"{n}× {b}" for b, n in sorted(by_block.items())))
    clouds = [o for o in objs if o.kind == "pointcloud"]
    if clouds:
        points = sum(o.shape.count for o in clouds)
        ctx.echo(f"Points: {points:,} in {len(clouds)} point cloud(s)")
    yield from ()


@command("pointcloud", aliases=("pc",))
def cmd_pointcloud(ctx):
    """Point clouds: `info` says what a scan holds; `subsample` keeps an
    even fraction of its points, which is the cheap way to make a scan
    the laptop can orbit."""
    objs = yield SelectReq("Select point clouds", kinds=("pointcloud",))
    if not objs:
        ctx.echo("No point clouds selected.")
        return
    what = yield OptionReq("Action", options=["info", "subsample"],
                           default="info")
    if what == "info":
        for o in objs:
            c = o.shape
            (x0, y0, z0), (x1, y1, z1) = c.bbox()
            fmt = ctx.scene.format_length
            parts = [f"{c.count:,} points",
                     f"{fmt(x1 - x0)} × {fmt(y1 - y0)} × {fmt(z1 - z0)}",
                     "colour" if c.rgb is not None else "no colour"]
            if c.conf is not None:
                parts.append(f"confidence mean {float(c.conf.mean()):.2f}")
            counts = c.level_counts()
            if counts is not None:
                parts.append("levels " + "/".join(f"{n:,}" for n in counts))
            if c.provenance:
                prov = c.provenance
                parts.append("from " + ", ".join(
                    str(prov[k]) for k in ("backbone", "scale", "session")
                    if prov.get(k)))
            ctx.echo(f"{o.name}: " + "; ".join(parts))
        return
    fraction = yield NumberReq("Fraction of points to keep", default=0.25)
    if not 0 < fraction <= 1:
        ctx.echo("Fraction must be between 0 and 1.")
        return
    for o in objs:
        thinned = o.shape.subsampled(fraction)
        ctx.scene.replace_shape(o.id, thinned)
        ctx.echo(f"{o.name}: {thinned.count:,} points kept.")


@command("meshtobrep")
def cmd_meshtobrep(ctx):
    """Convert mesh objects into exact BREP shells (slow for big meshes)."""
    objs = yield SelectReq("Select meshes to convert", kinds=("mesh",))
    from ..core.mesh import brep_from_mesh
    done = 0
    for o in objs:
        try:
            ctx.scene.replace_shape(o.id, brep_from_mesh(o.shape))
            done += 1
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    ctx.echo(f"Converted {done} mesh(es) to BREP.")


@command("breptomesh", aliases=("meshify",))
def cmd_breptomesh(ctx):
    """Convert BREP objects into lightweight native meshes."""
    objs = yield SelectReq("Select objects to mesh",
                           kinds=("surface", "solid"))
    from ..core.mesh import mesh_from_brep
    done = 0
    for o in objs:
        try:
            ctx.scene.replace_shape(o.id, mesh_from_brep(o.shape))
            done += 1
        except Exception as exc:                              # noqa: BLE001
            ctx.echo(f"{o.name}: {exc}")
    ctx.echo(f"Converted {done} object(s) to mesh.")


@command("purge")
def cmd_purge(ctx):
    """Remove empty layers and unused block definitions."""
    from ..core.layers import DEFAULT_LAYER_ID
    used_layers = {o.layer_id for o in ctx.scene.all()}
    layers = ctx.scene.layers
    keep = used_layers | {DEFAULT_LAYER_ID, layers.current_id}
    # A layer goes only if nothing in its whole branch is wanted: deleting
    # a parent takes its children with it, and an empty Walls with a busy
    # Walls::Interior under it is not an empty layer.
    doomed = {la.id for la in layers.all()
              if not ({la.id, *(d.id for d in layers.descendants(la.id))}
                      & keep)}
    removed_layers = 0
    for layer_id in [i for i in doomed if layers.get(i).parent not in doomed]:
        removed_layers += len(layers.remove(layer_id))
    used_blocks = {o.block_id for o in ctx.scene.all() if o.block_id}
    removed_blocks = 0
    for bid in list(ctx.scene.block_defs):
        if bid not in used_blocks:
            del ctx.scene.block_defs[bid]
            removed_blocks += 1
    ctx.scene.notify()
    ctx.echo(f"Purged {removed_layers} empty layer(s) and "
             f"{removed_blocks} unused block definition(s).")
    yield from ()


@command("what", mutates=False)
def cmd_what(ctx):
    """Report details of the selected objects."""
    objs = yield SelectReq("Select objects to describe")
    for o in objs:
        layer = ctx.scene.layers.get(o.layer_id)
        lines = [f"{o.name} — {o.kind}",
                 f"  layer: {layer.name if layer else o.layer_id}"]
        try:
            if o.kind == "curve":
                closed = g.is_closed_curve(o.shape)
                lines.append(f"  length: {g.curve_length(o.shape):.4g}"
                             f"  ({'closed' if closed else 'open'})")
            elif o.kind == "surface":
                lines.append(f"  area: {g.surface_area(o.shape):.4g}")
            elif o.kind == "solid":
                lines.append(f"  area: {g.surface_area(o.shape):.4g}"
                             f"  volume: {g.volume(o.shape):.4g}")
            elif o.kind == "point":
                x, y, z = g.point_coords(o.shape)
                lines.append(f"  at: {x:g}, {y:g}, {z:g}")
            (mn, mx) = g.bbox(o.shape)
            lines.append("  bbox: "
                         f"({mn[0]:.4g}, {mn[1]:.4g}, {mn[2]:.4g}) to "
                         f"({mx[0]:.4g}, {mx[1]:.4g}, {mx[2]:.4g})")
            valid = g.is_valid(o.shape)
            if not valid:
                lines.append("  WARNING: geometry is invalid")
        except Exception as exc:
            lines.append(f"  (analysis failed: {exc})")
        ctx.echo("\n".join(lines))
    if not objs:
        ctx.echo("Nothing selected.")


@command("matchprops", aliases=("matchproperties",))
def cmd_matchprops(ctx):
    """Copy an object's layer, colour, material, print width and hatch.

    From one object to others, the section hatch and print width coming
    over as overrides only where the source had them."""
    src = yield SelectReq("Select source object", max_count=1)
    targets = yield SelectReq("Select objects to change",
                              allow_preselected=False)
    s = src[0]
    targets = [o for o in targets if o.id != s.id]
    # one notification, not one a target; not update_many, since each
    # target gets its own copy of the material
    with ctx.scene.batched():
        for o in targets:
            ctx.scene.update(o.id, layer_id=s.layer_id, color=s.color,
                             material=dict(s.material) if s.material else None,
                             print_width=s.print_width,
                             section_fill=(dict(s.section_fill)
                                           if s.section_fill else None))
    ctx.echo(f"Matched properties on {len(targets)} object(s) from {s.name}.")


@command("linetype", aliases=("lt", "setlinetype"))
def cmd_linetype(ctx):
    """Set the dash style of selected objects (Continuous/Dashed/…/ByLayer)."""
    from ..core import linetype as lt
    objs = yield SelectReq("Select objects to set linetype")
    if not objs:
        ctx.echo("Nothing selected.")
        return
    style = yield OptionReq("Linetype", options=["ByLayer", *lt.LINETYPES],
                            default="ByLayer")
    ctx.scene.update_many([o.id for o in objs], linetype=style)
    ctx.echo(f"Set linetype '{style}' on {len(objs)} object(s).")


@command("printwidth", aliases=("plotweight", "printweight"))
def cmd_printwidth(ctx):
    """Set the pen width selected objects plot with, or ByLayer.

    A width of their own in millimetres, Default for the printer's, or
    ByLayer to take their layer's again."""
    objs = yield SelectReq("Select objects to set print width")
    if not objs:
        ctx.echo("Nothing selected.")
        return
    answer = yield TextReq("Print width in mm, Default or ByLayer",
                           default="ByLayer")
    text = (answer or "ByLayer").strip().lower().removesuffix("mm").strip()
    if text in ("bylayer", "by layer"):
        width, said = None, "ByLayer"
    elif text == "default":
        width, said = 0.0, "Default"
    else:
        try:
            width = max(0.0, float(text))
        except ValueError:
            ctx.echo(f"Not a print width: '{answer}'.")
            return
        said = f"{width:g} mm"
    ctx.scene.update_many([o.id for o in objs], print_width=width)
    ctx.echo(f"Set print width {said} on {len(objs)} object(s).")


@command("setusertext", aliases=("setattributeusertext",))
def cmd_setusertext(ctx):
    """Set a key of user text on the selected objects, as Rhino's
    SetUserText does.

    The key, then its value; no value takes the key away. A key already
    there under another case is the same key, and keeps its spelling."""
    from ..core import user_text
    objs = yield SelectReq("Select objects to set user text on")
    if not objs:
        ctx.echo("Nothing selected.")
        return
    key = ((yield TextReq("Key")) or "").strip()
    if not key:
        ctx.echo("A key needs a name.")
        return
    value = yield TextReq(f"Value for {key} (Enter for none, which takes "
                          "the key away)", default="")
    with ctx.scene.batched():
        for o in objs:
            ctx.scene.update(o.id, user_text=user_text.with_value(
                o.user_text, key, value))
    ctx.echo(f"Set {key} = {value} on {len(objs)} object(s)." if value
             else f"Took {key} off {len(objs)} object(s).")


@command("getusertext", mutates=False)
def cmd_getusertext(ctx):
    """Report the user text on the selected objects, as Rhino's
    GetUserText does: one key's value, or with Enter every key."""
    from ..core import user_text
    objs = yield SelectReq("Select objects to read user text from")
    if not objs:
        ctx.echo("Nothing selected.")
        return
    key = ((yield TextReq("Key (Enter for all of them)", default=""))
           or "").strip()
    for o in objs:
        text = o.user_text or {}
        if key:
            held = user_text.key_in(text, key)
            ctx.echo(f"{o.name}: {held} = {text[held]}" if held is not None
                     else f"{o.name} has no {key}.")
        elif text:
            ctx.echo("\n".join([f"{o.name}:", *(f"  {k} = {v}"
                                                for k, v in text.items())]))
        else:
            ctx.echo(f"{o.name} has no user text.")


@command("sectionhatch", aliases=("sectionstyle",))
def cmd_sectionhatch(ctx):
    """Set how a section cut through selected objects is filled.

    ByLayer, or a hatch of their own, which starts from the first one's
    layer's angle, spacing and colour."""
    from ..core.layers import section_fill_dict
    from ..core.layout import SECTION_FILLS
    objs = yield SelectReq("Select objects to set section hatch")
    if not objs:
        ctx.echo("Nothing selected.")
        return
    pattern = yield OptionReq(
        "Section hatch",
        options=["ByLayer", *(p.capitalize() for p in SECTION_FILLS)],
        default="ByLayer")
    if pattern == "ByLayer":
        ctx.scene.update_many([o.id for o in objs], section_fill=None)
        ctx.echo(f"{len(objs)} object(s) hatched by layer.")
        return
    layer = ctx.scene.layers.get(objs[0].layer_id)
    angle, spacing = layer.hatch_angle, layer.hatch_spacing
    if pattern.lower() in ("lines", "cross"):
        angle = yield NumberReq("Hatch angle (degrees)", default=angle)
        spacing = yield NumberReq("Hatch spacing on paper (mm)",
                                  default=spacing, minimum=0.2)
    fill = section_fill_dict(pattern, angle, spacing, layer.hatch_color,
                             layer.cut_line_width, layer.cut_line_color)
    # one notification, not one an object; each gets its own copy
    with ctx.scene.batched():
        for o in objs:
            ctx.scene.update(o.id, section_fill=dict(fill))
    ctx.echo(f"Section hatch {fill['pattern']} on {len(objs)} object(s).")


def _reorder(scene, objs, mode: str):
    orders = [o.draw_order for o in scene.all()] or [0]
    hi, lo = max(orders), min(orders)
    # one notification, not one an object; not update_many, since each
    # object lands at its own order
    with scene.batched():
        for i, o in enumerate(objs):
            if mode == "front":
                scene.update(o.id, draw_order=hi + 1 + i)
            elif mode == "back":
                scene.update(o.id, draw_order=lo - 1 - i)
            elif mode == "forward":
                scene.update(o.id, draw_order=o.draw_order + 1)
            elif mode == "backward":
                scene.update(o.id, draw_order=o.draw_order - 1)


@command("bringtofront", aliases=("bf",))
def cmd_bringtofront(ctx):
    """Draw the selected objects on top of overlapping ones."""
    objs = yield SelectReq("Select objects to bring to front")
    if objs:
        _reorder(ctx.scene, objs, "front")
        ctx.echo(f"Brought {len(objs)} object(s) to front.")


@command("sendtoback", aliases=("sb",))
def cmd_sendtoback(ctx):
    """Draw the selected objects behind overlapping ones."""
    objs = yield SelectReq("Select objects to send to back")
    if objs:
        _reorder(ctx.scene, objs, "back")
        ctx.echo(f"Sent {len(objs)} object(s) to back.")


@command("bringforward", aliases=("bringforwards",))
def cmd_bringforward(ctx):
    """Nudge the selected objects one step towards the front."""
    objs = yield SelectReq("Select objects to bring forward")
    if objs:
        _reorder(ctx.scene, objs, "forward")
        ctx.echo(f"Brought {len(objs)} object(s) forward.")


@command("sendbackward", aliases=("sendbackwards",))
def cmd_sendbackward(ctx):
    """Nudge the selected objects one step towards the back."""
    objs = yield SelectReq("Select objects to send backward")
    if objs:
        _reorder(ctx.scene, objs, "backward")
        ctx.echo(f"Sent {len(objs)} object(s) backward.")


@command("changelayer", aliases=("tolayer",))
def cmd_changelayer(ctx):
    """Move objects to a layer by name (created if missing)."""
    objs = yield SelectReq("Select objects to move to a layer")
    name = yield TextReq("Layer name")
    name = name.strip()
    if not name:
        ctx.echo("No layer name given.")
        return
    layer = ctx.scene.layers.find_by_name(name)
    if layer is None:
        layer = ctx.scene.layers.create(name)
        ctx.echo(f"Created layer {layer.name}.")
    ctx.scene.update_many([o.id for o in objs], layer_id=layer.id)
    ctx.scene.notify("layers")
    ctx.echo(f"Moved {len(objs)} object(s) to {layer.name}.")


@command("audit", mutates=False)
def cmd_audit(ctx):
    """Check every object's geometry for validity."""
    bad = []
    for o in ctx.scene.all():
        try:
            if not g.is_valid(o.shape):
                bad.append(o.name)
        except Exception:
            bad.append(o.name)
    if bad:
        ctx.echo(f"{len(bad)} invalid object(s): " + ", ".join(bad))
    else:
        ctx.echo(f"All {len(ctx.scene.all())} object(s) are valid.")
    yield from ()
