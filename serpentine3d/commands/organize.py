"""Organisation: groups, locking, blocks."""

import uuid

from ..core import geometry as g
from .base import OptionReq, PointReq, SelectReq, TextReq, command


@command("group")
def cmd_group(ctx):
    objs = yield SelectReq("Select objects to group", min_count=2)
    gid = uuid.uuid4().hex[:8]
    for o in objs:
        ctx.scene.update(o.id, group_id=gid)
    ctx.echo(f"Grouped {len(objs)} object(s) — clicking one now selects "
             "them all.")


@command("ungroup")
def cmd_ungroup(ctx):
    objs = yield SelectReq("Select grouped objects to ungroup")
    n = 0
    for o in objs:
        if o.group_id:
            ctx.scene.update(o.id, group_id=None)
            n += 1
    ctx.echo(f"Ungrouped {n} object(s).")


@command("lock")
def cmd_lock(ctx):
    objs = yield SelectReq("Select objects to lock")
    for o in objs:
        ctx.scene.update(o.id, locked=True)
    ctx.selection.clear()
    ctx.echo(f"Locked {len(objs)} object(s) — visible but unselectable. "
             "'unlockall' releases them.")


@command("unlockall", aliases=("unlock",))
def cmd_unlockall(ctx):
    n = 0
    for o in ctx.scene.all():
        if o.locked:
            ctx.scene.update(o.id, locked=False)
            n += 1
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
    yield from ()


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
    removed_layers = 0
    for layer in list(ctx.scene.layers.all()):
        if (layer.id not in used_layers
                and layer.id != DEFAULT_LAYER_ID
                and layer.id != ctx.scene.layers.current_id):
            ctx.scene.layers.remove(layer.id)
            removed_layers += 1
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
    """Copy layer, colour and material from one object to others."""
    src = yield SelectReq("Select source object", max_count=1)
    targets = yield SelectReq("Select objects to change",
                              allow_preselected=False)
    s = src[0]
    n = 0
    for o in targets:
        if o.id == s.id:
            continue
        ctx.scene.update(o.id, layer_id=s.layer_id, color=s.color,
                         material=dict(s.material) if s.material else None)
        n += 1
    ctx.echo(f"Matched properties on {n} object(s) from {s.name}.")


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
    for o in objs:
        ctx.scene.update(o.id, layer_id=layer.id)
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
