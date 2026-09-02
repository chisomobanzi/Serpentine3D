"""Transform commands: move, copy, rotate, scale, mirror, array."""

from ..core import geometry as g
from .base import (
    IntReq, NumberReq, OptionReq, PointReq, SelectReq, command,
)


def _ghost(objs, fn):
    """Compound preview of every object transformed by fn(shape)."""
    return g.make_compound([fn(o.shape) for o in objs])


def _what_to_transform(ctx, prompt, **kw):
    """(held control points, objects) — whichever of the two is being used.

    Control points on are a way of working on part of an object, so when some
    of them are held they are what the command is for and there is nothing
    left to ask: putting the select prompt up anyway would throw them away,
    since a select prompt clears the selection to take its answer.
    """
    held = ctx.held_control_points()
    objs = [] if held else (yield SelectReq(prompt, **kw))
    return held, objs


def _preview_of(ctx, held, objs, fn):
    """What the drawing would look like with `fn` applied to what is picked."""
    return (ctx.control_point_ghost(held, fn) if held else _ghost(objs, fn))


def _do(ctx, held, objs, fn, verb, tail=""):
    """Apply `fn` to the held points or to the objects, and say what happened.

    One transform for both, so a control point cannot be moved by a slightly
    different rule from the curve it belongs to.
    """
    if held:
        n = ctx.apply_to_control_points(held, fn)
        ctx.echo(f"{verb} {n} control point(s){tail}.")
        return
    for o in objs:
        ctx.scene.replace_shape(o.id, fn(o.shape))
    ctx.echo(f"{verb} {len(objs)} object(s){tail}.")


def _move_on_paper(ctx, lv):
    """Move what is picked on a sheet, in paper millimetres.

    A corner takes the two edges that meet at it, so `move` reshapes a frame
    from typed coordinates exactly as dragging its grip does. With no corner
    picked, whole sheet items travel instead. The model is untouched either
    way — nothing here is model space.
    """
    if not lv.corners and not lv.selected:
        ctx.echo("Nothing is picked on this sheet — click the geometry, a "
                 "detail frame, an annotation or a corner grip first.")
        return
    what = "corner" if lv.corners else "sheet item"
    p1 = yield PointReq(f"Point to move the {what} from")
    p2 = yield PointReq("Point to move to", rubber_from=p1)
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    moved = lv.move_corners(dx, dy) if lv.corners else \
        lv.move_selected(dx, dy)
    if not moved:
        ctx.echo("Nothing moved — the detail is locked.")
        return
    ctx.echo(f"Moved {moved} {what}(s) by {dx:g}, {dy:g} mm on the sheet.")


@command("move", aliases=("m",), space="any")
def cmd_move(ctx):
    lv = ctx.sheet_view()
    if lv is not None:
        yield from _move_on_paper(ctx, lv)
        return
    held, objs = yield from _what_to_transform(ctx, "Select objects to move")
    p1 = yield PointReq("Point to move from")

    def _preview(p):
        off = tuple(b - a for a, b in zip(p1, p))
        return _preview_of(ctx, held, objs, lambda s: g.translate(s, off))

    p2 = yield PointReq("Point to move to", rubber_from=p1,
                        preview_fn=_preview)
    offset = tuple(b - a for a, b in zip(p1, p2))
    _do(ctx, held, objs, lambda s: g.translate(s, offset), "Moved")


def _copy_on_paper(ctx, lv):
    """Copy what is picked on a sheet, in paper millimetres.

    Whole items only, unlike `move`: a corner grip is a way of reshaping the
    frame it belongs to, and a corner on its own is not something there can be
    two of. The originals stay picked, so every repeat is measured from the
    same thing rather than from the copy before it.
    """
    if not lv.selected:
        ctx.echo("Nothing is picked on this sheet — click the geometry, a "
                 "detail frame or an annotation first.")
        return
    items = len(lv.selected)
    p1 = yield PointReq("Point to copy the sheet item from")
    count = 0
    while True:
        p2 = yield PointReq("Point to copy to (Enter to finish)",
                            rubber_from=p1, allow_empty=count > 0)
        if p2 is None:
            break
        lv.copy_selected(p2[0] - p1[0], p2[1] - p1[1])
        count += 1
    ctx.echo(f"Copied {items} sheet item(s) {count} time(s).")


