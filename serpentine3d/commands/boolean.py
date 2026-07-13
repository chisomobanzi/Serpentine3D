"""Boolean operations."""

from functools import reduce

from ..core import geometry as g
from .base import SelectReq, command

_SOLIDISH = ("solid", "surface", "compound")


@command("booleanunion", aliases=("union", "bu"))
def cmd_union(ctx):
    objs = yield SelectReq("Select 2 or more solids to union",
                           kinds=_SOLIDISH, min_count=2)
    result = reduce(lambda a, b: g.boolean_union(a, b),
                    (o.shape for o in objs))
    for o in objs[1:]:
        ctx.scene.remove(o.id)
    new = ctx.scene.replace_shape(objs[0].id, result)
    ctx.echo(f"Union of {len(objs)} objects -> {new.name}.")


@command("booleandifference", aliases=("difference", "bd"))
def cmd_difference(ctx):
    keep = yield SelectReq("Select solids to subtract FROM",
                           kinds=_SOLIDISH)
    cut = yield SelectReq("Select solids to subtract WITH",
                          kinds=_SOLIDISH, allow_preselected=False)
    cut_union = reduce(lambda a, b: g.boolean_union(a, b),
                       (o.shape for o in cut))
    for o in keep:
        ctx.scene.replace_shape(o.id, g.boolean_difference(o.shape,
                                                           cut_union))
    for o in cut:
        ctx.scene.remove(o.id)
    ctx.echo(f"Subtracted {len(cut)} object(s) from {len(keep)}.")


@command("booleanintersection", aliases=("intersection", "bi"))
def cmd_intersection(ctx):
    objs = yield SelectReq("Select 2 or more solids to intersect",
                           kinds=_SOLIDISH, min_count=2)
    result = reduce(lambda a, b: g.boolean_intersection(a, b),
                    (o.shape for o in objs))
    for o in objs[1:]:
        ctx.scene.remove(o.id)
    new = ctx.scene.replace_shape(objs[0].id, result)
    ctx.echo(f"Intersection -> {new.name}.")
