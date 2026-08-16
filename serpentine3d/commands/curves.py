"""Curve creation commands."""

import numpy as np

from ..core import geometry as g
from .base import (
    IntReq, PointReq, SelectReq, command, frame_sides, quadrant)


def _back_at_the_start(p, pts) -> bool:
    """A pick landing on the first point again, once a loop is possible.

    Drawn as a gesture: End osnap puts the click exactly on the stored
    point, so the tolerance only has to absorb float noise, not aim."""
    if not isinstance(p, (tuple, list)) or len(pts) < 3:
        return False        # option keywords ("Undo") pass through here too
    return all(abs(a - b) < 1e-7 for a, b in zip(p, pts[0]))


def _rubber(pts):
    """Preview segments through a point list."""
    if len(pts) < 2:
        return None
    a = np.asarray(pts, np.float32)
    return np.stack([a[:-1], a[1:]], axis=1)


@command("line", aliases=("l",), space="any")
def cmd_line(ctx):
    """Straight line; BothSides grows it evenly out of its middle."""
    p1 = yield PointReq("Start of line", extra_options=("BothSides",))
    if p1 == "BothSides":
        mid = yield PointReq("Middle of line")

        def _both(p):
            far = tuple(2 * m - c for m, c in zip(mid, p))
            try:
                return g.make_line(far, p)
            except g.GeometryError:
                return None

        p2 = yield PointReq("End of line", rubber_from=mid,
                            preview_fn=_both)
        obj = ctx.add(g.make_line(
            tuple(2 * m - c for m, c in zip(mid, p2)), p2))
        ctx.echo(f"Created {obj.name}.")
        return
    p2 = yield PointReq("End of line", rubber_from=p1)
    obj = ctx.add(g.make_line(p1, p2))
    ctx.echo(f"Created {obj.name}.")


@command("polyline", aliases=("pl", "pline"), space="any")
def cmd_polyline(ctx):
    pts = [(yield PointReq("Start of polyline"))]
    while True:
        prompt = ("Next point" if len(pts) < 2
                  else "Next point (Enter to finish)")
        req = PointReq(prompt, rubber_pts=list(pts),
                       allow_empty=len(pts) >= 2,
                       extra_options=("Close",) if len(pts) >= 3 else ())
        p = yield req
        if p is None:
            break
        if p == "Close" or _back_at_the_start(p, pts):
            obj = ctx.add(g.make_polyline(pts, closed=True))
            ctx.echo(f"Created closed {obj.name}.")
            return
        pts.append(p)
    obj = ctx.add(g.make_polyline(pts))
    ctx.echo(f"Created {obj.name} with {len(pts)} points.")


def _curve_ghost(build, pts, **kw):
    """A preview of the curve this command would make if the next point
    landed under the cursor.

    Drawing the picked points and a straight chain between them says where
    you have clicked, which is the one thing you already know. What you
    cannot work out in your head is the curve those points imply, and for a
    control point curve it does not even go through them.
    """
    def ghost(p):
        if not isinstance(p, (tuple, list)):
            return None                     # an option keyword, not a point
        try:
            return build(list(pts) + [tuple(p)], **kw)
        except g.GeometryError:
            return None                     # too few points yet, or coincident
    return ghost


@command("curve", aliases=("cv",), space="any")
def cmd_curve(ctx):
    """NURBS curve by control points, as Rhino's Curve does.

    The curve is pulled toward the points rather than run through them,
    and Degree decides how far.
    """
    degree = 3
    pts = []
    while True:
        opts = ["Degree"]
        if len(pts) >= 3:
            opts.append("Close")
        if not pts:
            prompt = "Start of curve"
        elif len(pts) < 2:
            prompt = "Next control point"
        else:
            prompt = "Next control point (Enter to finish)"
        p = yield PointReq(
            prompt, rubber_pts=list(pts), allow_empty=len(pts) >= 2,
            extra_options=tuple(opts),
            # the chain between control points is the control polygon, which
            # is part of what you are drawing rather than a stand-in for it
            preview_fn=_curve_ghost(g.make_control_curve, pts, degree=degree))
        if p is None:
            break
        if p == "Degree":
            degree = yield IntReq("Degree", default=degree, minimum=1)
            continue
        if p == "Close" or _back_at_the_start(p, pts):
            obj = ctx.add(g.make_control_curve(pts, degree=degree,
                                               closed=True))
            ctx.echo(f"Created closed {obj.name}.")
            return
        pts.append(p)
    obj = ctx.add(g.make_control_curve(pts, degree=degree))
    ctx.echo(f"Created {obj.name} from {len(pts)} control points.")


