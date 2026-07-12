"""Drafting commands: layouts, detail views, make2d, annotations."""

from __future__ import annotations

import math

from ..core import geometry as g
from ..core.layout import (
    PAPER_SIZES, DetailView, Layout, LinearDim, TextNote, parse_scale,
)
from .base import NumberReq, OptionReq, PointReq, SelectReq, TextReq, command

_VIEW_ANGLES = {
    "top": (math.radians(-90), math.radians(89.9)),
    "bottom": (math.radians(-90), math.radians(-89.9)),
    "front": (math.radians(-90), 0.0),
    "back": (math.radians(90), 0.0),
    "right": (0.0, 0.0),
    "left": (math.radians(180), 0.0),
    "perspective": (math.radians(-60), math.radians(30)),
}


def _window(ctx):
    return ctx.window


def _active_layout(ctx):
    vp = ctx.viewport
    if vp is None or vp.space == "model":
        return None
    for lay in ctx.scene.layouts:
        if lay.id == vp.space:
            return lay
    return None


def _entered_or_only_detail(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        return None, None
    entered = ctx.viewport.layout_view._entered()
    if entered is not None:
        return lay, entered
    if len(lay.details) == 1:
        return lay, lay.details[0]
    return lay, None


# ------------------------------------------------------------------ layouts

@command("layout")
def cmd_layout(ctx):
    action = yield OptionReq(
        "Layout", options=["New", "Rename", "Delete", "Duplicate", "List"],
        default="New")
    scene = ctx.scene
    if action == "List":
        if not scene.layouts:
            ctx.echo("No layouts. Use 'layout' > New to create one.")
        else:
            ctx.echo("Layouts: " + ", ".join(
                f"{lay.name} ({lay.paper_w:g}x{lay.paper_h:g}mm, "
                f"{len(lay.details)} details)" for lay in scene.layouts))
        return

    if action == "New":
        name = yield TextReq("Layout name",
                             default=f"Layout {len(scene.layouts) + 1}")
        size = yield OptionReq(
            "Paper size", options=list(PAPER_SIZES) + ["Custom"],
            default="A3")
        if size == "Custom":
            w = yield NumberReq("Paper width (mm)", default=420.0,
                                minimum=10)
            h = yield NumberReq("Paper height (mm)", default=297.0,
                                minimum=10)
        else:
            orientation = yield OptionReq(
                "Orientation", options=["Landscape", "Portrait"],
                default="Landscape")
            w, h = PAPER_SIZES[size]
            if orientation == "Portrait":
                w, h = h, w
        lay = Layout(name=name, paper_w=float(w), paper_h=float(h))
        scene.layouts.append(lay)
        scene.notify()
        if _window(ctx) is not None:
            _window(ctx).switch_space(lay.id)
        ctx.echo(f"Created layout '{name}' ({w:g}x{h:g}mm). "
                 "Use 'detail' to place views of the model.")
        return

    name = yield TextReq("Layout name")
    lay = next((l for l in scene.layouts
                if l.name.lower() == name.lower()), None)
    if lay is None:
        ctx.echo(f"No layout named '{name}'.")
        return
    if action == "Rename":
        new = yield TextReq("New name", default=lay.name)
        lay.name = new
        ctx.echo(f"Renamed to '{new}'.")
    elif action == "Delete":
        scene.layouts.remove(lay)
        if ctx.viewport is not None and ctx.viewport.space == lay.id:
            _window(ctx).switch_space("model")
        ctx.echo(f"Deleted layout '{name}'.")
    elif action == "Duplicate":
        copy = lay.clone()
        import uuid
        copy.id = uuid.uuid4().hex[:8]
        for d in copy.details:
            d.id = uuid.uuid4().hex[:8]
        copy.name = f"{lay.name} copy"
        scene.layouts.append(copy)
        ctx.echo(f"Duplicated as '{copy.name}'.")
    scene.notify()


# ------------------------------------------------------------------ details

@command("detail")
def cmd_detail(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Switch to a layout first (create one with 'layout').")
        return
        yield  # pragma: no cover
    c1 = yield PointReq("First corner of detail (on the paper)")
    c2 = yield PointReq("Opposite corner", rubber_from=c1)
    view = yield OptionReq(
        "View direction",
        options=["Top", "Front", "Right", "Left", "Back", "Bottom",
                 "Perspective"],
        default="Top")
    scale_text = yield TextReq("Scale (e.g. 1:10, 1:50)", default="1:10")
    denom = parse_scale(scale_text)
    if denom is None:
        ctx.echo(f"Could not parse scale '{scale_text}' — using 1:10.")
        denom = 10.0

    x, y = min(c1[0], c2[0]), min(c1[1], c2[1])
    w, h = abs(c2[0] - c1[0]), abs(c2[1] - c1[1])
    if w < 5 or h < 5:
        ctx.echo("Detail too small (min 5mm).")
        return
    az, el = _VIEW_ANGLES[view.lower()]
    bounds = ctx.scene.bbox()
    target = [0.0, 0.0, 0.0]
    if bounds is not None:
        target = [(a + b) / 2 for a, b in zip(bounds[0], bounds[1])]
    detail = DetailView(x=x, y=y, w=w, h=h, azimuth=az, elevation=el,
                        target=target,
                        perspective=(view == "Perspective"),
                        scale_denom=float(denom),
                        display_mode="hidden")
    if view == "Perspective" and bounds is not None:
        import numpy as np
        radius = float(np.linalg.norm(
            np.subtract(bounds[1], bounds[0]))) / 2 or 10.0
        detail.perspective_distance = radius * 2.5
    lay.details.append(detail)
    ctx.scene.notify()
    ctx.echo(f"Detail created: {view} at {detail.scale_text()} "
             f"({w:g}x{h:g}mm). Double-click to enter it; "
             "'detailmode' changes its display.")


@command("detailscale")
def cmd_detailscale(ctx):
    lay, detail = _entered_or_only_detail(ctx)
    if detail is None:
        ctx.echo("Enter a detail first (double-click it).")
        return
        yield  # pragma: no cover
    text = yield TextReq("New scale (e.g. 1:20)",
                         default=detail.scale_text())
    denom = parse_scale(text)
    if denom is None:
        ctx.echo(f"Could not parse '{text}'.")
        return
    detail.scale_denom = float(denom)
    ctx.scene.notify()
    ctx.echo(f"Detail scale set to {detail.scale_text()}.")


@command("detailmode")
def cmd_detailmode(ctx):
    lay, detail = _entered_or_only_detail(ctx)
    if detail is None:
        ctx.echo("Enter a detail first (double-click it).")
        return
        yield  # pragma: no cover
    mode = yield OptionReq(
        "Display mode",
        options=["Technical", "Hidden", "Wireframe", "Shaded"],
        default="Hidden")
    detail.display_mode = mode.lower()
    ctx.viewport.layout_view._hlr_cache.pop(detail.id, None)
    ctx.scene.notify()
    ctx.echo(f"Detail display: {mode.lower()} "
             "(technical = hidden lines removed, hidden = dashed).")


@command("detaillock")
def cmd_detaillock(ctx):
    lay, detail = _entered_or_only_detail(ctx)
    if detail is None:
        ctx.echo("Enter a detail first (double-click it).")
    else:
        detail.locked = not detail.locked
        ctx.scene.notify()
        ctx.echo(f"Detail {'locked' if detail.locked else 'unlocked'}.")
    yield from ()


@command("detailborder")
def cmd_detailborder(ctx):
    lay, detail = _entered_or_only_detail(ctx)
    if detail is None:
        ctx.echo("Enter a detail first (double-click it).")
    else:
        detail.show_border = not detail.show_border
        ctx.scene.notify()
        ctx.echo(f"Border {'on' if detail.show_border else 'off'}.")
    yield from ()


@command("detaildelete")
def cmd_detaildelete(ctx):
    lay, detail = _entered_or_only_detail(ctx)
    if detail is None:
        ctx.echo("Enter the detail to delete first (double-click it).")
    else:
        lay.details.remove(detail)
        ctx.viewport.layout_view.entered_detail = None
        ctx.scene.notify()
        ctx.echo("Detail deleted.")
    yield from ()


# ------------------------------------------------------------------- make2d

@command("make2d")
def cmd_make2d(ctx):
    objs = yield SelectReq(
        "Select objects to project (Enter = all visible)", min_count=0)
    if not objs:
        objs = ctx.scene.visible_objects()
        objs = [o for o in objs
                if not ctx.scene.layers.get(o.layer_id).name.startswith(
                    "Make2D")]
    if not objs:
        ctx.echo("Nothing to project.")
        return
    from ..core import hlr
    cam = ctx.viewport.camera
    import numpy as np
    fwd = cam.target - cam.position
    fwd = fwd / max(np.linalg.norm(fwd), 1e-12)
    right, up = cam.right_up()
    res = hlr.hlr_project_safe([o.shape for o in objs], origin=(0, 0, 0),
                          view_dir=tuple(-fwd), x_dir=tuple(right))

    layers = ctx.scene.layers
    def layer_for(name, color):
        existing = layers.find_by_name(name)
        if existing:
            return existing.id
        return layers.create(name, color).id

    made = 0
    visible_edges = res["visible"] + res["outline"]
    if visible_edges:
        vis_layer = layer_for("Make2D visible", (0.9, 0.9, 0.92))
        ctx.scene.add(g.make_compound(visible_edges),
                      name="2D drawing (visible)", layer_id=vis_layer)
        made += len(visible_edges)
    if res["hidden"]:
        hid_layer = layer_for("Make2D hidden", (0.5, 0.5, 0.55))
        ctx.scene.add(g.make_compound(res["hidden"]),
                      name="2D drawing (hidden)", layer_id=hid_layer)
        made += len(res["hidden"])
    ctx.echo(f"Make2D: projected {len(objs)} object(s) into {made} curves "
             "on the world XY plane (Make2D layers). 'explode' to edit "
             "individual curves.")


@command("exportpdf", aliases=("print", "pdf"), mutates=False)
def cmd_exportpdf(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        if not ctx.scene.layouts:
            ctx.echo("No layouts to print — create one with 'layout'.")
            return
            yield  # pragma: no cover
        name = yield TextReq("Layout to export",
                             default=ctx.scene.layouts[0].name)
        lay = next((l for l in ctx.scene.layouts
                    if l.name.lower() == name.lower()), None)
        if lay is None:
            ctx.echo(f"No layout named '{name}'.")
            return
    import os
    path = yield TextReq("PDF path", default=f"~/{lay.name}.pdf")
    path = os.path.abspath(os.path.expanduser(path.strip()))
    if not path.endswith(".pdf"):
        path += ".pdf"
    from ..fileio.pdf import export_layout_pdf
    export_layout_pdf(_window(ctx), lay, path)
    ctx.echo(f"Exported '{lay.name}' to {path} "
             "(vector linework, raster shaded views).")


# -------------------------------------------------------------- annotations

@command("text", aliases=("note",))
def cmd_text(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Text notes go on layouts — switch to one first.")
        return
        yield  # pragma: no cover
    pos = yield PointReq("Text position")
    content = yield TextReq("Text")
    height = yield NumberReq("Text height (mm)", default=4.0, minimum=0.5)
    lay.notes.append(TextNote(x=pos[0], y=pos[1], text=content,
                              height=float(height)))
    ctx.scene.notify()
    ctx.echo("Note placed.")


@command("dim", aliases=("dimension", "dimlinear"))
def cmd_dim(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Dimensions go on layouts — switch to one first.")
        return
        yield  # pragma: no cover
    p1 = yield PointReq("First dimension point")
    p2 = yield PointReq("Second dimension point", rubber_from=p1)
    p3 = yield PointReq("Dimension line position", rubber_from=p2)
    import numpy as np
    a = np.array(p1[:2])
    b = np.array(p2[:2])
    d = b - a
    length = np.linalg.norm(d)
    if length < 1e-9:
        ctx.echo("Points coincide.")
        return
    n = np.array([-d[1], d[0]]) / length
    offset = float(np.dot(np.array(p3[:2]) - a, n))
    # dimensions over a detail read in model units at the detail's scale
    mid = (a + b) / 2
    detail = lay.detail_at(float(mid[0]), float(mid[1]))
    scale_denom = detail.scale_denom if (detail and
                                         not detail.perspective) else 1.0
    lay.dims.append(LinearDim(x1=p1[0], y1=p1[1], x2=p2[0], y2=p2[1],
                              offset=offset, scale_denom=scale_denom))
    ctx.scene.notify()
    measured = length * scale_denom
    ctx.echo(f"Dimension placed: {measured:g}"
             + (f" (model units at {detail.scale_text()})" if detail
                else " mm on paper"))