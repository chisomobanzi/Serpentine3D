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


@command("4view", aliases=("fourview", "quadview"), mutates=False)
def cmd_4view(ctx):
    """Split the model area into Top / Front / Right / Perspective."""
    win = ctx.window
    if win is None:
        ctx.echo("Viewport layouts need the GUI.")
    else:
        win.set_view_layout("quad")
        ctx.echo("Four viewports. '1view' returns to a single view.")
    yield from ()


@command("1view", aliases=("oneview", "singleview"), mutates=False)
def cmd_1view(ctx):
    win = ctx.window
    if win is None:
        ctx.echo("Viewport layouts need the GUI.")
    else:
        win.set_view_layout("single")
        ctx.echo("Single viewport.")
    yield from ()


@command("rendered", aliases=("render",), mutates=False)
def cmd_rendered(ctx):
    """Environment-lit display with materials and a ground shadow."""
    _vp(ctx).set_display_mode("rendered")
    ctx.echo("Rendered display. Assign looks with 'material'.")
    yield from ()


@command("technical", aliases=("tech",), mutates=False)
def cmd_technical(ctx):
    """Hidden-line technical display (parallel projection linework)."""
    _vp(ctx).set_display_mode("technical")
    ctx.echo("Technical display — visible edges solid, hidden dashed. "
             "Navigation shows wireframe until you release.")
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

@command("units", mutates=False)
def cmd_units(ctx):
    """Set document units; optionally rescale the model to keep real size."""
    from .base import OptionReq
    from ..utils.units import TO_MM, UNIT_LABELS, UNITS
    current = ctx.scene.units
    choice = yield OptionReq(
        f"Document units (currently {UNIT_LABELS[current]})",
        options=["mm", "cm", "m", "in", "ft"], default=current)
    if choice == current:
        ctx.echo(f"Units unchanged ({UNIT_LABELS[current]}).")
        return
    factor = TO_MM[current] / TO_MM[choice]
    rescale = "No"
    if ctx.scene.all():
        rescale = yield OptionReq(
            f"Scale model by {factor:g} so objects keep their real size?",
            options=["Yes", "No"], default="Yes")
    ctx.scene.units = choice
    if rescale == "Yes":
        ctx.history.checkpoint("units rescale")
        for o in ctx.scene.all():
            ctx.scene.replace_shape(
                o.id, g.scale(o.shape, (0, 0, 0), factor))
    ctx.scene.notify()
    ctx.echo(f"Document units: {UNIT_LABELS[choice]}."
             + (" Model rescaled." if rescale == "Yes" else ""))


@command("distance", aliases=("dist",), mutates=False)
def cmd_distance(ctx):
    p1 = yield PointReq("First point")
    p2 = yield PointReq("Second point", rubber_from=p1)
    d = sum((b - a) ** 2 for a, b in zip(p1, p2)) ** 0.5
    ctx.echo(f"Distance: {ctx.scene.format_length(d)}")


@command("area", mutates=False)
def cmd_area(ctx):
    objs = yield SelectReq("Select surfaces or solids",
                           kinds=("surface", "solid"))
    total = sum(g.surface_area(o.shape) for o in objs)
    ctx.echo(f"Area: {total:.4f} {ctx.scene.units}²")


@command("volume", aliases=("vol",), mutates=False)
def cmd_volume(ctx):
    objs = yield SelectReq("Select solids", kinds=("solid",))
    total = sum(g.volume(o.shape) for o in objs)
    ctx.echo(f"Volume: {total:.4f} {ctx.scene.units}³")


@command("length", aliases=("len",), mutates=False)
def cmd_length(ctx):
    objs = yield SelectReq("Select curves", kinds=("curve",))
    total = sum(g.curve_length(o.shape) for o in objs)
    ctx.echo(f"Length: {ctx.scene.format_length(total)}")


@command("curvature", mutates=False)
def cmd_curvature(ctx):
    objs = yield SelectReq("Select curve", kinds=("curve",), max_count=1)
    pt = yield PointReq("Point on curve to evaluate")
    info = g.curvature_at(objs[0].shape, pt)
    r = info["radius"]
    r_text = f"{r:.4f}" if r != float("inf") else "infinite (straight)"
    ctx.echo(f"Curvature: {info['curvature']:.6f}   Radius: {r_text}")


@command("cplane", mutates=False)
def cmd_cplane(ctx):
    """Reposition the construction plane (drawing plane + grid)."""
    from .base import OptionReq
    from ..core import cplane as cp
    choice = yield OptionReq(
        "Construction plane",
        options=["World", "Front", "Back", "Right", "Left", "3Point"],
        default="World")
    vp = _vp(ctx)
    if choice == "3Point":
        origin = yield PointReq("CPlane origin")
        xpt = yield PointReq("Point on the X axis", rubber_from=origin)
        ypt = yield PointReq("Point in the plane (Y side)",
                             rubber_from=origin)
        try:
            vp.set_cplane(cp.from_three_points(origin, xpt, ypt))
        except ValueError as exc:
            ctx.echo(f"CPlane failed: {exc}")
            return
    else:
        vp.set_cplane(cp.PRESETS[choice.lower()]())
    ctx.echo(f"Construction plane: {vp.cplane.name}. Drawing commands, "
             "grid and picking now use this plane.")


