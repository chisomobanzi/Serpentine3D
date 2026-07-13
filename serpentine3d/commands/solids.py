"""Solid primitive commands."""

from ..core import geometry as g
from .base import LengthReq, NumberReq, PointReq, command


@command("box")
def cmd_box(ctx):
    c1 = yield PointReq("First corner of base")
    c2 = yield PointReq("Opposite corner of base", rubber_from=c1)
    h = yield LengthReq("Height", default=10.0)
    dx, dy = c2[0] - c1[0], c2[1] - c1[1]
    obj = ctx.scene.add(g.make_box(c1, dx, dy, h))
    ctx.echo(f"Created {obj.name}.")


@command("sphere", aliases=("sph",))
def cmd_sphere(ctx):
    center = yield PointReq("Center of sphere")
    r = yield LengthReq("Radius", minimum=1e-9)
    obj = ctx.scene.add(g.make_sphere(center, r))
    ctx.echo(f"Created {obj.name} (r={r:g}).")


@command("cylinder", aliases=("cyl",))
def cmd_cylinder(ctx):
    base = yield PointReq("Center of base")
    r = yield LengthReq("Radius", minimum=1e-9)
    h = yield LengthReq("Height", default=10.0)
    obj = ctx.scene.add(g.make_cylinder(base, r, h))
    ctx.echo(f"Created {obj.name}.")


@command("cone")
def cmd_cone(ctx):
    base = yield PointReq("Center of base")
    r = yield LengthReq("Base radius", minimum=1e-9)
    h = yield LengthReq("Height", default=10.0)
    obj = ctx.scene.add(g.make_cone(base, r, 0.0, h))
    ctx.echo(f"Created {obj.name}.")


@command("torus")
def cmd_torus(ctx):
    center = yield PointReq("Center of torus")
    r1 = yield LengthReq("Major radius", minimum=1e-9)
    r2 = yield LengthReq("Minor (tube) radius", minimum=1e-9)
    obj = ctx.scene.add(g.make_torus(center, r1, r2))
    ctx.echo(f"Created {obj.name}.")
