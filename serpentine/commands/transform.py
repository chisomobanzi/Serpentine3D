"""Transform commands: move, copy, rotate, scale, mirror, array."""

from ..core import geometry as g
from .base import IntReq, LengthReq, NumberReq, OptionReq, PointReq, SelectReq, command


@command("move", aliases=("m",))
def cmd_move(ctx):
    objs = yield SelectReq("Select objects to move")
    p1 = yield PointReq("Point to move from")
    p2 = yield PointReq("Point to move to", rubber_from=p1)
    offset = tuple(b - a for a, b in zip(p1, p2))
    for o in objs:
        ctx.scene.replace_shape(o.id, g.translate(o.shape, offset))
    ctx.echo(f"Moved {len(objs)} object(s).")


@command("copy", aliases=("co", "cp"))
def cmd_copy(ctx):
    objs = yield SelectReq("Select objects to copy")
    p1 = yield PointReq("Point to copy from")
    count = 0
    while True:
        p2 = yield PointReq("Point to copy to (Enter to finish)",
                            rubber_from=p1, allow_empty=count > 0)
        if p2 is None:
            break
        offset = tuple(b - a for a, b in zip(p1, p2))
        for o in objs:
            ctx.scene.add(g.translate(o.shape, offset),
                          name=None, layer_id=o.layer_id)
        count += 1
    ctx.echo(f"Copied {len(objs)} object(s) {count} time(s).")


@command("rotate", aliases=("ro",))
def cmd_rotate(ctx):
    objs = yield SelectReq("Select objects to rotate")
    center = yield PointReq("Center of rotation")
    angle = yield NumberReq("Angle in degrees (around the CPlane normal)")
    axis = tuple(ctx.cplane.normal)
    for o in objs:
        ctx.scene.replace_shape(
            o.id, g.rotate(o.shape, center, axis, angle))
    ctx.echo(f"Rotated {len(objs)} object(s) by {angle:g} degrees.")


@command("scale", aliases=("sc",))
def cmd_scale(ctx):
    objs = yield SelectReq("Select objects to scale")
    center = yield PointReq("Base point")
    factor = yield NumberReq("Scale factor")
    for o in objs:
        ctx.scene.replace_shape(o.id, g.scale(o.shape, center, factor))
    ctx.echo(f"Scaled {len(objs)} object(s) by {factor:g}.")


@command("scalenu")
def cmd_scale_nu(ctx):
    objs = yield SelectReq("Select objects to scale (non-uniform)")
    center = yield PointReq("Base point")
    sx = yield NumberReq("X factor", default=1.0)
    sy = yield NumberReq("Y factor", default=1.0)
    sz = yield NumberReq("Z factor", default=1.0)
    for o in objs:
        ctx.scene.replace_shape(
            o.id, g.scale(o.shape, center, 1.0, factors=(sx, sy, sz)))
    ctx.echo(f"Scaled {len(objs)} object(s).")


@command("mirror", aliases=("mi",))
def cmd_mirror(ctx):
    objs = yield SelectReq("Select objects to mirror")
    p1 = yield PointReq("Start of mirror line")
    p2 = yield PointReq("End of mirror line", rubber_from=p1)
    keep = yield OptionReq("Keep original?", options=["Yes", "No"],
                           default="Yes")
    # mirror across the plane through the picked line, perpendicular to
    # the construction plane
    import numpy as np
    line = np.subtract(p2, p1)
    normal = np.cross(ctx.cplane.normal, line)
    if np.linalg.norm(normal) < 1e-12:
        normal = ctx.cplane.xdir
    normal = tuple(float(c) for c in normal)
    for o in objs:
        mirrored = g.mirror(o.shape, p1, normal)
        if keep == "Yes":
            ctx.scene.add(mirrored, layer_id=o.layer_id)
        else:
            ctx.scene.replace_shape(o.id, mirrored)
    ctx.echo(f"Mirrored {len(objs)} object(s).")


@command("arraypolar")
def cmd_array_polar(ctx):
    objs = yield SelectReq("Select objects to array")
    center = yield PointReq("Center of polar array")
    count = yield IntReq("Number of items", default=6, minimum=2)
    total = yield NumberReq("Angle to fill (degrees)", default=360.0)
    step = total / (count if abs(total - 360.0) < 1e-9 else count - 1)
    n = 0
    for i in range(1, count):
        for o in objs:
            ctx.scene.add(g.rotate(o.shape, center, (0, 0, 1), step * i),
                          layer_id=o.layer_id)
            n += 1
    ctx.echo(f"Created {n} arrayed object(s) around {center}.")


@command("arraypath", aliases=("arraycrv",))
def cmd_array_path(ctx):
    objs = yield SelectReq("Select objects to array")
    paths = yield SelectReq("Select path curve", kinds=("curve",),
                            max_count=1, allow_preselected=False)
    count = yield IntReq("Number of items", default=6, minimum=2)
    base = yield PointReq("Base point on the object(s)")
    samples = g.sample_curve(paths[0].shape, count)
    n = 0
    for target in samples:
        offset = tuple(t - b for t, b in zip(target, base))
        if all(abs(c) < 1e-12 for c in offset):
            continue
        for o in objs:
            ctx.scene.add(g.translate(o.shape, offset),
                          layer_id=o.layer_id)
            n += 1
    ctx.echo(f"Placed {n} object(s) along {paths[0].name}.")


@command("array")
def cmd_array(ctx):
    objs = yield SelectReq("Select objects to array")
    nx = yield IntReq("Count X", default=2, minimum=1)
    ny = yield IntReq("Count Y", default=1, minimum=1)
    dx = yield LengthReq("Spacing X", default=10.0)
    dy = 0.0
    if ny > 1:
        dy = yield LengthReq("Spacing Y", default=10.0)
    n = 0
    for i in range(nx):
        for j in range(ny):
            if i == 0 and j == 0:
                continue
            for o in objs:
                ctx.scene.add(g.translate(o.shape, (i * dx, j * dy, 0)),
                              layer_id=o.layer_id)
                n += 1
    ctx.echo(f"Created {n} arrayed object(s).")