@command("interpcrv", aliases=("interpcurve",), space="any")
def cmd_interpcrv(ctx):
    """NURBS curve through picked points; Close joins it back smoothly."""
    pts = []
    while True:
        prompt = ("First point of curve" if not pts
                  else "Next point (Enter to finish)")
        p = yield PointReq(
            prompt, rubber_pts=list(pts), allow_empty=len(pts) >= 2,
            extra_options=("Close",) if len(pts) >= 3 else (),
            # no band: the curve bulges away from the straight chain, so
            # drawing the chain draws a line that will not be there
            rubber_band=False,
            preview_fn=_curve_ghost(g.make_interp_curve, pts))
        if p is None:
            break
        if p == "Close" or _back_at_the_start(p, pts):
            obj = ctx.add(g.make_interp_curve(pts, closed=True))
            ctx.echo(f"Created closed {obj.name}.")
            return
        pts.append(p)
    obj = ctx.add(g.make_interp_curve(pts))
    ctx.echo(f"Created {obj.name} through {len(pts)} points.")


@command("circle", aliases=("c", "ci"), space="any")
def cmd_circle(ctx):
    """Circle from center and radius; or 2Point across, or 3Point through."""
    import math
    center = yield PointReq("Center of circle",
                            extra_options=("2Point", "3Point"))

    if center == "2Point":
        a = yield PointReq("Start of diameter")
        # the plane is read off the pick, not before it: the first click may
        # have gone through a detail and landed on that detail's plane
        normal = tuple(ctx.cplane.normal)

        def _two_to(p):
            r = math.dist(a, p) / 2
            if r < 1e-9:
                return None
            mid = tuple((x + y) / 2 for x, y in zip(a, p))
            return g.make_circle(mid, r, normal=normal)

        b = yield PointReq("End of diameter", rubber_from=a,
                           preview_fn=_two_to)
        shape = _two_to(b)
        if shape is None:
            ctx.echo("Zero diameter — no circle created.")
            return
        obj = ctx.add(shape)
        ctx.echo(f"Created {obj.name} (r={math.dist(a, b) / 2:g}).")
        return

    if center == "3Point":
        a = yield PointReq("First point on circle")
        b = yield PointReq("Second point on circle", rubber_from=a)

        def _three_to(p):
            try:
                return g.make_circle_3pt(a, b, p)
            except g.GeometryError:
                return None

        c = yield PointReq("Third point on circle", rubber_from=b,
                           preview_fn=_three_to)
        shape = _three_to(c)
        if shape is None:
            ctx.echo("Points are in a line — no circle created.")
            return
        obj = ctx.add(shape)
        ctx.echo(f"Created {obj.name}.")
        return

    normal = tuple(ctx.cplane.normal)

    def _circle_to(p):
        r = math.dist(center, p)
        return g.make_circle(center, r, normal=normal) if r > 1e-9 else None

    xdir = tuple(ctx.cplane.xdir)
    rp = yield PointReq("Radius (click, or type a number)",
                        number_from=(center, xdir),
                        rubber_from=center, preview_fn=_circle_to,
                        extra_options=("Diameter",))
    if rp == "Diameter":
        # the click means the same thing either way — a point on the rim —
        # but a typed number is now the width across rather than to the edge
        rp = yield PointReq(
            "Diameter (click, or type a number)",
            number_from=lambda v: tuple(
                c + (v / 2) * d for c, d in zip(center, xdir)),
            rubber_from=center, preview_fn=_circle_to)
    r = math.dist(center, rp)
    if r < 1e-9:
        ctx.echo("Zero radius — no circle created.")
        return
    obj = ctx.add(g.make_circle(center, r, normal=normal))
    ctx.echo(f"Created {obj.name} (r={r:g}).")


