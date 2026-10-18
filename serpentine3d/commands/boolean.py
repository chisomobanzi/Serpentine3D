"""Boolean operations."""

from functools import reduce

from ..core import geometry as g
from .base import CancelCommand, SelectReq, command
from .regions import coplanar_curves, pick_regions

_SOLIDISH = ("solid", "surface", "compound")


def _place(ctx, obj, shape) -> list:
    """Put a boolean's result where `obj` was, one object per loose piece.

    A cut that falls right through hands back a compound with a solid in it
    per piece, and keeping that as one object is what let a bar go on being
    a single bar after being sawn in half: one name, one gumball between
    the halves, and both moving together. Anything still joined comes back
    as a single solid and is placed as one object, so this only ever
    separates what is genuinely no longer connected.

    The first piece keeps the id, so a name, a layer and anything built
    from this object survive the cut rather than being replaced by
    strangers.
    """
    pieces = g.loose_pieces(shape)
    if not pieces:
        return [ctx.scene.replace_shape(obj.id, shape)]
    out = [ctx.scene.replace_shape(obj.id, pieces[0])]
    out.extend(ctx.scene.add(p, layer_id=obj.layer_id) for p in pieces[1:])
    return out


@command("booleanunion", aliases=("union", "bu"))
def cmd_union(ctx):
    objs = yield SelectReq("Select 2 or more solids to union",
                           kinds=_SOLIDISH, min_count=2)
    result = reduce(lambda a, b: g.boolean_union(a, b),
                    (o.shape for o in objs))
    for o in objs[1:]:
        ctx.scene.remove(o.id)
    made = _place(ctx, objs[0], result)
    ctx.select_result(made)
    names = ", ".join(o.name for o in made)
    ctx.echo(f"Union of {len(objs)} objects -> {names}.")


@command("booleandifference", aliases=("difference", "bd"))
def cmd_difference(ctx):
    keep = yield SelectReq("Select solids to subtract FROM",
                           kinds=_SOLIDISH)
    cut = yield SelectReq("Select solids to subtract WITH",
                          kinds=_SOLIDISH, allow_preselected=False)
    cut_union = reduce(lambda a, b: g.boolean_union(a, b),
                       (o.shape for o in cut))
    made = []
    for o in keep:
        made += _place(ctx, o, g.boolean_difference(o.shape, cut_union))
    for o in cut:
        ctx.scene.remove(o.id)
    ctx.select_result(made)
    extra = (f", leaving {len(made)} piece(s)" if len(made) != len(keep)
             else "")
    ctx.echo(f"Subtracted {len(cut)} object(s) from {len(keep)}{extra}.")


@command("booleanintersection", aliases=("intersection", "bi"))
def cmd_intersection(ctx):
    objs = yield SelectReq("Select 2 or more solids to intersect",
                           kinds=_SOLIDISH, min_count=2)
    result = reduce(lambda a, b: g.boolean_intersection(a, b),
                    (o.shape for o in objs))
    for o in objs[1:]:
        ctx.scene.remove(o.id)
    made = _place(ctx, objs[0], result)
    ctx.select_result(made)
    ctx.echo(f"Intersection -> {', '.join(o.name for o in made)}.")


@command("curveboolean", aliases=("curvebool",))
def cmd_curveboolean(ctx):
    """Closed curves around the regions of overlapping planar curves.

    The curves divide their plane into regions the way a Venn diagram does,
    and the pick says which regions to keep: click one to keep it (click
    again to let it go), or All — Alt+A — to keep every region. Enter
    finishes, and a closed curve comes back around each kept outline, the
    seams between neighbouring regions fused away.

    Boundary mode, Rhino's term for this whole business, is off for a
    single closed curve: its boundary is itself and there is nothing to
    boolean it with, so the curve stands as it is. Regions that only
    touch at a point — two squares sharing a corner — come back as two
    curves meeting there: a cut that falls through a point does not join
    outlines.

    The curves are consumed, as they always were. KeepObjects leaves them
    where they are instead, for when the same outlines are about to be
    booleaned another way or are the construction the drawing is set out
    from.
    """
    objs = yield SelectReq("Select planar closed curves to boolean",
                           kinds=("curve",), min_count=1,
                           choices={"KeepObjects": ["No", "Yes"]})
    closed = []
    for o in objs:
        if g.is_closed_curve(o.shape):
            closed.append(o)
        else:
            ctx.echo(f"Skipped {o.name}, open curves cannot bound a region.")
    if not closed:
        raise CancelCommand
    if len(closed) == 1:
        # Boundary mode off: the curve is its own boundary already. Nothing
        # changed, so the checkpoint is dropped — no no-op undo step.
        ctx.select_result(closed)
        ctx.echo("One closed curve, boundary mode off, nothing to boolean.")
        ctx.history.discard_checkpoint()
        return
    try:
        coplanar, origin, normal = coplanar_curves(ctx, closed)
    except g.GeometryError as exc:
        ctx.echo(f"{exc}")
        raise CancelCommand
    if len(coplanar) < 2:
        if coplanar:
            # One curve left on the plane: boundary mode off for it too.
            ctx.select_result(coplanar)
            ctx.echo("One curve left on the plane, boundary mode off, "
                     "nothing to boolean.")
            ctx.history.discard_checkpoint()
            return
        ctx.echo("No curves share a plane to boolean.")
        raise CancelCommand
    try:
        regions = g.curve_regions([o.shape for o in coplanar])
    except g.GeometryError as exc:
        ctx.echo(f"{exc}")
        raise CancelCommand
    if not regions:
        ctx.echo("The curves share no usable regions.")
        raise CancelCommand
    kept = yield from pick_regions(
        ctx, regions, origin, normal,
        choices={"KeepObjects": ["No", "Yes"]})
    if not kept:
        ctx.echo("No regions kept — nothing to boolean.")
        raise CancelCommand
    try:
        merged = g.merge_planar_regions([regions[i] for i in kept])
        wires = g.free_boundaries(merged)
        # Outer loops first, holes after: the order FreeBounds hands the
        # boundaries back in is not a promise, and the bigger the loop
        # the further out it is.
        wires.sort(key=lambda w: -g.surface_area(g.planar_face(w)))
    except g.GeometryError as exc:
        ctx.echo(f"{exc}")
        raise CancelCommand
    made = [ctx.scene.add(w, layer_id=coplanar[0].layer_id) for w in wires]
    if ctx.opt("KeepObjects", "No") == "No":
        for o in coplanar:
            ctx.scene.remove(o.id)
    ctx.select_result(made)
    ctx.echo(f"CurveBoolean -> {len(made)} curve(s)"
             + (", curves kept." if ctx.opt("KeepObjects", "No") == "Yes"
                else "."))
