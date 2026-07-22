"""View and display commands (non-mutating)."""

from ..core import geometry as g
from .base import OptionReq, PointReq, SelectReq, TextReq, command


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


@command("back", mutates=False)
def cmd_back(ctx):
    _vp(ctx).set_view("back")
    yield from ()


@command("left", mutates=False)
def cmd_left(ctx):
    _vp(ctx).set_view("left")
    yield from ()


@command("bottom", mutates=False)
def cmd_bottom(ctx):
    _vp(ctx).set_view("bottom")
    yield from ()


@command("viewcapturetofile", aliases=("vcf", "viewcapture"), mutates=False)
def cmd_viewcapturetofile(ctx):
    """Save the active viewport as a PNG image."""
    import os
    path = yield TextReq("Image path", default="~/viewport.png")
    path = os.path.abspath(os.path.expanduser(path.strip()))
    if not path.lower().endswith((".png", ".jpg", ".jpeg")):
        path += ".png"
    img = _vp(ctx).grabFramebuffer()
    img.save(path)
    ctx.echo(f"Saved {img.width()}x{img.height()} capture to {path}")


@command("viewcapturetoclipboard", aliases=("vcc",), mutates=False)
def cmd_viewcapturetoclipboard(ctx):
    """Copy the active viewport image to the clipboard."""
    from PySide6.QtWidgets import QApplication
    img = _vp(ctx).grabFramebuffer()
    QApplication.clipboard().setImage(img)
    ctx.echo(f"Copied {img.width()}x{img.height()} capture to the "
             "clipboard.")
    yield from ()


@command("clippingplane", aliases=("clip",))
def cmd_clippingplane(ctx):
    """Place a rectangular clipping plane on the CPlane: geometry on its
    normal side is hidden in shaded viewports. Move or rotate the plane
    object to move the cut; Flip reverses the kept side."""
    c1 = yield PointReq("First corner of clipping plane")

    def _rect(p):
        cp = ctx.cplane
        u1, v1, _ = cp.from_world(c1)
        u2, v2, _ = cp.from_world(p)
        if abs(u2 - u1) < 1e-9 or abs(v2 - v1) < 1e-9:
            return None
        return g.planar_face(g.make_polyline(
            [cp.to_world(u1, v1), cp.to_world(u2, v1),
             cp.to_world(u2, v2), cp.to_world(u1, v2)], closed=True))

    c2 = yield PointReq("Opposite corner", rubber_from=c1,
                        choices={"Flip": ["No", "Yes"]}, preview_fn=_rect)
    face = _rect(c2)
    if face is None:
        ctx.echo("Degenerate rectangle — no clipping plane created.")
        return
    if ctx.opt("Flip", "No") == "Yes":
        face = g.mirror(face, tuple(c1), tuple(ctx.cplane.normal))
    obj = ctx.scene.add(face, name=_next_clip_name(ctx.scene))
    ctx.scene.update(obj.id, clip_plane={"enabled": True})
    ctx.echo(f"Created {obj.name} — geometry on its normal side is "
             "hidden. 'disableclippingplane' pauses it.")


def _next_clip_name(scene) -> str:
    n = sum(1 for o in scene.all() if o.clip_plane) + 1
    return f"Clipping Plane {n:02d}"


def _clip_planes_from(ctx, objs):
    planes = [o for o in objs if o.clip_plane]
    if not planes:                       # fall back to every clip plane
        planes = [o for o in ctx.scene.all() if o.clip_plane]
    return planes


@command("disableclippingplane", aliases=("dcc",), mutates=False)
def cmd_disableclippingplane(ctx):
    """Pause clipping planes (they stay in the scene, the cut stops)."""
    objs = yield SelectReq("Select clipping planes (Enter or 'all' = all)",
                           allow_preselected=True)
    planes = _clip_planes_from(ctx, objs)
    for o in planes:
        ctx.scene.update(o.id, clip_plane={"enabled": False})
    ctx.echo(f"Disabled {len(planes)} clipping plane(s).")


@command("enableclippingplane", aliases=("ecc",), mutates=False)
def cmd_enableclippingplane(ctx):
    """Re-enable paused clipping planes."""
    objs = yield SelectReq("Select clipping planes (Enter or 'all' = all)",
                           allow_preselected=True)
    planes = _clip_planes_from(ctx, objs)
    for o in planes:
        ctx.scene.update(o.id, clip_plane={"enabled": True})
    ctx.echo(f"Enabled {len(planes)} clipping plane(s).")


@command("selclippingplane", mutates=False)
def cmd_selclippingplane(ctx):
    """Select every clipping plane object."""
    ids = [o.id for o in ctx.scene.all() if o.clip_plane]
    ctx.selection.set(ids)
    ctx.echo(f"Selected {len(ids)} clipping plane(s).")
    yield from ()