@command("arc", aliases=("a",), space="any")
def cmd_arc(ctx):
    """Arc through three points; or Center and a sweep, or StartEnd."""
    import math
    p1 = yield PointReq("Start of arc",
                        extra_options=("Center", "StartEnd"))

    if p1 == "Center":
        center = yield PointReq("Center of arc")
        normal = tuple(ctx.cplane.normal)

        def _ring_to(p):
            r = math.dist(center, p)
            return (g.make_circle(center, r, normal=normal)
                    if r > 1e-9 else None)

        start = yield PointReq("Start of arc (click, or type the radius)",
                               number_from=(center, tuple(ctx.cplane.xdir)),
                               rubber_from=center, preview_fn=_ring_to)
        if math.dist(center, start) < 1e-9:
            ctx.echo("Zero radius — no arc created.")
            return
        n = np.asarray(normal, float)
        n = n / np.linalg.norm(n)
        u = np.asarray(start, float) - np.asarray(center, float)
        u -= n * (u @ n)

        def _sweep_of(val):
            """Radians swept: a typed number is degrees, signed; a picked
            point is a direction, always the counterclockwise way round."""
            if isinstance(val, float):
                return math.radians(val)
            w = np.asarray(val, float) - np.asarray(center, float)
            w -= n * (w @ n)
            ang = math.atan2(float(n @ np.cross(u, w)), float(u @ w))
            if ang <= 1e-12:
                ang += 2 * math.pi
            return ang

        def _arc_to(val):
            try:
                return g.make_arc_center(center, start, _sweep_of(val),
                                         normal)
            except g.GeometryError:
                return None

        end = yield PointReq("End of arc (click, or type an angle)",
                             allow_number=True, rubber_from=center,
                             preview_fn=_arc_to)
        shape = _arc_to(end)
        if shape is None:
            ctx.echo("Zero sweep — no arc created.")
            return
        obj = ctx.add(shape)
        ctx.echo(f"Created {obj.name} "
                 f"({math.degrees(_sweep_of(end)):g}\N{DEGREE SIGN}).")
        return

    if p1 == "StartEnd":
        p1 = yield PointReq("Start of arc")
        p3 = yield PointReq("End of arc", rubber_from=p1)

        def _bulge_to(p):
            try:
                return g.make_arc_3pt(p1, p, p3)
            except g.GeometryError:
                return None

        p2 = yield PointReq("Point on arc", rubber_from=p1,
                            preview_fn=_bulge_to)
        shape = _bulge_to(p2)
        if shape is None:
            ctx.echo("Points are in a line — no arc created.")
            return
        obj = ctx.add(shape)
        ctx.echo(f"Created {obj.name}.")
        return

    p2 = yield PointReq("Point on arc", rubber_from=p1)
    p3 = yield PointReq("End of arc", rubber_from=p2,
                        preview_fn=lambda p: g.make_arc_3pt(p1, p2, p))
    obj = ctx.add(g.make_arc_3pt(p1, p2, p3))
    ctx.echo(f"Created {obj.name}.")


