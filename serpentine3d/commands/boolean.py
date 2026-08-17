"""Boolean operations."""

from functools import reduce

from ..core import geometry as g
from .base import SelectReq, command

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