@command("spacemouse", aliases=("3dmouse",), mutates=False)
def cmd_spacemouse(ctx):
    """SpaceMouse status, on/off toggle, and a live axis readout for
    checking the motion mapping."""
    win = ctx.window
    if win is None or not hasattr(win, "spacemouse"):
        ctx.echo("SpaceMouse support needs the GUI.")
        return
        yield  # pragma: no cover
    action = yield OptionReq("SpaceMouse",
                             options=["Status", "Toggle", "Diag"],
                             default="Status")
    sm = win.spacemouse
    cfg = win.cfg
    if action == "Toggle":
        new = not cfg.get("spacemouse", "enabled", default=True)
        cfg.set("spacemouse", "enabled", new)
        ctx.echo(f"SpaceMouse {'enabled' if new else 'disabled'} "
                 f"({sm.status()}).")
    elif action == "Diag":
        import time
        sm.diag_until = time.time() + 10
        ctx.echo("SpaceMouse diagnostics for 10 s — move the puck and "
                 "watch the axis values here.")
    else:
        state = "on" if cfg.get("spacemouse", "enabled",
                                default=True) else "off"
        ctx.echo(f"SpaceMouse: {sm.status()}; navigation {state}. "
                 "Sensitivity and inversion live in Settings > Mouse.")


@command("zoom", aliases=("z",), mutates=False)
def cmd_zoom(ctx):
    """Zoom the active view: Selected, Extents, a picked Window, In, Out."""
    vp = _vp(ctx)
    mode = yield OptionReq(
        "Zoom", options=["Selected", "Extents", "Window", "In", "Out"],
        default="Selected" if ctx.selection.ids else "Extents")
    if mode == "Window":
        p1 = yield PointReq("First corner of zoom window")
        p2 = yield PointReq("Opposite corner", rubber_from=p1)
        vp.zoom_to_points(p1, p2)
    elif mode == "Selected":
        if not vp.zoom_selected():
            ctx.echo("Nothing selected — zooming extents instead.")
            vp.zoom_extents()
    elif mode == "Extents":
        vp.zoom_extents()
    else:
        vp.camera.zoom(3.0 if mode == "In" else -3.0)
        vp.update()


@command("zoomselected", aliases=("zs",), mutates=False)
def cmd_zoomselected(ctx):
    """Frame the current selection in the active view."""
    vp = _vp(ctx)
    if not vp.zoom_selected():
        ctx.echo("Nothing selected.")
    yield from ()


@command("zoomwindow", aliases=("zw",), mutates=False)
def cmd_zoomwindow(ctx):
    """Zoom into a window picked with two corner points."""
    vp = _vp(ctx)
    p1 = yield PointReq("First corner of zoom window")
    p2 = yield PointReq("Opposite corner", rubber_from=p1)
    vp.zoom_to_points(p1, p2)


@command("newviewport", aliases=("newvp", "splitview"), mutates=False)
def cmd_newviewport(ctx):
    """Open an extra live viewport in a dockable panel — drag its title
    bar to rearrange or tear it off to float; space tabs switch what the
    focused pane shows (model and paper sheets can sit side by side)."""
    win = ctx.window
    if win is None:
        ctx.echo("Extra viewports need the GUI.")
        return
        yield  # pragma: no cover
    where = yield OptionReq(
        "Place the new viewport",
        options=["Right", "Left", "Bottom", "Top", "Floating"],
        default="Right")
    space = "model"
    if ctx.scene.layouts:
        names = ["Model"] + [lay.name for lay in ctx.scene.layouts]
        pick = yield OptionReq("Showing", options=names, default="Model")
        if pick != "Model":
            space = next(lay.id for lay in ctx.scene.layouts
                         if lay.name == pick)
    win.new_viewport_dock(where, space)
    ctx.echo("New viewport opened — drag its title bar to rearrange; "
             "click it, then a space tab, to change what it shows.")


@command("floatviewport", aliases=("floatvp",), mutates=False)
def cmd_floatviewport(ctx):
    """Open a floating viewport window (drag it to another monitor)."""
    win = ctx.window
    if win is None:
        ctx.echo("Extra viewports need the GUI.")
    else:
        win.new_viewport_dock("Floating")
        ctx.echo("Floating viewport opened.")
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


@command("snap", mutates=False)
def cmd_snap(ctx):
    vp = _vp(ctx)
    vp.snaps.enabled = not vp.snaps.enabled
    ctx.echo(f"Object snap {'on' if vp.snaps.enabled else 'off'} "
             "(end / mid / center).")
    yield from ()


_OSNAP_KINDS = ("End", "Mid", "Center", "Quad", "Int", "Perp", "Near")


