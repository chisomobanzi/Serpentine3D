"""Picking the regions a set of curves cuts their plane into.

Rhino calls this boundary mode, and two commands want it: CurveBoolean,
which brings a closed curve back around what you kept, and Hatch, which
fills it (#45). Both ask the same question in the same way, so they ask
it from here: click a region to keep it, click it again to let it go, or
All (Alt+A) for every one of them, with the result ghosted as you move.

When to ask at all is each command's own business, and neither asks when
the answer is already there: a single closed curve is its own boundary,
and Hatch also fills curves that lie apart, or one inside another, with
nothing to pick, since there is only one thing those can mean.
"""

from __future__ import annotations

from ..core import geometry as g
from .base import PointReq


def coplanar_curves(ctx, curves):
    """`curves` that share the first one's plane, with (origin, normal).

    Returns (kept, origin, normal). Anything off the plane is dropped with
    a word about it, since a region needs its curves on one plane and a
    stray one would otherwise fail deep in the kernel.
    """
    first = g.planar_face(curves[0].shape)
    normal = g.face_normal(first)
    origin = g.centroid(first)
    kept = []
    for o in curves:
        off = max(
            abs(sum((a - b) * n for a, b, n in zip(p, origin, normal)))
            for p in g.sample_curve(o.shape, 8))
        if off > g.tol():
            ctx.echo(f"Skipped {o.name}, not on the plane of the other "
                     "curves.")
        else:
            kept.append(o)
    return kept, origin, normal


def pick_regions(ctx, regions, origin, normal,
                 prompt="Pick region to keep (Enter to finish)",
                 choices=None):
    """Which of `regions` to keep, as a sorted list of indices.

    A generator, so a command drives it with `yield from`. Empty when the
    pick was finished without keeping anything, which the caller reads as
    "nothing to do" rather than as an error.

    `choices` are the command's own option chips. They belong on this
    prompt as well as on the selection it came from: a command run on a
    preselection never shows that one, and an option nobody can see is an
    option nobody has.
    """
    kept: set = set()
    # The ghost is a merge of the kept faces plus the hovered one, and a
    # merge is the expensive part of every mousemove: cache it per
    # (hovered, kept) pair and only rebuild when one of them changes.
    ghost_cache: dict = {}

    def _ghost(p):
        hit = None
        if isinstance(p, (tuple, list)):
            try:
                hit, _ = g.region_containing(regions, p, origin, normal)
            except g.GeometryError:
                hit = None
        key = (hit, tuple(sorted(kept)))
        if key in ghost_cache:
            return ghost_cache[key]
        shape = None
        if hit is not None or kept:
            sel = set(kept)
            if hit is not None:
                sel.add(hit)
            try:
                shape = g.merge_planar_regions(
                    [regions[i] for i in sorted(sel)])
            except g.GeometryError:
                shape = None
        ghost_cache[key] = shape
        return shape

    while True:
        p = yield PointReq(prompt, allow_empty=True, extra_options=("All",),
                           rubber_band=False, preview_fn=_ghost,
                           choices=choices)
        if p is None:
            break
        if p == "All":
            kept = set(range(len(regions)))
            ctx.echo("All regions kept, click one to remove it, "
                     "Enter to finish.")
            continue
        try:
            hit, state = g.region_containing(regions, p, origin, normal)
        except g.GeometryError:
            hit, state = None, "out"
        if state == "on":
            ctx.echo("That point is on a curve, click inside a region.")
            continue
        if hit is None:
            ctx.echo("Not inside a region.")
            continue
        if hit in kept:
            kept.remove(hit)
            ctx.echo(f"Region {hit + 1} removed.")
        else:
            kept.add(hit)
            ctx.echo(f"Region {hit + 1} kept.")
    return sorted(kept)