@command("copy", aliases=("co", "cp"), space="any")
def cmd_copy(ctx):
    lv = ctx.sheet_view()
    if lv is not None:
        yield from _copy_on_paper(ctx, lv)
        return
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
    held, objs = yield from _what_to_transform(ctx, "Select objects to rotate")
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
            return _preview_of(ctx, held, objs,
                               lambda s: g.rotate(s, center, axis, a))

        p2 = yield PointReq("Angle, or second reference point",
                            rubber_from=center, allow_number=True,
                            preview_fn=_preview)
        angle = p2 if isinstance(p2, float) else _angle(p2)
    _do(ctx, held, objs, lambda s: g.rotate(s, center, axis, angle),
        "Rotated", f" by {angle:g} degrees")


@command("scale", aliases=("sc",))
def cmd_scale(ctx):
    """Scale about a base point: type a factor, or grab a reference
    point and drag it to its new position (live preview)."""
    import math
    held, objs = yield from _what_to_transform(ctx, "Select objects to scale")
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
            return _preview_of(ctx, held, objs,
                               lambda s: g.scale(s, center, f))

        p2 = yield PointReq("Second reference point (drag to scale)",
                            rubber_from=center, allow_number=True,
                            preview_fn=_preview)
        factor = _factor(p2)
    if abs(factor) < 1e-9:
        ctx.echo("Zero scale factor — cancelled.")
        return
    _do(ctx, held, objs, lambda s: g.scale(s, center, factor),
        "Scaled", f" by {factor:g}")


@command("scalenu")
def cmd_scale_nu(ctx):
    """Scale by a different amount along each axis: type the three
    factors, or grab a reference point and drag it to where it should end
    up (live preview either way)."""
    held, objs = yield from _what_to_transform(
        ctx, "Select objects to scale (non-uniform)")
    center = yield PointReq("Base point")

    def _apply(s, factors):
        return g.scale(s, center, 1.0, factors=factors)

    def _preview(factors):
        if not all(abs(f) > 1e-9 for f in factors):
            return None
        return _preview_of(ctx, held, objs, lambda s: _apply(s, factors))

    ref = yield PointReq("X factor, or first reference point",
                         rubber_from=center, allow_number=True,
                         preview_fn=lambda v: _preview((v, 1.0, 1.0)))
    if isinstance(ref, float):
        sx = ref
        sy = yield NumberReq("Y factor", default=1.0,
                             preview_fn=lambda v: _preview((sx, v, 1.0)))
        sz = yield NumberReq("Z factor", default=1.0,
                             preview_fn=lambda v: _preview((sx, sy, v)))
        factors = (sx, sy, sz)
    else:
        span = [r - c for c, r in zip(center, ref)]
        if all(abs(d) < 1e-12 for d in span):
            ctx.echo("Reference point is on the base point — cancelled.")
            return

        def _factors(p):
            # Per axis, and only where the reference point gave one a
            # length to be a ratio of: an axis it does not move along is
            # not being asked about, so it keeps its size.
            return tuple((c - b) / d if abs(d) > 1e-9 else 1.0
                         for b, d, c in zip(center, span, p))

        p2 = yield PointReq("Second reference point (drag to scale)",
                            rubber_from=center,
                            preview_fn=lambda p: _preview(_factors(p)))
        factors = _factors(p2)
    if not all(abs(f) > 1e-9 for f in factors):
        ctx.echo("Zero scale factor — cancelled.")
        return
    _do(ctx, held, objs, lambda s: _apply(s, factors), "Scaled",
        " by " + " × ".join(f"{f:g}" for f in factors))


