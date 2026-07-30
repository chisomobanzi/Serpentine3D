"""Solid primitive commands."""

import math


def _dist(a, b) -> float:
    return math.dist(a, b)

from ..core import geometry as g
from .base import PointReq, command


@command("box")
def cmd_box(ctx):
    c1 = yield PointReq("First corner of base")

    def _rect(p):
        return g.make_polyline(
            [c1, (p[0], c1[1], c1[2]), (p[0], p[1], c1[2]),
             (c1[0], p[1], c1[2])], closed=True)

    def _base_sides(p):                 # the base is world-axis, as _rect is
        return (abs(p[0] - c1[0]), abs(p[1] - c1[1]))

    c2 = yield PointReq("Opposite corner of base", rubber_from=c1,
                        preview_fn=_rect, rubber_sides=_base_sides)
    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    up = (0.0, 0.0, 1.0)

    def _box_to(p):
        h = p[2] - c1[2]
        if abs(h) < 1e-9 or abs(dx) < 1e-9 or abs(dy) < 1e-9:
            return None
        base = (c1[0], c1[1], min(c1[2], c1[2] + h))
        return g.make_box(base, dx, dy, abs(h))

    hp = yield PointReq("Height (click, or type a number)",
                        axis_lock=(c2, up), number_from=(c2, up),
                        rubber_from=c2, preview_fn=_box_to)
    shape = _box_to(hp)
    if shape is None:
        ctx.echo("Zero height — no box created.")
        return
    obj = ctx.scene.add(shape)
    ctx.echo(f"Created {obj.name}.")


@command("sphere", aliases=("sph",))
def cmd_sphere(ctx):
    center = yield PointReq("Center of sphere")

    def _sphere_to(p):
        r = _dist(center, p)
        return g.make_sphere(center, r) if r > 1e-9 else None

    rp = yield PointReq("Radius (click, or type a number)",
                        number_from=(center, (1.0, 0.0, 0.0)),
                        rubber_from=center, preview_fn=_sphere_to)
    r = _dist(center, rp)
    if r < 1e-9:
        ctx.echo("Zero radius — no sphere created.")
        return
    obj = ctx.scene.add(g.make_sphere(center, r))
    ctx.echo(f"Created {obj.name} (r={r:g}).")


@command("cylinder", aliases=("cyl",))
def cmd_cylinder(ctx):
    base = yield PointReq("Center of base")

    def _circle_to(p):
        r = _dist(base, p)
        return g.make_circle(base, r) if r > 1e-9 else None

    rp = yield PointReq("Radius (click, or type a number)",
                        number_from=(base, (1.0, 0.0, 0.0)),
                        rubber_from=base, preview_fn=_circle_to)
    r = _dist(base, rp)
    up = (0.0, 0.0, 1.0)

    def _cyl_to(p):
        h = p[2] - base[2]
        if r < 1e-9 or abs(h) < 1e-9:
            return None
        b = (base[0], base[1], min(base[2], base[2] + h))
        return g.make_cylinder(b, r, abs(h))

    hp = yield PointReq("Height (click, or type a number)",
                        axis_lock=(base, up), number_from=(base, up),
                        preview_fn=_cyl_to)
    shape = _cyl_to(hp)
    if shape is None:
        ctx.echo("Zero radius or height — no cylinder created.")
        return
    obj = ctx.scene.add(shape)
    ctx.echo(f"Created {obj.name}.")


@command("cone")
def cmd_cone(ctx):
    base = yield PointReq("Center of base")

    def _circle_to(p):
        r = _dist(base, p)
        return g.make_circle(base, r) if r > 1e-9 else None

    rp = yield PointReq("Base radius (click, or type a number)",
                        number_from=(base, (1.0, 0.0, 0.0)),
                        rubber_from=base, preview_fn=_circle_to)
    r = _dist(base, rp)
    up = (0.0, 0.0, 1.0)

    def _cone_to(p):
        h = p[2] - base[2]
        if r < 1e-9 or h <= 1e-9:
            return None
        return g.make_cone(base, r, 0.0, h)

    hp = yield PointReq("Apex height (click, or type a number)",
                        axis_lock=(base, up), number_from=(base, up),
                        preview_fn=_cone_to)
    shape = _cone_to(hp)
    if shape is None:
        ctx.echo("Zero radius or height — no cone created.")
        return
    obj = ctx.scene.add(shape)
    ctx.echo(f"Created {obj.name}.")


@command("torus")
def cmd_torus(ctx):
    center = yield PointReq("Center of torus")

    def _ring_to(p):
        r = _dist(center, p)
        return g.make_circle(center, r) if r > 1e-9 else None

    rp = yield PointReq("Major radius (click, or type a number)",
                        number_from=(center, (1.0, 0.0, 0.0)),
                        rubber_from=center, preview_fn=_ring_to)
    r1 = _dist(center, rp)
    if r1 < 1e-9:
        ctx.echo("Zero major radius — no torus created.")
        return

    # the tube is dragged out from the ring itself, not from the centre:
    # its thickness is a distance you can see against the circle above
    ring = (center[0] + r1, center[1], center[2])

    def _torus_to(p):
        r2 = _dist(ring, p)
        # r2 >= r1 folds the tube through the middle and OCC will not build it
        if r2 < 1e-9 or r2 >= r1:
            return None
        try:
            return g.make_torus(center, r1, r2)
        except g.GeometryError:
            return None

    tp = yield PointReq("Minor (tube) radius (click, or type a number)",
                        number_from=(ring, (1.0, 0.0, 0.0)),
                        rubber_from=ring, preview_fn=_torus_to)
    shape = _torus_to(tp)
    if shape is None:
        ctx.echo("Tube radius must be greater than zero and smaller than the "
                 "major radius — no torus created.")
        return
    obj = ctx.scene.add(shape)
    ctx.echo(f"Created {obj.name} (R={r1:g}, r={_dist(ring, tp):g}).")
