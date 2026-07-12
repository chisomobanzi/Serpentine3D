"""View and display commands (non-mutating)."""

from ..core import geometry as g
from .base import PointReq, SelectReq, command


def _vp(ctx):
    return ctx.viewport


@command("top", mutates=False)
def cmd_top(ctx):
    _vp(ctx).set_view("top")
    ctx.echo("Top view.")
    yield from ()


@command("front", mutates=False)
def cmd_front(ctx):
    _vp(ctx).set_view("front")
    ctx.echo("Front view.")
    yield from ()


@command("right", mutates=False)
def cmd_right(ctx):
    _vp(ctx).set_view("right")
    ctx.echo("Right view.")
    yield from ()


@command("perspective", aliases=("persp",), mutates=False)
def cmd_persp(ctx):
    _vp(ctx).set_view("perspective")
    ctx.echo("Perspective view.")
    yield from ()


@command("zoomextents", aliases=("ze", "zea"), mutates=False)
def cmd_zoom_extents(ctx):
    _vp(ctx).zoom_extents()
    ctx.echo("Zoomed to extents.")
    yield from ()


@command("wireframe", aliases=("wf",), mutates=False)
def cmd_wireframe(ctx):
    _vp(ctx).set_display_mode("wireframe")
    ctx.echo("Wireframe display.")
    yield from ()


@command("shaded", aliases=("sh",), mutates=False)
def cmd_shaded(ctx):
    _vp(ctx).set_display_mode("shaded")
    ctx.echo("Shaded display.")
    yield from ()


@command("ghosted", aliases=("gh",), mutates=False)
def cmd_ghosted(ctx):
    _vp(ctx).set_display_mode("ghosted")
    ctx.echo("Ghosted display.")
    yield from ()


@command("grid", mutates=False)
def cmd_grid(ctx):
    vp = _vp(ctx)
    vp.grid_visible = not vp.grid_visible
    vp.update()
    ctx.echo(f"Grid {'on' if vp.grid_visible else 'off'}.")
    yield from ()


@command("snap", aliases=("osnap",), mutates=False)
def cmd_snap(ctx):
    vp = _vp(ctx)
    vp.snaps.enabled = not vp.snaps.enabled
    ctx.echo(f"Object snap {'on' if vp.snaps.enabled else 'off'} "
             "(end / mid / center).")
    yield from ()


@command("gridsnap", mutates=False)
def cmd_gridsnap(ctx):
    vp = _vp(ctx)
    vp.grid_snap = not vp.grid_snap
    ctx.echo(f"Grid snap {'on' if vp.grid_snap else 'off'} "
             f"(step {vp.grid_snap_step:g}).")
    yield from ()


@command("pointson", aliases=("po",), mutates=False)
def cmd_pointson(ctx):
    """Show control points for selected curves and surfaces (F10)."""
    from ..core import geometry as gm
    objs = yield SelectReq("Select curves or surfaces to show control points",
                           kinds=("curve", "surface"))
    vp = _vp(ctx)
    shown = 0
    for o in objs:
        try:
            if o.kind == "surface":
                gm.surface_control_points(o.shape)
            else:
                gm.get_control_points(o.shape)
            vp.cv_enabled.add(o.id)
            shown += 1
        except gm.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    vp.update()
    if shown:
        ctx.echo(f"Control points on for {shown} object(s) — drag to edit, "
                 "F11 to hide.")


@command("pointsoff", aliases=("pf",), mutates=False)
def cmd_pointsoff(ctx):
    vp = _vp(ctx)
    n = len(vp.cv_enabled)
    vp.cv_enabled.clear()
    vp.update()
    ctx.echo(f"Control points off ({n} curve(s)).")
    yield from ()


# --- analysis ----------------------------------------------------------------

@command("distance", aliases=("dist",), mutates=False)
def cmd_distance(ctx):
    p1 = yield PointReq("First point")
    p2 = yield PointReq("Second point", rubber_from=p1)
    d = sum((b - a) ** 2 for a, b in zip(p1, p2)) ** 0.5
    ctx.echo(f"Distance: {d:.4f}")


@command("area", mutates=False)
def cmd_area(ctx):
    objs = yield SelectReq("Select surfaces or solids",
                           kinds=("surface", "solid"))
    total = sum(g.surface_area(o.shape) for o in objs)
    ctx.echo(f"Area: {total:.4f}")


@command("volume", aliases=("vol",), mutates=False)
def cmd_volume(ctx):
    objs = yield SelectReq("Select solids", kinds=("solid",))
    total = sum(g.volume(o.shape) for o in objs)
    ctx.echo(f"Volume: {total:.4f}")


@command("length", aliases=("len",), mutates=False)
def cmd_length(ctx):
    objs = yield SelectReq("Select curves", kinds=("curve",))
    total = sum(g.curve_length(o.shape) for o in objs)
    ctx.echo(f"Length: {total:.4f}")


@command("curvature", mutates=False)
def cmd_curvature(ctx):
    objs = yield SelectReq("Select curve", kinds=("curve",), max_count=1)
    pt = yield PointReq("Point on curve to evaluate")
    info = g.curvature_at(objs[0].shape, pt)
    r = info["radius"]
    r_text = f"{r:.4f}" if r != float("inf") else "infinite (straight)"
    ctx.echo(f"Curvature: {info['curvature']:.6f}   Radius: {r_text}")


@command("zebra", mutates=False)
def cmd_zebra(ctx):
    vp = _vp(ctx)
    if vp.display_mode == "zebra":
        vp.set_display_mode("shaded")
        ctx.echo("Zebra analysis off.")
    else:
        vp.set_display_mode("zebra")
        ctx.echo("Zebra analysis on — stripes reveal surface continuity "
                 "(run again to turn off).")
    yield from ()