@command("curvatureanalysis", aliases=("curvmap",), mutates=False)
def cmd_curvature_analysis(ctx):
    vp = _vp(ctx)
    if vp.display_mode == "curvature":
        vp.set_display_mode("shaded")
        ctx.echo("Curvature analysis off.")
    else:
        vp.set_display_mode("curvature")
        ctx.echo("Curvature analysis on — blue concave, green flat, "
                 "red convex (run again to turn off).")
    yield from ()


@command("namedview", aliases=("nv",), mutates=False)
def cmd_namedview(ctx):
    from .base import OptionReq, TextReq
    action = yield OptionReq("Named view",
                             options=["Save", "Restore", "List", "Delete"],
                             default="Save")
    views = ctx.scene.named_views
    vp = _vp(ctx)
    if action == "List":
        ctx.echo("Named views: " + (", ".join(sorted(views))
                                    if views else "(none)"))
        return
    name = yield TextReq("View name")
    if action == "Save":
        cam = vp.camera
        views[name] = {
            "target": [float(c) for c in cam.target],
            "distance": cam.distance,
            "azimuth": cam.azimuth,
            "elevation": cam.elevation,
            "fov": cam.fov,
            "sensor": cam.sensor_name,
        }
        ctx.scene.notify()
        ctx.echo(f"Saved view '{name}'.")
    elif action == "Restore":
        v = views.get(name)
        if v is None:
            ctx.echo(f"No view named '{name}'.")
            return
        import numpy as np
        cam = vp.camera
        cam.target = np.asarray(v["target"], float)
        cam.distance = v["distance"]
        cam.azimuth = v["azimuth"]
        cam.elevation = v["elevation"]
        cam.fov = v.get("fov", cam.fov)
        cam.sensor_name = v.get("sensor", cam.sensor_name)
        vp.update()
        ctx.echo(f"Restored view '{name}'.")
    elif action == "Delete":
        if views.pop(name, None) is not None:
            ctx.scene.notify()
            ctx.echo(f"Deleted view '{name}'.")
        else:
            ctx.echo(f"No view named '{name}'.")


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


@command("gumball", mutates=False)
def cmd_gumball(ctx):
    gb = _vp(ctx).gumball
    gb.enabled = not gb.enabled
    if ctx.viewport.config is not None:
        ctx.viewport.config.set("gumball", gb.enabled)
    _vp(ctx).update()
    ctx.echo(f"Gumball {'on' if gb.enabled else 'off'}.")
    yield from ()


@command("pictureframe", aliases=("picture",))
def cmd_pictureframe(ctx):
    """Place a reference image in the model (trace over photos/plans)."""
    from .base import OptionReq, PointReq, TextReq
    action = "Add"
    if ctx.scene.image_planes:
        action = yield OptionReq("Picture frame",
                                 options=["Add", "RemoveAll"], default="Add")
    if action == "RemoveAll":
        n = len(ctx.scene.image_planes)
        ctx.scene.image_planes = []
        ctx.scene.notify()
        ctx.echo(f"Removed {n} picture frame(s).")
        return
    import os
    path = yield TextReq("Image path (.png/.jpg)")
    path = os.path.abspath(os.path.expanduser(path.strip()))
    if not os.path.exists(path):
        ctx.echo(f"File not found: {path}")
        return
    c1 = yield PointReq("First corner")
    c2 = yield PointReq("Opposite corner (width; height follows the "
                        "image aspect)", rubber_from=c1)
    from PySide6.QtGui import QImage
    img = QImage(path)
    if img.isNull():
        ctx.echo("Could not read the image.")
        return
    aspect = img.height() / max(img.width(), 1)
    cp = ctx.cplane
    u1, v1, w1 = cp.from_world(c1)
    u2, v2, _ = cp.from_world(c2)
    width = u2 - u1
    height = abs(width) * aspect * (1 if v2 >= v1 else -1)
    origin = cp.to_world(u1, v1, w1)
    u_vec = tuple(a - b for a, b in zip(cp.to_world(u2, v1, w1), origin))
    v_vec = tuple(a - b for a, b in zip(
        cp.to_world(u1, v1 + height, w1), origin))
    ctx.scene.image_planes.append({
        "path": path, "origin": list(origin), "u": list(u_vec),
        "v": list(v_vec), "alpha": 1.0,
    })
    ctx.scene.notify()
    ctx.echo(f"Picture frame placed ({os.path.basename(path)}).")


@command("tolerance", mutates=False)
def cmd_tolerance(ctx):
    """Show or set the document's absolute modelling tolerance."""
    from .base import LengthReq
    from ..core.tolerance import set_tolerance, tol
    value = yield LengthReq(
        f"Absolute tolerance (currently {ctx.scene.format_length(tol())})",
        default=tol(), minimum=1e-9)
    set_tolerance(float(value))
    ctx.echo(f"Modelling tolerance: {ctx.scene.format_length(value)}.")
