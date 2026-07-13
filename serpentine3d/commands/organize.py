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
