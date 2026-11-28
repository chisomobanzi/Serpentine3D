"""Typed measurement constraints and radial Diameter/Radius prompting.

When a user types a length (e.g. '20', '20mm', '2cm', '2in', '3\'6"') while
a command is asking for a point, this module resolves how that measurement
locks the shape's size across live previews, mouse movements, and clicks.
"""

from __future__ import annotations

import math
from typing import NamedTuple

from ..utils.units import parse_length
from .base import Point, PointReq, parse_point, parse_value, quadrant


class TypedConstraint(NamedTuple):
    """Resolved constraint from typed command-line text during a PointReq."""
    commit_value: Point | float
    preview_value: Point | float
    rubber_point: Point | None


def _base_point(req: PointReq, ctx) -> Point | None:
    if req.rubber_from is not None:
        return tuple(float(c) for c in req.rubber_from)
    if req.rubber_pts:
        return tuple(float(c) for c in req.rubber_pts[-1])
    if ctx.last_point is not None:
        return tuple(float(c) for c in ctx.last_point)
    return None


def _is_keyword_or_option(req: PointReq, text: str) -> bool:
    low = text.lower()
    if any(opt.lower().startswith(low) for opt in req.extra_options):
        return True
    if req.choices:
        if "=" in text:
            return True
        if any(name.lower().startswith(low) for name in req.choices):
            return True
    return False


def _is_explicit_coordinate(text: str, req: PointReq, ctx) -> bool:
    if text == "0" and req.number_from is None and not req.allow_number:
        return True
    units, per = ctx.typed_units()
    cplane = None if ctx.on_bare_paper() else ctx.cplane
    last = ctx.last_point
    if per != 1.0 and isinstance(last, (tuple, list)):
        last = tuple(c / per for c in last)
    return parse_point(text, last, units, cplane) is not None


def _unit_direction(vec: tuple[float, float, float]) -> Point | None:
    length = math.dist(vec, (0.0, 0.0, 0.0))
    if length < 1e-9:
        return None
    return tuple(c / length for c in vec)


def _aim_direction(base: Point, cursor: Point, cplane=None) -> Point | None:
    raw = tuple(c - b for b, c in zip(base, cursor))
    if cplane is not None:
        n = tuple(float(v) for v in cplane.normal)
        dot = sum(r * nv for r, nv in zip(raw, n))
        planar = tuple(r - dot * nv for r, nv in zip(raw, n))
        d = _unit_direction(planar)
        if d is not None:
            return d
    return _unit_direction(raw)


def _frame_preview_point(req: PointReq, length_val: float, ctx,
                         cursor: Point | None) -> Point:
    cp = ctx.cplane
    base = req.rubber_from
    u0, v0, w0 = cp.from_world(base)
    length = abs(ctx.from_typed(length_val))
    probe = req.rubber_sides(cp.to_world(u0 + 1.0, v0 + 1.0, w0))
    centered = bool(probe and probe[0] > 1.5)
    du = (length / 2.0) if centered else length

    if cursor is not None:
        uc, vc, _ = cp.from_world(cursor)
        su = -1.0 if uc < u0 else 1.0
        sv = -1.0 if vc < v0 else 1.0
        v_target = vc if abs(vc - v0) > 1e-9 else (v0 + sv * du)
    else:
        su, sv = quadrant(ctx, cp)
        v_target = v0 + sv * du
    return cp.to_world(u0 + su * du, v_target, w0)


def resolve_typed_constraint(req, text: str, ctx,
                             cursor: Point | None = None) -> TypedConstraint | None:
    """Resolve `text` into a live geometric constraint for `PointReq`.

    Returns None when `text` is empty, names a command keyword/option, or
    does not parse to a valid point/measurement.
    """
    if not isinstance(req, PointReq):
        return None
    text = text.strip()
    if not text or text.lstrip().startswith("!"):
        return None
    if _is_keyword_or_option(req, text):
        return None

    ok, val = parse_value(req, text, ctx)
    if not ok and req.number_from is None and not req.allow_number:
        units, per = ctx.typed_units()
        v = parse_length(text, units)
        base = _base_point(req, ctx)
        if v is not None and base is not None:
            d = (_aim_direction(base, cursor) if cursor is not None else None)
            if d is None:
                d = tuple(float(c) for c in ctx.cplane.xdir)
            val = tuple(b + v * per * di for b, di in zip(base, d))
            ok = True
    if not ok:
        return None

    if isinstance(val, tuple):
        if req.axis_lock is not None or _is_explicit_coordinate(text, req, ctx):
            return TypedConstraint(val, val, val)
        base = _base_point(req, ctx)
        if base is not None and cursor is not None:
            dist = math.dist(base, val)
            cplane = ctx.cplane if req.number_from is not None else None
            d = _aim_direction(base, cursor, cplane=cplane)
            if d is not None:
                aimed = tuple(b + dist * di for b, di in zip(base, d))
                return TypedConstraint(aimed, aimed, aimed)
        return TypedConstraint(val, val, val)

    if isinstance(val, float):
        if req.rubber_sides is not None and req.rubber_from is not None:
            preview_pt = _frame_preview_point(req, val, ctx, cursor)
            return TypedConstraint(val, preview_pt, preview_pt)
        return TypedConstraint(val, val, None)

    return None


def pick_radius(ctx, center: Point, axis_dir: Point, preview_fn, *,
                radius_prompt: str = "Radius (click, or type a number)",
                diameter_prompt: str = "Diameter (click, or type a number)",
                choices: dict | None = None):
    """Yield radial PointReqs allowing free toggling between Radius and Diameter."""
    diameter = False
    while True:
        if diameter:
            req = PointReq(
                diameter_prompt,
                number_from=lambda v, c=center, d=axis_dir: tuple(
                    ci + (v / 2.0) * di for ci, di in zip(c, d)),
                rubber_from=center,
                preview_fn=preview_fn,
                extra_options=("Radius",),
                choices=choices,
            )
        else:
            req = PointReq(
                radius_prompt,
                number_from=(center, axis_dir),
                rubber_from=center,
                preview_fn=preview_fn,
                extra_options=("Diameter",),
                choices=choices,
            )
        rp = yield req
        if rp == "Diameter":
            diameter = True
            continue
        if rp == "Radius":
            diameter = False
            continue
        return rp
