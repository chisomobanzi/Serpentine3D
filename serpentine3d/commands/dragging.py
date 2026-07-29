"""Distances the mouse can answer, for commands that edit what is there.

A primitive measures its size from the point you just clicked: a sphere's
radius is the distance from its centre to the cursor. An editing command has
no such point — the thing it is about to change is already in the scene — so
the distance has to be measured off that geometry instead.

These work out where to measure from, and turn the point the user ends up
picking back into the number the command asked for. The pairing is always
the same: a base and a direction go into `PointReq(number_from=...)` so a
typed number still lands somewhere sensible, and the matching recovery
function here reads the picked point back as a distance.
"""

import math

from ..core import geometry as g

Point = tuple[float, float, float]


def _shape(obj):
    """Accept either a scene object or a bare shape."""
    return getattr(obj, "shape", obj)


def _unit(v) -> Point:
    n = math.dist(v, (0.0, 0.0, 0.0))
    if n < 1e-12:
        return (1.0, 0.0, 0.0)
    return tuple(float(c) / n for c in v)


def bounds(objs):
    """The combined bounding box of some objects, or None if there are none."""
    lo = hi = None
    for o in objs:
        a, b = g.bbox(_shape(o))
        if lo is None:
            lo, hi = list(a), list(b)
        else:
            lo = [min(x, y) for x, y in zip(lo, a)]
            hi = [max(x, y) for x, y in zip(hi, b)]
    if lo is None:
        return None
    return tuple(lo), tuple(hi)


def edge_point(objs, direction) -> Point:
    """A point on the outside of a selection, `direction` from its middle.

    Sizes are measured from the surface of the thing being changed, not from
    its middle: a 2 mm wall on a 100 mm box should be a 2 mm drag, not a
    52 mm one.
    """
    box = bounds(objs)
    if box is None:
        return (0.0, 0.0, 0.0)
    lo, hi = box
    mid = tuple((a + b) / 2 for a, b in zip(lo, hi))
    half = tuple((b - a) / 2 for a, b in zip(lo, hi))
    d = _unit(direction)
    # walk out of the middle until the box stops us in every axis at once
    reach = max((h * abs(c) for h, c in zip(half, d)), default=0.0)
    return tuple(m + c * reach for m, c in zip(mid, d))


def middle(objs) -> Point:
    """The centre of a selection — where a copy of it would sit if it moved.

    Spacings are centre-to-centre, so this is what the cursor should land on.
    """
    box = bounds(objs)
    if box is None:
        return (0.0, 0.0, 0.0)
    lo, hi = box
    return tuple((a + b) / 2 for a, b in zip(lo, hi))


def end_direction(shape, end: str = "end") -> Point:
    """The way a curve is heading as it leaves one of its ends."""
    pts = g.sample_curve(_shape(shape), 5)
    a, b = (pts[1], pts[0]) if end == "start" else (pts[-2], pts[-1])
    return _unit(tuple(y - x for x, y in zip(a, b)))


def grow_direction(shape, grow, fallback: Point = (1.0, 0.0, 0.0)) -> Point:
    """Which way `grow(size)` moves a shape — and so which way to drag it.

    Some operations run off a piece of geometry the command knows about but
    cannot name a direction for, like the boundary edge a surface extends
    past. Rather than guess, do a small one and look at where it went.
    """
    shape = _shape(shape)
    before = middle([shape])
    try:
        after = middle([grow(1e-3)])
    except (g.GeometryError, IndexError, ValueError):
        return _unit(fallback)
    v = tuple(a - b for a, b in zip(after, before))
    if math.dist(v, (0.0, 0.0, 0.0)) < 1e-12:
        return _unit(fallback)
    return _unit(v)


def signed_along(base, direction):
    """Read a picked point as a signed distance along `direction`.

    Sideways wander is dropped: the user is answering one number, and the
    cursor drifting off the axis is not part of it.
    """
    d = _unit(direction)
    b = tuple(float(c) for c in base)

    def read(p) -> float:
        return sum((x - y) * c for x, y, c in zip(p, b, d))

    return read


def distance_from(base):
    """Read a picked point as a plain, unsigned distance from `base`."""
    b = tuple(float(c) for c in base)
    return lambda p: math.dist(b, p)


def curve_middle(shape) -> Point:
    """A point on a curve, halfway along it — somewhere to measure from."""
    pts = g.sample_curve(_shape(shape), 3)
    return tuple(float(c) for c in pts[len(pts) // 2])


def offset_direction(shape, normal) -> Point:
    """Which way a *positive* offset actually moves this curve.

    OCC chooses the side, and which side that is depends on how the curve was
    built. Rather than guess its convention — and hand the user a drag that
    goes the opposite way to the cursor — nudge the curve and look.
    """
    shape = _shape(shape)
    mid = curve_middle(shape)
    try:
        moved = curve_middle(g.offset_curve(shape, 1e-3))
    except (g.GeometryError, IndexError):
        return sideways(shape, normal)
    v = tuple(a - b for a, b in zip(moved, mid))
    if math.dist(v, (0.0, 0.0, 0.0)) < 1e-12:
        return sideways(shape, normal)
    return _unit(v)


def sideways(shape, normal) -> Point:
    """The unit direction a curve moves in when it is offset.

    Offsetting slides a curve sideways in its plane, so that is the way to
    drag it: across the curve at its middle, not along it.
    """
    pts = g.sample_curve(_shape(shape), 5)
    a, b = pts[1], pts[-2]
    tangent = tuple(y - x for x, y in zip(a, b))
    n = _unit(normal)
    cross = (tangent[1] * n[2] - tangent[2] * n[1],
             tangent[2] * n[0] - tangent[0] * n[2],
             tangent[0] * n[1] - tangent[1] * n[0])
    return _unit(cross)
