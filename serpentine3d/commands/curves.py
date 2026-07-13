"""Curve creation commands."""

import numpy as np

from ..core import geometry as g
from .base import LengthReq, NumberReq, OptionReq, PointReq, command


def _rubber(pts):
    """Preview segments through a point list."""
    if len(pts) < 2:
        return None
    a = np.asarray(pts, np.float32)
    return np.stack([a[:-1], a[1:]], axis=1)


@command("line", aliases=("l",))
def cmd_line(ctx):
    p1 = yield PointReq("Start of line")
    p2 = yield PointReq("End of line", rubber_from=p1)
    obj = ctx.scene.add(g.make_line(p1, p2))
    ctx.echo(f"Created {obj.name}.")


@command("polyline", aliases=("pl", "pline"))
def cmd_polyline(ctx):
    pts = [(yield PointReq("Start of polyline"))]
    while True:
        prompt = ("Next point" if len(pts) < 2
                  else "Next point (Enter to finish, c to close)")
        req = PointReq(prompt, rubber_pts=list(pts),
                       allow_empty=len(pts) >= 2,
                       extra_options=("close",) if len(pts) >= 3 else ())
        p = yield req
        if p is None:
            break
        if p == "close":
            obj = ctx.scene.add(g.make_polyline(pts, closed=True))
            ctx.echo(f"Created closed {obj.name}.")
            return
        pts.append(p)
    obj = ctx.scene.add(g.make_polyline(pts))
    ctx.echo(f"Created {obj.name} with {len(pts)} points.")


@command("curve", aliases=("cv", "interpcrv"))
def cmd_curve(ctx):
    """NURBS curve interpolated through picked points."""
    pts = [(yield PointReq("First point of curve"))]
    while True:
        req = PointReq("Next point (Enter to finish)",
                       rubber_pts=list(pts), allow_empty=len(pts) >= 2)
        p = yield req
        if p is None:
            break
        pts.append(p)
    obj = ctx.scene.add(g.make_interp_curve(pts))
    ctx.echo(f"Created {obj.name} through {len(pts)} points.")


@command("circle", aliases=("c", "ci"))
def cmd_circle(ctx):
    center = yield PointReq("Center of circle")
    r = yield LengthReq("Radius", minimum=1e-9)
    obj = ctx.scene.add(g.make_circle(center, r,
                                      normal=tuple(ctx.cplane.normal)))
    ctx.echo(f"Created {obj.name} (r={r:g}).")


@command("arc", aliases=("a",))
def cmd_arc(ctx):
    p1 = yield PointReq("Start of arc")
    p2 = yield PointReq("Point on arc", rubber_from=p1)
    p3 = yield PointReq("End of arc", rubber_from=p2)
    obj = ctx.scene.add(g.make_arc_3pt(p1, p2, p3))
    ctx.echo(f"Created {obj.name}.")


@command("ellipse", aliases=("el",))
def cmd_ellipse(ctx):
    center = yield PointReq("Center of ellipse")
    r1 = yield LengthReq("Major radius", minimum=1e-9)
    r2 = yield LengthReq("Minor radius", minimum=1e-9)
    obj = ctx.scene.add(g.make_ellipse(center, r1, r2))
    ctx.echo(f"Created {obj.name}.")


@command("rectangle", aliases=("rect", "rec"))
def cmd_rectangle(ctx):
    c1 = yield PointReq("First corner")
    c2 = yield PointReq("Opposite corner", rubber_from=c1)
    cp = ctx.cplane
    if cp.is_world_xy():
        obj = ctx.scene.add(g.make_rectangle(c1, c2))
    else:
        u1, v1, _ = cp.from_world(c1)
        u2, v2, _ = cp.from_world(c2)
        if abs(u2 - u1) < 1e-9 or abs(v2 - v1) < 1e-9:
            from ..core.geometry import GeometryError
            raise GeometryError("Degenerate rectangle")
        pts = [cp.to_world(u1, v1), cp.to_world(u2, v1),
               cp.to_world(u2, v2), cp.to_world(u1, v2)]
        obj = ctx.scene.add(g.make_polyline(pts, closed=True))
    ctx.echo(f"Created {obj.name}.")