@command("ellipse", aliases=("el",), space="any")
def cmd_ellipse(ctx):
    """Ellipse from center and two radii; Diameter takes an axis whole."""
    import math
    center = yield PointReq("Center of ellipse",
                            extra_options=("Diameter",))

    if center == "Diameter":
        a = yield PointReq("Start of first axis")
        # read off the pick, not before it: the click may have entered a
        # detail and settled on its plane
        normal = tuple(ctx.cplane.normal)
        b = yield PointReq("End of first axis", rubber_from=a)
        r1 = math.dist(a, b) / 2
        if r1 < 1e-9:
            ctx.echo("Zero first axis — no ellipse created.")
            return
        mid = tuple((x + y) / 2 for x, y in zip(a, b))
        n = np.asarray(normal, float)
        n = n / np.linalg.norm(n)
        x = np.asarray(b, float) - np.asarray(mid, float)
        x -= n * (x @ n)
        if np.linalg.norm(x) < 1e-9:
            ctx.echo("The axis stands square to the plane — "
                     "no ellipse created.")
            return
        x /= np.linalg.norm(x)
        y = np.cross(n, x)

        def _half_width(p):
            w = np.asarray(p, float) - np.asarray(mid, float)
            return abs(float(w @ y))

        def _axis_to(p):
            r2 = _half_width(p)
            if r2 < 1e-9:
                return None
            try:
                return g.make_ellipse_axis(mid, tuple(x), r1, r2, normal)
            except g.GeometryError:
                return None

        tp = yield PointReq(
            "End of second axis (click, or type a number)",
            number_from=lambda v: tuple(np.asarray(mid, float) + v * y),
            rubber_from=mid, preview_fn=_axis_to)
        shape = _axis_to(tp)
        if shape is None:
            ctx.echo("Zero second axis — no ellipse created.")
            return
        obj = ctx.add(shape)
        ctx.echo(f"Created {obj.name} ({r1:g} x {_half_width(tp):g}).")
        return

    normal = tuple(ctx.cplane.normal)

    def _round_to(p):
        # nothing describes an ellipse until both radii are in, so the first
        # drag shows the circle it would be if you stopped here
        r = math.dist(center, p)
        return g.make_circle(center, r, normal=normal) if r > 1e-9 else None

    rp = yield PointReq("Major radius (click, or type a number)",
                        number_from=(center, tuple(ctx.cplane.xdir)),
                        rubber_from=center, preview_fn=_round_to)
    r1 = math.dist(center, rp)
    if r1 < 1e-9:
        ctx.echo("Zero major radius — no ellipse created.")
        return

    def _ellipse_to(p):
        r2 = math.dist(center, p)
        if r2 < 1e-9:
            return None
        try:
            return g.make_ellipse(center, r1, r2, normal=normal)
        except g.GeometryError:
            return None

    tp = yield PointReq("Minor radius (click, or type a number)",
                        number_from=(center, tuple(ctx.cplane.ydir)),
                        rubber_from=center, preview_fn=_ellipse_to)
    shape = _ellipse_to(tp)
    if shape is None:
        ctx.echo("Zero minor radius — no ellipse created.")
        return
    obj = ctx.add(shape)
    ctx.echo(f"Created {obj.name} ({r1:g} x {math.dist(center, tp):g}).")


def _rect_from_center(ctx):
    """Center then a corner — or a length and a width, both spread evenly."""
    cpt = yield PointReq("Center of rectangle")
    cp = ctx.cplane          # after the pick: it may have entered a detail
    uc, vc, w1 = cp.from_world(cpt)

    def _spread(du, dv):
        if du < 1e-9 or dv < 1e-9:
            return None
        return g.make_polyline(
            [cp.to_world(uc - du, vc - dv, w1),
             cp.to_world(uc + du, vc - dv, w1),
             cp.to_world(uc + du, vc + dv, w1),
             cp.to_world(uc - du, vc + dv, w1)], closed=True)

    def _corner_to(p):
        u2, v2, _w = cp.from_world(p)
        return _spread(abs(u2 - uc), abs(v2 - vc))

    c2 = yield PointReq(
        "Corner, or length", rubber_from=cpt, preview_fn=_corner_to,
        rubber_sides=lambda p: (2 * abs(cp.from_world(p)[0] - uc),
                                2 * abs(cp.from_world(p)[1] - vc)),
        allow_number=True)
    if isinstance(c2, float):
        du = abs(c2) / 2
        if du < 1e-9:
            ctx.echo("Zero length — no rectangle created.")
            return
        wp = yield PointReq(
            "Width (click, or type a number)",
            number_from=lambda v: cp.to_world(uc, vc + v / 2, w1),
            rubber_from=cpt,
            preview_fn=lambda p: _spread(
                du, abs(cp.from_world(p)[1] - vc)))
        dv = abs(cp.from_world(wp)[1] - vc)
    else:
        u2, v2, _w = cp.from_world(c2)
        du, dv = abs(u2 - uc), abs(v2 - vc)
    shape = _spread(du, dv)
    if shape is None:
        ctx.echo("Zero width — no rectangle created.")
        return
    obj = ctx.add(shape)
    ctx.echo(f"Created {obj.name}.")