@command("mirror", aliases=("mi",))
def cmd_mirror(ctx):
    held, objs = yield from _what_to_transform(ctx, "Select objects to mirror")
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
        return _preview_of(ctx, held, objs, lambda s: g.mirror(s, p1, n))

    p2 = yield PointReq("End of mirror line", rubber_from=p1,
                        preview_fn=_preview)
    # mirror across the plane through the picked line, perpendicular to
    # the construction plane
    normal = _mirror_normal(p2)
    if held:
        # Nothing to ask about keeping the original: a control point is part
        # of a curve, and a spare copy of a corner on its own is not
        # something a curve can have.
        _do(ctx, held, objs, lambda s: g.mirror(s, p1, normal), "Mirrored")
        return
    keep = yield OptionReq("Keep original?", options=["Yes", "No"],
                           default="Yes")
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
    # the ring lies on the plane you are working on, so an array laid out in
    # a Front pane stays in that pane instead of swinging away behind it
    axis = tuple(float(a) for a in ctx.cplane.normal)

    def _ring(count, total):
        step = total / (count if abs(total - 360.0) < 1e-9 else count - 1)
        return g.make_compound(
            [g.rotate(o.shape, center, axis, step * i)
             for i in range(1, count) for o in objs])

    count = yield IntReq("Number of items", default=6, minimum=2,
                         preview_fn=lambda v: _ring(v, 360.0))
    total = yield NumberReq("Angle to fill (degrees)", default=360.0,
                            preview_fn=lambda v: _ring(count, v))
    step = total / (count if abs(total - 360.0) < 1e-9 else count - 1)
    n = 0
    with ctx.scene.batched():           # one notification, not one a copy
        for i in range(1, count):
            for o in objs:
                ctx.scene.add_from(
                    g.rotate(o.shape, center, axis, step * i), o)
                n += 1
    ctx.echo(f"Created {n} arrayed object(s) around {center}.")


@command("arraypath", aliases=("arraycrv",))
def cmd_array_path(ctx):
    objs = yield SelectReq("Select objects to array")
    paths = yield SelectReq("Select path curve", kinds=("curve",),
                            max_count=1, allow_preselected=False)
    count = yield IntReq("Number of items", default=6, minimum=2)
    how = yield OptionReq("Orientation",
                          options=["Freeform", "Roadlike", "None"],
                          default="Freeform")
    base = yield PointReq("Base point on the object(s)")
    frames = g.sample_curve_frames(paths[0].shape, count)
    # Roadlike's idea of up is the plane you are working on, so a path
    # arrayed in the Front pane keeps its copies standing on that plane
    # rather than on the world's floor.
    up = tuple(float(a) for a in ctx.cplane.normal)
    n = 0
    with ctx.scene.batched():           # one notification, not one a copy
        for frame in frames:
            placement = _path_placement(frames[0], frame, base, how, up)
            if placement is None:       # the copy that lands on the original
                continue
            for o in objs:
                ctx.scene.add_from(g.apply_matrix(o.shape, placement), o)
                n += 1
    ctx.echo(f"Placed {n} object(s) along {paths[0].name}.")


def _path_placement(first, frame, base, how, up):
    """Where one arrayed copy goes, as a 4x4, or None if it would not move.

    Turn it from the frame at the head of the path to the frame here, about
    the base point, then set the base point down on the curve. Doing it in
    that order is what keeps the base point exactly on its sample: the
    rotation happens around the base, so it cannot drag the object off.
    """
    import numpy as np

    if how == "Freeform":
        rot = _axes(frame[1], frame[2]) @ _axes(first[1], first[2]).T
    elif how == "Roadlike":
        rot = _yaw_between(first[1], frame[1], up)
    else:
        rot = np.eye(3)
    m = np.eye(4)
    m[:3, :3] = rot
    m[:3, 3] = np.asarray(frame[0], float) - rot @ np.asarray(base, float)
    if np.allclose(m, np.eye(4), atol=1e-12):
        return None
    return m


