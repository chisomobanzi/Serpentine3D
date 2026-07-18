"""Transform commands: move, copy, rotate, scale, mirror, array."""

from ..core import geometry as g
from .base import IntReq, LengthReq, NumberReq, OptionReq, PointReq, SelectReq, command


def _ghost(objs, fn):
    """Compound preview of every object transformed by fn(shape)."""
    return g.make_compound([fn(o.shape) for o in objs])


@command("move", aliases=("m",))
def cmd_move(ctx):
    objs = yield SelectReq("Select objects to move")
    p1 = yield PointReq("Point to move from")

    def _preview(p):
        off = tuple(b - a for a, b in zip(p1, p))
        return _ghost(objs, lambda s: g.translate(s, off))

    p2 = yield PointReq("Point to move to", rubber_from=p1,
                        preview_fn=_preview)
    offset = tuple(b - a for a, b in zip(p1, p2))
    for o in objs:
        ctx.scene.replace_shape(o.id, g.translate(o.shape, offset))
    ctx.echo(f"Moved {len(objs)} object(s).")


@command("copy", aliases=("co", "cp"))
def cmd_copy(ctx):
    objs = yield SelectReq("Select objects to copy")
    p1 = yield PointReq("Point to copy from")

    def _preview(p):
        off = tuple(b - a for a, b in zip(p1, p))
        return _ghost(objs, lambda s: g.translate(s, off))

    count = 0
    while True:
        p2 = yield PointReq("Point to copy to (Enter to finish)",
                            rubber_from=p1, allow_empty=count > 0,
                            preview_fn=_preview)
        if p2 is None:
            break
        offset = tuple(b - a for a, b in zip(p1, p2))
        for o in objs:
            ctx.scene.add_from(g.translate(o.shape, offset), o)
        count += 1
    ctx.echo(f"Copied {len(objs)} object(s) {count} time(s).")


@command("rotate", aliases=("ro",))
def cmd_rotate(ctx):
    """Rotate around the CPlane normal: type an angle, or pick a
    reference direction and drag it to its new heading (live preview)."""
    import math

    import numpy as np
    objs = yield SelectReq("Select objects to rotate")
    center = yield PointReq("Center of rotation")
    axis = tuple(ctx.cplane.normal)
    ref = yield PointReq("Angle in degrees, or first reference point",
                         rubber_from=center, allow_number=True)
    if isinstance(ref, float):
        angle = ref
    else:
        v1 = np.subtract(ref, center)
        if np.linalg.norm(v1) < 1e-12:
            ctx.echo("Reference point is on the center — cancelled.")
            return

        def _angle(p):
            v2 = np.subtract(p, center)
            n = np.asarray(axis, float)
            return math.degrees(math.atan2(
                float(np.dot(np.cross(v1, v2), n)), float(np.dot(v1, v2))))

        def _preview(p):
            a = p if isinstance(p, float) else _angle(p)
            return _ghost(objs, lambda s: g.rotate(s, center, axis, a))

        p2 = yield PointReq("Angle, or second reference point",
                            rubber_from=center, allow_number=True,
                            preview_fn=_preview)
        angle = p2 if isinstance(p2, float) else _angle(p2)
    for o in objs:
        ctx.scene.replace_shape(
            o.id, g.rotate(o.shape, center, axis, angle))
    ctx.echo(f"Rotated {len(objs)} object(s) by {angle:g} degrees.")


@command("scale", aliases=("sc",))
def cmd_scale(ctx):
    """Scale about a base point: type a factor, or grab a reference
    point and drag it to its new position (live preview)."""
    import math
    objs = yield SelectReq("Select objects to scale")
    center = yield PointReq("Base point")
    ref = yield PointReq("Scale factor, or first reference point",
                         rubber_from=center, allow_number=True)
    if isinstance(ref, float):
        factor = ref
    else:
        d0 = math.dist(center, ref)
        if d0 < 1e-12:
            ctx.echo("Reference point is on the base point — cancelled.")
            return

        def _factor(p):
            return p if isinstance(p, float) else math.dist(center, p) / d0

        def _preview(p):
            f = _factor(p)
            if f < 1e-9:
                return None
            return _ghost(objs, lambda s: g.scale(s, center, f))

        p2 = yield PointReq("Second reference point (drag to scale)",
                            rubber_from=center, allow_number=True,
                            preview_fn=_preview)
        factor = _factor(p2)
    if abs(factor) < 1e-9:
        ctx.echo("Zero scale factor — cancelled.")
        return
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

    def _mirror_normal(p):
        import numpy as np
        line = np.subtract(p, p1)
        normal = np.cross(ctx.cplane.normal, line)
        if np.linalg.norm(normal) < 1e-12:
            normal = np.asarray(ctx.cplane.xdir)
        return tuple(float(c) for c in normal)

    def _preview(p):
        n = _mirror_normal(p)
        return _ghost(objs, lambda s: g.mirror(s, p1, n))

    p2 = yield PointReq("End of mirror line", rubber_from=p1,
                        preview_fn=_preview)
    keep = yield OptionReq("Keep original?", options=["Yes", "No"],
                           default="Yes")
    # mirror across the plane through the picked line, perpendicular to
    # the construction plane
    normal = _mirror_normal(p2)
    for o in objs:
        mirrored = g.mirror(o.shape, p1, normal)
        if keep == "Yes":
            ctx.scene.add_from(mirrored, o)
        else:
            ctx.scene.replace_shape(o.id, mirrored)
    ctx.echo(f"Mirrored {len(objs)} object(s).")


