"""Solid editing: edge fillets/chamfers, capping, intersection, contours."""

from ..core import geometry as g
from .base import LengthReq, OptionReq, SelectReq, command


@command("filletedge", aliases=("fe",))
def cmd_filletedge(ctx):
    objs = yield SelectReq("Select solids to fillet",
                           kinds=("solid", "surface"))
    radius = yield LengthReq("Fillet radius", minimum=1e-9)
    done = 0
    for o in objs:
        try:
            ctx.scene.replace_shape(o.id, g.fillet_edges(o.shape, radius))
            done += 1
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    if done:
        ctx.echo(f"Filleted all edges of {done} object(s) at r={radius:g}.")


@command("chamferedge", aliases=("che",))
def cmd_chamferedge(ctx):
    objs = yield SelectReq("Select solids to chamfer",
                           kinds=("solid", "surface"))
    dist = yield LengthReq("Chamfer distance", minimum=1e-9)
    done = 0
    for o in objs:
        try:
            ctx.scene.replace_shape(
                o.id, g.fillet_edges(o.shape, dist, chamfer=True))
            done += 1
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    if done:
        ctx.echo(f"Chamfered {done} object(s) at {dist:g}.")


@command("cap")
def cmd_cap(ctx):
    objs = yield SelectReq("Select open surfaces to cap",
                           kinds=("surface", "solid", "compound"))
    done = 0
    for o in objs:
        try:
            capped = g.cap_holes(o.shape)
            new = ctx.scene.replace_shape(o.id, capped)
            done += 1
            ctx.echo(f"{o.name} -> {new.kind}.")
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    if done:
        ctx.echo(f"Capped {done} object(s).")


@command("intersect", aliases=("int",))
def cmd_intersect(ctx):
    a = yield SelectReq("Select first object", kinds=("surface", "solid"),
                        max_count=1)
    b = yield SelectReq("Select second object", kinds=("surface", "solid"),
                        max_count=1, allow_preselected=False)
    curves = g.intersect_shapes(a[0].shape, b[0].shape)
    for c in curves:
        ctx.scene.add(c)
    ctx.echo(f"Created {len(curves)} intersection curve(s).")


@command("contour")
def cmd_contour(ctx):
    objs = yield SelectReq("Select objects to contour",
                           kinds=("surface", "solid"))
    axis = yield OptionReq("Contour direction",
                           options=["Z", "X", "Y", "CPlane"], default="Z")
    spacing = yield LengthReq("Distance between contours", minimum=1e-9)
    direction = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1),
                 "CPlane": tuple(ctx.cplane.normal)}[axis]
    layer = ctx.scene.layers.find_by_name("Contours")
    layer_id = layer.id if layer else ctx.scene.layers.create(
        "Contours", (0.95, 0.75, 0.35)).id
    total = 0
    for o in objs:
        try:
            levels = g.contour(o.shape, direction, spacing)
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
            continue
        for _, curves in levels:
            for c in curves:
                ctx.scene.add(c, layer_id=layer_id)
                total += 1
    ctx.scene.notify()
    ctx.echo(f"Created {total} contour curve(s) on layer 'Contours' "
             f"(spacing {spacing:g}).")


@command("booleansplit", aliases=("bsplit",))
def cmd_booleansplit(ctx):
    """Split solids with cutters, keeping every piece."""
    targets = yield SelectReq("Select solids to split", kinds=("solid",))
    cutters = yield SelectReq("Select cutting objects",
                              allow_preselected=False)
    total = 0
    for t in targets:
        try:
            pieces = g.split_shape(t.shape, [c.shape for c in cutters])
        except g.GeometryError as exc:
            ctx.echo(f"{t.name}: {exc}")
            continue
        for p in pieces:
            ctx.scene.add(p, layer_id=t.layer_id)
            total += 1
        ctx.scene.remove(t.id)
    ctx.echo(f"Split into {total} piece(s).")