@command("osnap", mutates=False)
def cmd_osnap(ctx):
    """Toggle one object-snap type (or All = the master switch) —
    scriptable, e.g. bind a key to 'osnap mid toggle'."""
    kind = yield OptionReq("Snap type", options=["All", *_OSNAP_KINDS],
                           default="All")
    action = yield OptionReq("Action", options=["Toggle", "On", "Off"],
                             default="Toggle")
    vp = _vp(ctx)
    cfg = getattr(vp, "config", None)
    if kind == "All":
        vp.snaps.enabled = (not vp.snaps.enabled if action == "Toggle"
                            else action == "On")
        if cfg:
            cfg.set("osnaps", "enabled", vp.snaps.enabled)
        state = "on" if vp.snaps.enabled else "off"
        ctx.echo(f"Object snaps {state}.")
    else:
        key = kind.lower()
        cur = bool(cfg.get("osnaps", key, default=True)) if cfg else True
        new = (not cur) if action == "Toggle" else action == "On"
        if cfg:
            cfg.set("osnaps", key, new)
        ctx.echo(f"{kind} snap {'on' if new else 'off'}.")
    win = ctx.window
    if win is not None and hasattr(win, "osnap_bar"):
        win.osnap_bar.refresh()


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


@command("printcheck", aliases=("printinfo",), mutates=False)
def cmd_printcheck(ctx):
    """Check selected objects for 3D-print readiness: watertight, manifold,
    degenerate facets, thin walls, overhangs and print size."""
    objs = yield SelectReq("Select objects to check for printing",
                           kinds=("solid", "surface", "mesh"))
    if not objs:
        ctx.echo("Nothing selected.")
        return
    from ..core import printcheck as pc
    u = ctx.scene.units
    for o in objs:
        try:
            r = pc.analyze(o.shape)
        except Exception as exc:                      # noqa: BLE001
            ctx.echo(f"{o.name}: analysis failed ({exc})")
            continue
        head = "PRINT-READY" if r["ok"] else "NEEDS ATTENTION"
        wt = "yes" if r["watertight"] else f"NO ({r['open_edges']} open edges)"
        mf = ("yes" if r["manifold"]
              else f"NO ({r['nonmanifold_edges']} bad edges)")
        sx, sy, sz = r["size"]
        lines = [f"{o.name} — {head}",
                 f"  watertight: {wt} · manifold: {mf}",
                 f"  size: {sx:.3g} x {sy:.3g} x {sz:.3g} {u}"]
        if r.get("brep_valid") is False:
            lines.append("  WARNING: geometry is invalid (self-intersections?)")
        if r["degenerate"]:
            lines.append(f"  degenerate facets: {r['degenerate']}")
        if r["min_wall"] is not None:
            tag = "  (THIN)" if r["thin"] else ""
            lines.append(f"  min wall: {r['min_wall']:.3g} {u}{tag}")
        pct = r["overhang_fraction"] * 100.0
        note = " — may need supports" if pct > 1.0 else ""
        lines.append(f"  overhangs >{r['overhang_deg']:.0f}°: "
                     f"{pct:.1f}% of surface{note}")
        ctx.echo("\n".join(lines))


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
            "projection": cam.projection,
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
        cam.projection = v.get("projection", "perspective")
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


@command("ai", aliases=("assistant",), label="AI Assistant", mutates=False)
def cmd_ai(ctx):
    """Open the AI assistant panel — model by describing what you want."""
    ctx.window.show_ai_panel()
    yield from ()


@command("ortho", mutates=False)
def cmd_ortho(ctx):
    """Toggle ortho: picked points lock to CPlane axes from the last
    point (hold Shift for the momentary opposite)."""
    vp = _vp(ctx)
    vp.ortho = not vp.ortho
    if getattr(ctx, "window", None) is not None:
        bar = getattr(ctx.window, "osnap_bar", None)
        if bar is not None:
            bar.refresh()
    ctx.echo(f"Ortho {'on' if vp.ortho else 'off'}.")
    yield from ()


@command("angle", mutates=False)
def cmd_angle(ctx):
    """Angle at a vertex point between two directions."""
    import math

    import numpy as np
    pv = yield PointReq("Vertex point")
    p1 = yield PointReq("First direction point", rubber_from=pv)
    p2 = yield PointReq("Second direction point", rubber_from=pv)
    v1 = np.subtract(p1, pv)
    v2 = np.subtract(p2, pv)
    n1, n2 = np.linalg.norm(v1), np.linalg.norm(v2)
    if n1 < 1e-12 or n2 < 1e-12:
        ctx.echo("Degenerate direction — cancelled.")
        return
    cosang = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
    a = math.degrees(math.acos(cosang))
    ctx.echo(f"Angle: {a:.4g} degrees ({360 - a if a else 0:.4g} reflex)")


@command("radius", mutates=False)
def cmd_radius(ctx):
    """Radius of curvature of a curve at a picked point."""
    curves = yield SelectReq("Select curve", kinds=("curve",), max_count=1)
    p = yield PointReq("Point on curve")
    try:
        info = g.curvature_at(curves[0].shape, p)
    except g.GeometryError as exc:
        ctx.echo(str(exc))
        return
    k = info["curvature"]
    if k <= 1e-12:
        ctx.echo("Curve is straight there (infinite radius).")
    else:
        ctx.echo(f"Radius: {ctx.scene.format_length(info['radius'])}"
                 f"  (curvature {k:.6g})")