def _rect_from_edge(ctx):
    """One whole side then a width, so the rectangle can lean.

    The corner-to-corner rectangle stands square to the plane's axes; this
    one takes the first side as drawn and hangs the width off whichever
    side of it you point.
    """
    import math
    a = yield PointReq("Start of edge")
    cp = ctx.cplane          # after the pick: it may have entered a detail
    b = yield PointReq("End of edge", rubber_from=a)
    ua, va, wa = cp.from_world(a)
    ub, vb, _w = cp.from_world(b)
    eu, ev = ub - ua, vb - va
    elen = math.hypot(eu, ev)
    if elen < 1e-9:
        ctx.echo("Zero edge — no rectangle created.")
        return
    pu, pv = -ev / elen, eu / elen        # square to the edge, on the plane

    def _lean(s):
        if abs(s) < 1e-9:
            return None
        return g.make_polyline(
            [cp.to_world(ua, va, wa), cp.to_world(ub, vb, wa),
             cp.to_world(ub + s * pu, vb + s * pv, wa),
             cp.to_world(ua + s * pu, va + s * pv, wa)], closed=True)

    def _side_of(p):
        u, v, _ = cp.from_world(p)
        return (u - ua) * pu + (v - va) * pv

    wp = yield PointReq(
        "Width (click, or type a number)",
        number_from=lambda v: cp.to_world(ub + v * pu, vb + v * pv, wa),
        rubber_from=b, preview_fn=lambda p: _lean(_side_of(p)))
    shape = _lean(_side_of(wp))
    if shape is None:
        ctx.echo("Zero width — no rectangle created.")
        return
    obj = ctx.add(shape)
    ctx.echo(f"Created {obj.name}.")