@command("arraypolar")
def cmd_array_polar(ctx):
    objs = yield SelectReq("Select objects to array")
    center = yield PointReq("Center of polar array")

    def _ring(count, total):
        step = total / (count if abs(total - 360.0) < 1e-9 else count - 1)
        return g.make_compound(
            [g.rotate(o.shape, center, (0, 0, 1), step * i)
             for i in range(1, count) for o in objs])

    count = yield IntReq("Number of items", default=6, minimum=2,
                         preview_fn=lambda v: _ring(v, 360.0))
    total = yield NumberReq("Angle to fill (degrees)", default=360.0,
                            preview_fn=lambda v: _ring(count, v))
    step = total / (count if abs(total - 360.0) < 1e-9 else count - 1)
    n = 0
    for i in range(1, count):
        for o in objs:
            ctx.scene.add_from(
                g.rotate(o.shape, center, (0, 0, 1), step * i), o)
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
            ctx.scene.add_from(g.translate(o.shape, offset), o)
            n += 1
    ctx.echo(f"Placed {n} object(s) along {paths[0].name}.")


@command("array")
def cmd_array(ctx):
    objs = yield SelectReq("Select objects to array")
    nx = yield IntReq("Count X", default=2, minimum=1)
    ny = yield IntReq("Count Y", default=1, minimum=1)

    def _grid(dx, dy):
        shapes = [g.translate(o.shape, (i * dx, j * dy, 0))
                  for i in range(nx) for j in range(ny)
                  if (i, j) != (0, 0) for o in objs]
        return g.make_compound(shapes) if shapes else None

    dx = yield LengthReq("Spacing X", default=10.0,
                         preview_fn=lambda v: _grid(v, 0.0))
    dy = 0.0
    if ny > 1:
        dy = yield LengthReq("Spacing Y", default=10.0,
                             preview_fn=lambda v: _grid(dx, v))
    n = 0
    for i in range(nx):
        for j in range(ny):
            if i == 0 and j == 0:
                continue
            for o in objs:
                ctx.scene.add_from(
                    g.translate(o.shape, (i * dx, j * dy, 0)), o)
                n += 1
    ctx.echo(f"Created {n} arrayed object(s).")


def _rotation_between(v1, v2):
    """3x3 rotation taking direction v1 to v2 (numpy, Rodrigues)."""
    import numpy as np
    a = np.asarray(v1, float)
    b = np.asarray(v2, float)
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    s = float(np.linalg.norm(v))
    if s < 1e-12:
        if c > 0:
            return np.eye(3)
        # antiparallel: rotate pi about any axis perpendicular to a
        perp = np.cross(a, [1.0, 0.0, 0.0])
        if np.linalg.norm(perp) < 1e-9:
            perp = np.cross(a, [0.0, 1.0, 0.0])
        perp = perp / np.linalg.norm(perp)
        return 2.0 * np.outer(perp, perp) - np.eye(3)
    k = v / s
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    angle = float(np.arctan2(s, c))
    import math
    return (np.eye(3) + math.sin(angle) * kx
            + (1 - math.cos(angle)) * (kx @ kx))


def _frame(p1, p2, p3):
    """Orthonormal basis from three points (x along p1->p2)."""
    import numpy as np
    x = np.asarray(p2, float) - np.asarray(p1, float)
    nx = np.linalg.norm(x)
    if nx < 1e-12:
        raise g.GeometryError("Reference points coincide")
    x = x / nx
    v = np.asarray(p3, float) - np.asarray(p1, float)
    z = np.cross(x, v)
    nz = np.linalg.norm(z)
    if nz < 1e-12:
        raise g.GeometryError("Points are collinear")
    z = z / nz
    return np.column_stack([x, np.cross(z, x), z])


def _similarity(rot3, scale, src_origin, dst_origin):
    """4x4 taking src_origin to dst_origin with rotation and scale."""
    import numpy as np
    A = rot3 * float(scale)
    M = np.eye(4)
    M[:3, :3] = A
    M[:3, 3] = np.asarray(dst_origin, float) - A @ np.asarray(src_origin,
                                                              float)
    return M


def _place(ctx, objs, matrix, copy: bool):
    made = []
    for o in objs:
        shape = g.apply_matrix(o.shape, matrix)
        if copy:
            made.append(ctx.scene.add_from(shape, o))
        else:
            ctx.scene.replace_shape(o.id, shape)
            made.append(o)
    return made


