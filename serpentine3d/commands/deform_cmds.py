"""Deformation and curve-refinement commands."""

import numpy as np

from ..core import deform, geometry as g
from .base import LengthReq, NumberReq, OptionReq, PointReq, SelectReq, command


def _apply(ctx, objs, fn, label):
    done = 0
    for o in objs:
        try:
            ctx.scene.replace_shape(o.id, deform.deform_shape(o.shape, fn))
            done += 1
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    if done:
        ctx.echo(f"{label} {done} object(s).")


@command("twist")
def cmd_twist(ctx):
    objs = yield SelectReq("Select objects to twist")
    base = yield PointReq("Twist axis base")
    top = yield PointReq("Twist axis top", rubber_from=base)
    angle = yield NumberReq("Total twist angle (degrees)", default=90.0)
    axis = np.subtract(top, base)
    height = float(np.linalg.norm(axis))
    if height < 1e-9:
        ctx.echo("Axis points coincide.")
        return
    fn = deform.twist_fn(base, axis, angle, height)
    _apply(ctx, objs, fn, f"Twisted ({angle:g}°)")


@command("taper")
def cmd_taper(ctx):
    objs = yield SelectReq("Select objects to taper")
    base = yield PointReq("Taper axis base")
    top = yield PointReq("Taper axis top", rubber_from=base)
    factor = yield NumberReq("End scale factor", default=0.5)
    axis = np.subtract(top, base)
    height = float(np.linalg.norm(axis))
    if height < 1e-9:
        ctx.echo("Axis points coincide.")
        return
    fn = deform.taper_fn(base, axis, factor, height)
    _apply(ctx, objs, fn, f"Tapered (to {factor:g})")


@command("bend")
def cmd_bend(ctx):
    objs = yield SelectReq("Select objects to bend")
    base = yield PointReq("Bend spine start")
    end = yield PointReq("Bend spine end", rubber_from=base)
    angle = yield NumberReq("Bend angle (degrees)", default=45.0)
    axis = np.subtract(end, base)
    length = float(np.linalg.norm(axis))
    if length < 1e-9:
        ctx.echo("Spine points coincide.")
        return
    fn = deform.bend_fn(base, axis, angle, length)
    _apply(ctx, objs, fn, f"Bent ({angle:g}°)")


@command("flow", aliases=("flowalongcrv",))
def cmd_flow(ctx):
    objs = yield SelectReq("Select objects to flow")
    rails = yield SelectReq("Select the target curve", kinds=("curve",),
                            max_count=1, allow_preselected=False)
    base_start = yield PointReq("Base line start (maps to curve start)")
    base_end = yield PointReq("Base line end (maps to curve end)",
                              rubber_from=base_start)
    try:
        fn = deform.flow_fn(base_start, base_end, rails[0].shape)
    except g.GeometryError as exc:
        ctx.echo(str(exc))
        return
    _apply(ctx, objs, fn, "Flowed")


@command("extend")
def cmd_extend(ctx):
    objs = yield SelectReq("Select curves to extend", kinds=("curve",))
    side = yield OptionReq("Which end", options=["End", "Start", "Both"],
                           default="End")
    length = yield LengthReq("Extension length", minimum=1e-9)
    done = 0
    for o in objs:
        try:
            shape = o.shape
            if side in ("End", "Both"):
                shape = g.extend_curve(shape, length, "end")
            if side in ("Start", "Both"):
                shape = g.extend_curve(shape, length, "start")
            ctx.scene.replace_shape(o.id, shape)
            done += 1
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    if done:
        ctx.echo(f"Extended {done} curve(s) by "
                 f"{ctx.scene.format_length(length)}.")


@command("matchcrv", aliases=("match",))
def cmd_matchcrv(ctx):
    a = yield SelectReq("Select curve to change", kinds=("curve",),
                        max_count=1)
    b = yield SelectReq("Select curve to match", kinds=("curve",),
                        max_count=1, allow_preselected=False)
    cont = yield OptionReq("Continuity", options=["Tangent", "Position"],
                           default="Tangent")
    new = g.match_curve(a[0].shape, b[0].shape, continuity=cont.lower())
    ctx.scene.replace_shape(a[0].id, new)
    ctx.echo(f"Matched {a[0].name} to {b[0].name} ({cont.lower()}).")


@command("curvaturegraph", aliases=("combs",), mutates=False)
def cmd_curvaturegraph(ctx):
    """Toggle curvature combs on selected curves."""
    vp = ctx.viewport
    objs = yield SelectReq("Select curves for the curvature graph",
                           kinds=("curve",))
    changed = 0
    for o in objs:
        if o.id in vp.comb_enabled:
            vp.comb_enabled.discard(o.id)
        else:
            vp.comb_enabled.add(o.id)
        changed += 1
    vp.update()
    ctx.echo(f"Curvature graph toggled on {changed} curve(s).")


@command("draftanalysis", aliases=("draft",), mutates=False)
def cmd_draftanalysis(ctx):
    """Colour faces by draft angle relative to the pull direction (+Z):
    green = enough draft, blue = vertical-side risk, red = undercut."""
    vp = ctx.viewport
    if vp.display_mode == "draft":
        vp.set_display_mode("shaded")
        ctx.echo("Draft analysis off.")
        return
    angle = yield NumberReq("Required draft angle (degrees)", default=3.0,
                            minimum=0.0)
    vp.draft_angle = float(angle)
    vp.set_display_mode("draft")
    ctx.echo(f"Draft analysis on ({angle:g}° from +Z; run again to exit).")