@command("rectangle", aliases=("rect", "rec"), space="any")
def cmd_rectangle(ctx):
    """Rectangle corner to corner; or Center out, or 3Point to lean it."""
    c1 = yield PointReq("First corner",
                        extra_options=("Center", "3Point"))

    if c1 == "Center":
        yield from _rect_from_center(ctx)
        return
    if c1 == "3Point":
        yield from _rect_from_edge(ctx)
        return
    cp = ctx.cplane

    def _rect_to(p):
        if cp.is_world_xy():
            return g.make_rectangle(c1, p)
        u1, v1, _ = cp.from_world(c1)
        u2, v2, _ = cp.from_world(p)
        if abs(u2 - u1) < 1e-9 or abs(v2 - v1) < 1e-9:
            return None
        return g.make_polyline(
            [cp.to_world(u1, v1), cp.to_world(u2, v1),
             cp.to_world(u2, v2), cp.to_world(u1, v2)], closed=True)

    # "or length" the way Rhino's rectangle reads it: one number is a side and
    # the width is asked for next. The general rule for a point prompt — a
    # number is how far along the way you are pointing — would make it the
    # diagonal, and under ortho the cursor is square to the plane, so the
    # rectangle would come out a line.
    c2 = yield PointReq("Opposite corner, or length", rubber_from=c1,
                        preview_fn=_rect_to, rubber_sides=frame_sides(c1, cp),
                        allow_number=True)
    if isinstance(c2, float):
        if abs(c2) < 1e-9:
            ctx.echo("Zero length — no rectangle created.")
            return
        # measured on the plane it is drawn on: a tilted rectangle has sides
        # of its own, and the world's idea of them is a pair of shadows
        su, sv = quadrant(ctx, cp)
        u1, v1, w1 = cp.from_world(c1)
        far_u = u1 + su * c2
        edge = cp.to_world(far_u, v1, w1)
        vdir = tuple(float(sv * a) for a in cp.ydir)

        def _wide_to(p):
            _u, pv, _w = cp.from_world(p)
            return _rect_to(cp.to_world(far_u, pv, w1))

        wp = yield PointReq("Width (click, or type a number)",
                            axis_lock=(edge, vdir), number_from=(edge, vdir),
                            rubber_from=edge, preview_fn=_wide_to,
                            rubber_sides=frame_sides(c1, cp))
        _u, wv, _w = cp.from_world(wp)
        c2 = cp.to_world(far_u, wv, w1)
    if cp.is_world_xy():
        obj = ctx.add(g.make_rectangle(c1, c2))
    else:
        u1, v1, _ = cp.from_world(c1)
        u2, v2, _ = cp.from_world(c2)
        if abs(u2 - u1) < 1e-9 or abs(v2 - v1) < 1e-9:
            from ..core.geometry import GeometryError
            raise GeometryError("Degenerate rectangle")
        pts = [cp.to_world(u1, v1), cp.to_world(u2, v1),
               cp.to_world(u2, v2), cp.to_world(u1, v2)]
        obj = ctx.add(g.make_polyline(pts, closed=True))
    ctx.echo(f"Created {obj.name}.")


@command("closecrv", aliases=("cc", "closecurve"))
def cmd_closecrv(ctx):
    """Close open curves with a straight segment between their ends."""
    objs = yield SelectReq("Select open curves to close", kinds=("curve",))
    done = 0
    for o in objs:
        try:
            ctx.scene.replace_shape(o.id, g.close_curve(o.shape))
            done += 1
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    ctx.echo(f"Closed {done} curve(s).")


# "any" since the sheet draws vertices as well as edges: a point on paper is a
# mark on the page, at the millimetres it was put at, and it is not printed.
@command("point", aliases=("pt",), space="any")
def cmd_point(ctx):
    count = 0
    p = yield PointReq("Location of point object")
    while p is not None:
        ctx.add(g.make_point(p))
        count += 1
        p = yield PointReq("Next point (Enter to finish)", allow_empty=True)
    ctx.echo(f"Placed {count} point object(s).")


@command("divide")
def cmd_divide(ctx):
    from .base import IntReq
    curves = yield SelectReq("Select curves to divide", kinds=("curve",))
    n = yield IntReq("Number of segments", default=10, minimum=1)
    total = 0
    for c in curves:
        try:
            pts = g.sample_curve(c.shape, int(n) + 1)
        except g.GeometryError as exc:
            ctx.echo(f"{c.name}: {exc}")
            continue
        if g.is_closed_curve(c.shape):
            pts = pts[:-1]
        for p in pts:
            ctx.scene.add(g.make_point(p), layer_id=c.layer_id)
            total += 1
    ctx.echo(f"Placed {total} division points.")


@command("tweencurves", aliases=("tween",))
def cmd_tweencurves(ctx):
    from .base import IntReq
    first = yield SelectReq("Select first curve", kinds=("curve",),
                            max_count=1)
    second = yield SelectReq("Select second curve", kinds=("curve",),
                             max_count=1, allow_preselected=False)
    n = yield IntReq("Number of tween curves", default=1, minimum=1)
    curves = g.tween_curves(first[0].shape, second[0].shape, int(n))
    for c in curves:
        ctx.scene.add(c, layer_id=first[0].layer_id)
    ctx.echo(f"Created {len(curves)} tween curve(s).")
