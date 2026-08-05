"""Solid primitive commands."""

import math


def _dist(a, b) -> float:
    return math.dist(a, b)

from ..core import geometry as g
from .base import PointReq, command, quadrant


@command("box")
def cmd_box(ctx):
    c1 = yield PointReq("First corner of base")
    cp = ctx.cplane
    u1, v1, w1 = cp.from_world(c1)

    def _rect(u2, v2):
        return g.make_polyline(
            [cp.to_world(u1, v1, w1), cp.to_world(u2, v1, w1),
             cp.to_world(u2, v2, w1), cp.to_world(u1, v2, w1)], closed=True)

    def _rect_to(p):
        u2, v2, _w = cp.from_world(p)
        if abs(u2 - u1) < 1e-9 or abs(v2 - v1) < 1e-9:
            return None
        return _rect(u2, v2)

    def _base_sides(p):        # the base has sides of its own on the plane
        u2, v2, _w = cp.from_world(p)
        return (abs(u2 - u1), abs(v2 - v1))

    # "or length" the way Rhino's box reads it: one number is a side and the
    # width is asked for next. The general rule for a point prompt — a number
    # is how far along the way you are pointing — would make it the diagonal,
    # and under ortho the cursor is square to the CPlane, so the base would
    # come out a line and the complaint would be about a height nobody had
    # been asked for.
    c2 = yield PointReq("Opposite corner of base, or length", rubber_from=c1,
                        preview_fn=_rect_to, rubber_sides=_base_sides,
                        allow_number=True)
    if isinstance(c2, float):
        if abs(c2) < 1e-9:
            ctx.echo("Zero length — no box created.")
            return
        su, sv = quadrant(ctx, cp)
        far_u = u1 + su * c2
        edge = cp.to_world(far_u, v1, w1)
        vdir = tuple(float(sv * a) for a in cp.ydir)

        def _wide_to(p):
            return _rect_to(cp.to_world(far_u, cp.from_world(p)[1], w1))

        wp = yield PointReq("Width (click, or type a number)",
                            axis_lock=(edge, vdir), number_from=(edge, vdir),
                            rubber_from=edge, preview_fn=_wide_to,
                            rubber_sides=lambda p: (
                                abs(c2), abs(cp.from_world(p)[1] - v1)))
        c2 = cp.to_world(far_u, cp.from_world(wp)[1], w1)
    u2, v2, _w = cp.from_world(c2)
    # the height goes up out of the plane you drew the base on, which in a
    # Front pane is towards you and not towards the sky
    up = tuple(float(a) for a in cp.normal)

    def _box_to(p):
        h = cp.from_world(p)[2] - w1
        if abs(h) < 1e-9:
            return None
        return g.extrude(g.planar_face(_rect(u2, v2)), up, h)

    if abs(u2 - u1) < 1e-9 or abs(v2 - v1) < 1e-9:
        ctx.echo("Zero width — no box created.")
        return
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
                        number_from=(center, tuple(ctx.cplane.xdir)),
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
    cp = ctx.cplane
    # the disc lies on the plane you are drawing on and the barrel runs up
    # out of it, so a cylinder started in Front comes at you rather than
    # standing on end somewhere off to the side
    up = tuple(float(a) for a in cp.normal)
    w0 = cp.from_world(base)[2]

    def _circle_to(p):
        r = _dist(base, p)
        return g.make_circle(base, r, up) if r > 1e-9 else None

    rp = yield PointReq("Radius (click, or type a number)",
                        number_from=(base, tuple(cp.xdir)),
                        rubber_from=base, preview_fn=_circle_to)
    r = _dist(base, rp)

    def _cyl_to(p):
        h = cp.from_world(p)[2] - w0
        if r < 1e-9 or abs(h) < 1e-9:
            return None
        b = base if h > 0 else cp.to_world(*cp.from_world(base)[:2], w0 + h)
        return g.make_cylinder(b, r, abs(h), up)

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
    cp = ctx.cplane
    up = tuple(float(a) for a in cp.normal)
    w0 = cp.from_world(base)[2]

    def _circle_to(p):
        r = _dist(base, p)
        return g.make_circle(base, r, up) if r > 1e-9 else None

    rp = yield PointReq("Base radius (click, or type a number)",
                        number_from=(base, tuple(cp.xdir)),
                        rubber_from=base, preview_fn=_circle_to)
    r = _dist(base, rp)

    def _cone_to(p):
        h = cp.from_world(p)[2] - w0
        if r < 1e-9 or h <= 1e-9:
            return None
        return g.make_cone(base, r, 0.0, h, up)

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
    cp = ctx.cplane
    up = tuple(float(a) for a in cp.normal)

    def _ring_to(p):
        r = _dist(center, p)
        return g.make_circle(center, r, up) if r > 1e-9 else None

    rp = yield PointReq("Major radius (click, or type a number)",
                        number_from=(center, tuple(cp.xdir)),
                        rubber_from=center, preview_fn=_ring_to)
    r1 = _dist(center, rp)
    if r1 < 1e-9:
        ctx.echo("Zero major radius — no torus created.")
        return

    # the tube is dragged out from the ring itself, not from the centre:
    # its thickness is a distance you can see against the circle above
    u, v, w = cp.from_world(center)
    ring = cp.to_world(u + r1, v, w)

    def _torus_to(p):
        r2 = _dist(ring, p)
        # r2 >= r1 folds the tube through the middle and OCC will not build it
        if r2 < 1e-9 or r2 >= r1:
            return None
        try:
            return g.make_torus(center, r1, r2, up)
        except g.GeometryError:
            return None

    tp = yield PointReq("Minor (tube) radius (click, or type a number)",
                        number_from=(ring, tuple(cp.xdir)),
                        rubber_from=ring, preview_fn=_torus_to)
    shape = _torus_to(tp)
    if shape is None:
        ctx.echo("Tube radius must be greater than zero and smaller than the "
                 "major radius — no torus created.")
        return
    obj = ctx.scene.add(shape)
    ctx.echo(f"Created {obj.name} (R={r1:g}, r={_dist(ring, tp):g}).")