def _axes(tangent, up):
    """The frame as a rotation matrix: its columns are where x, y and z end
    up, so B_here @ B_start.T is the turn from one frame to the other."""
    import numpy as np

    t = np.asarray(tangent, float)
    u = np.asarray(up, float)
    return np.column_stack([t, u, np.cross(t, u)])


def _yaw_between(t0, t1, up):
    """The part of the turn that happens in plan. Both tangents are flattened
    onto the plane `up` is normal to, and what is left is a rotation about
    `up` alone: the copy swings to follow the path but never leans with it.
    A tangent pointing straight up has no plan direction to follow, so that
    stretch of the path leaves the copy facing the way it was."""
    import numpy as np

    n = np.asarray(up, float)
    n = n / np.linalg.norm(n)
    flat = []
    for t in (t0, t1):
        v = np.asarray(t, float)
        v = v - float(np.dot(v, n)) * n
        norm = np.linalg.norm(v)
        if norm < 1e-9:
            return np.eye(3)
        flat.append(v / norm)
    return _rotation_between(flat[0], flat[1])


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

    from . import dragging
    from .base import PointReq
    # spacing is centre to centre, so the drag starts at the centre of what
    # is selected: wherever the cursor lands is where the next copy lands
    centre = dragging.middle(objs)
    xdir, ydir = tuple(ctx.cplane.xdir), tuple(ctx.cplane.ydir)
    read_x = dragging.signed_along(centre, xdir)
    read_y = dragging.signed_along(centre, ydir)

    dx = read_x((yield PointReq("Spacing X (click, or type a number)",
                                axis_lock=(centre, xdir),
                                number_from=(centre, xdir),
                                rubber_from=centre,
                                preview_fn=lambda p: _grid(read_x(p), 0.0))))
    dy = 0.0
    if ny > 1:
        dy = read_y((yield PointReq(
            "Spacing Y (click, or type a number)",
            axis_lock=(centre, ydir), number_from=(centre, ydir),
            rubber_from=centre,
            preview_fn=lambda p: _grid(dx, read_y(p)))))
    n = 0
    # One notification for the array, not one per copy: the counts are typed
    # by the user and 40x40 is an ordinary thing to type. See Scene.batched.
    with ctx.scene.batched():
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
    def _slide(p):
        # the first target only settles where the objects go, not how they
        # turn — so show them sliding across, and let the next two pick up
        # the rotation
        shift = tuple(a - b for a, b in zip(p, r1))
        return g.make_compound([g.translate(o.shape, shift) for o in objs])

    t1 = yield PointReq("First target point",
                        choices={"Copy": ["No", "Yes"]},
                        preview_fn=_slide)
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
    held, objs = yield from _what_to_transform(ctx, "Select objects to rotate")
    p1 = yield PointReq("Start of rotation axis")
    p2 = yield PointReq("End of rotation axis", rubber_from=p1)
    axis = tuple(np.subtract(p2, p1))
    if float(np.linalg.norm(axis)) < 1e-12:
        ctx.echo("Zero-length axis — cancelled.")
        return

    def _preview(a):
        if not isinstance(a, float):
            return None
        return _preview_of(ctx, held, objs,
                           lambda s: g.rotate(s, p1, axis, a))

    angle = yield NumberReq("Angle in degrees",
                            choices={"Copy": ["No", "Yes"]},
                            preview_fn=_preview)
    copy = ctx.opt("Copy", "No") == "Yes"
    if held:
        # As with mirror, nothing to copy: a corner belongs to its curve.
        _do(ctx, held, objs, lambda s: g.rotate(s, p1, axis, angle),
            "Rotated", f" by {angle:g} degrees around the picked axis")
        return
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


