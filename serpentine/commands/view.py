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