@command("orient", aliases=("o2",))
def cmd_orient(ctx):
    """Remap objects from two reference points to two target points
    (rotation + translation, Scale=Yes matches the point spacing)."""
    import math

    import numpy as np
    objs = yield SelectReq("Select objects to orient")
    r1 = yield PointReq("First reference point")
    r2 = yield PointReq("Second reference point", rubber_from=r1)
    t1 = yield PointReq("First target point", rubber_from=r1,
                        choices={"Copy": ["No", "Yes"],
                                 "Scale": ["No", "Yes"]})

    def _matrix(t2):
        v1 = np.subtract(r2, r1)
        v2 = np.subtract(t2, t1)
        if np.linalg.norm(v1) < 1e-12 or np.linalg.norm(v2) < 1e-12:
            raise g.GeometryError("Reference points coincide")
        s = (np.linalg.norm(v2) / np.linalg.norm(v1)
             if ctx.opt("Scale", "No") == "Yes" else 1.0)
        return _similarity(_rotation_between(v1, v2), s, r1, t1)

    def _preview(p):
        m = _matrix(p)
        return g.make_compound([g.apply_matrix(o.shape, m) for o in objs])

    t2 = yield PointReq("Second target point", rubber_from=t1,
                        preview_fn=_preview)
    made = _place(ctx, objs, _matrix(t2), ctx.opt("Copy", "No") == "Yes")
    verb = "Oriented a copy of" if ctx.opt("Copy", "No") == "Yes" \
        else "Oriented"
    ctx.echo(f"{verb} {len(made)} object(s)"
             + (" (scaled to fit)." if ctx.opt("Scale", "No") == "Yes"
                else "."))


@command("orient3pt", aliases=("o3",))
def cmd_orient3pt(ctx):
    """Remap objects from three reference points to three target points
    (full 3D reorientation)."""
    objs = yield SelectReq("Select objects to orient")
    r1 = yield PointReq("First reference point")
    r2 = yield PointReq("Second reference point", rubber_from=r1)
    r3 = yield PointReq("Third reference point", rubber_from=r2)
    t1 = yield PointReq("First target point",
                        choices={"Copy": ["No", "Yes"]})
    t2 = yield PointReq("Second target point", rubber_from=t1)

    def _matrix(t3):
        rot = _frame(t1, t2, t3) @ _frame(r1, r2, r3).T
        return _similarity(rot, 1.0, r1, t1)

    def _preview(p):
        m = _matrix(p)
        return g.make_compound([g.apply_matrix(o.shape, m) for o in objs])

    t3 = yield PointReq("Third target point", rubber_from=t2,
                        preview_fn=_preview)
    made = _place(ctx, objs, _matrix(t3), ctx.opt("Copy", "No") == "Yes")
    ctx.echo(f"Oriented {len(made)} object(s) onto the target frame.")


@command("rotate3d", aliases=("ro3",))
def cmd_rotate3d(ctx):
    """Rotate around an arbitrary axis picked as two points."""
    import math

    import numpy as np
    objs = yield SelectReq("Select objects to rotate")
    p1 = yield PointReq("Start of rotation axis")
    p2 = yield PointReq("End of rotation axis", rubber_from=p1)
    axis = tuple(np.subtract(p2, p1))
    if float(np.linalg.norm(axis)) < 1e-12:
        ctx.echo("Zero-length axis — cancelled.")
        return

    def _preview(a):
        if not isinstance(a, float):
            return None
        return _ghost(objs, lambda s: g.rotate(s, p1, axis, a))

    angle = yield NumberReq("Angle in degrees",
                            choices={"Copy": ["No", "Yes"]},
                            preview_fn=_preview)
    copy = ctx.opt("Copy", "No") == "Yes"
    for o in objs:
        rotated = g.rotate(o.shape, p1, axis, angle)
        if copy:
            ctx.scene.add_from(rotated, o)
        else:
            ctx.scene.replace_shape(o.id, rotated)
    verb = "Rotated a copy of" if copy else "Rotated"
    ctx.echo(f"{verb} {len(objs)} object(s) {angle:g} degrees "
             "around the picked axis.")


@command("setpt", aliases=("setpoints",))
def cmd_setpt(ctx):
    """Force chosen coordinates of every control point to one value —
    the classic way to flatten walls onto a level (Z) or line things
    up on an axis."""
    objs = yield SelectReq("Select curves, surfaces or points",
                           kinds=("curve", "surface", "point"))
    target = yield PointReq(
        "Target point",
        choices={"X": ["No", "Yes"], "Y": ["No", "Yes"],
                 "Z": ["Yes", "No"]})
    axes = (ctx.opt("X", "No") == "Yes", ctx.opt("Y", "No") == "Yes",
            ctx.opt("Z", "Yes") == "Yes")
    if not any(axes):
        ctx.echo("All axes set to No — nothing to do.")
        return
    n = 0
    for o in objs:
        try:
            ctx.scene.replace_shape(o.id, g.set_points(o.shape, target, axes))
            n += 1
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    tags = "".join(a for a, on in zip("XYZ", axes) if on)
    ctx.echo(f"Set {tags} on {n} object(s).")