@command("projecttocplane", aliases=("flatten",))
def cmd_projecttocplane(ctx):
    """Flatten curves/surfaces/points onto the construction plane."""
    objs = yield SelectReq("Select objects to flatten",
                           kinds=("curve", "surface", "point"))
    origin = tuple(ctx.cplane.origin)
    normal = tuple(ctx.cplane.normal)
    n = 0
    for o in objs:
        try:
            ctx.scene.replace_shape(
                o.id, g.project_to_plane(o.shape, origin, normal))
            n += 1
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    ctx.echo(f"Flattened {n} object(s) onto the CPlane.")


@command("scale1d")
def cmd_scale1d(ctx):
    """Stretch along one direction only: type a factor and it stretches
    the way the cursor is pointing, or set the axis with a reference point
    and drag that to where it should end up."""
    import math
    held, objs = yield from _what_to_transform(
        ctx, "Select objects to scale in one direction")
    base = yield PointReq("Base point")

    def _stretch(axis, factor):
        _do(ctx, held, objs,
            lambda s: g.scale_along_axis(s, base, axis, factor),
            "Scaled", f" by {factor:g} along the axis")

    ref = yield PointReq("Scale factor, or first reference point",
                         rubber_from=base, allow_number=True)
    if isinstance(ref, float):
        # The number says how much, never which way. The cursor has been
        # saying which way all along, and where there is no cursor to ask
        # — a batch, or the bridge — the CPlane's own x direction does.
        if abs(ref) < 1e-9:
            ctx.echo("Zero scale factor — cancelled.")
            return
        aim = ctx.aim_direction()
        _stretch(aim[1] if aim is not None else tuple(ctx.cplane.xdir), ref)
        return
    axis = tuple(b - a for a, b in zip(base, ref))
    d0 = math.dist(base, ref)
    if d0 < 1e-12:
        ctx.echo("Reference point is on the base point — cancelled.")
        return

    def _factor(p):
        if isinstance(p, float):
            return p
        # project the pick onto the axis to get the new length
        v = [c - b for b, c in zip(base, p)]
        along = sum(x * a for x, a in zip(v, axis)) / d0
        return along / d0

    def _preview(p):
        f = _factor(p)
        if abs(f) < 1e-9:
            return None
        return _preview_of(ctx, held, objs,
                           lambda s: g.scale_along_axis(s, base, axis, f))

    p2 = yield PointReq("New reference point (or type factor)",
                        rubber_from=base, allow_number=True,
                        preview_fn=_preview)
    factor = _factor(p2)
    if abs(factor) < 1e-9:
        ctx.echo("Zero scale factor — cancelled.")
        return
    _stretch(axis, factor)


@command("scale2d")
def cmd_scale2d(ctx):
    """Scale in the CPlane only (thickness along the CPlane normal is
    kept)."""
    import math
    held, objs = yield from _what_to_transform(
        ctx, "Select objects to scale in the CPlane")
    base = yield PointReq("Base point")
    normal = tuple(ctx.cplane.normal)

    def _apply(s, f):
        return g.scale_along_axis(g.scale(s, base, f), base, normal, 1.0 / f)

    ref = yield PointReq("Scale factor, or first reference point",
                         rubber_from=base, allow_number=True)
    if isinstance(ref, float):
        factor = ref
    else:
        d0 = math.dist(base, ref)
        if d0 < 1e-12:
            ctx.echo("Reference point is on the base point — cancelled.")
            return

        def _factor(p):
            return p if isinstance(p, float) else math.dist(base, p) / d0

        def _preview(p):
            f = _factor(p)
            return None if abs(f) < 1e-9 \
                else _preview_of(ctx, held, objs, lambda s: _apply(s, f))

        p2 = yield PointReq("Second reference point (drag to scale)",
                            rubber_from=base, allow_number=True,
                            preview_fn=_preview)
        factor = _factor(p2)
    if abs(factor) < 1e-9:
        ctx.echo("Zero scale factor — cancelled.")
        return
    _do(ctx, held, objs, lambda s: _apply(s, factor), "Scaled",
        f" by {factor:g} in the CPlane")
