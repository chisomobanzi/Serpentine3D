"""Drafting commands: layouts, detail views, make2d, annotations."""

from __future__ import annotations

from ..core import geometry as g
from ..core.layout import (
    PAPER_SIZES, DetailView, Layout, LinearDim, TextNote, parse_scale,
    unique_layout_name,
)
# a detail view named "front" should look where the front view looks
from ..ui.camera import STANDARD_VIEWS as _VIEW_ANGLES
from .base import NumberReq, OptionReq, PointReq, SelectReq, TextReq, command


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
        # The window moves itself off a sheet that has gone, on the notify
        # below — the same way it does for undo. Naming a fallback here as
        # well is how the command line came to send you somewhere other
        # than the tab menu did.
        scene.layouts.remove(lay)
        ctx.echo(f"Deleted layout '{name}'.")
    elif action == "Duplicate":
        copy = lay.duplicate(
            unique_layout_name(scene.layouts, f"{lay.name} copy"))
        scene.layouts.append(copy)
        ctx.echo(f"Duplicated as '{copy.name}'.")
    scene.notify()


# ------------------------------------------------------------------ details

def _frame(a, b) -> tuple:
    """The rectangle two opposite corners make, in paper millimetres."""
    return (min(a[0], b[0]), min(a[1], b[1]),
            abs(b[0] - a[0]), abs(b[1] - a[1]))


@command("detail", space="paper")
def cmd_detail(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Switch to a layout first (create one with 'layout').")
        return
        yield  # pragma: no cover
    # The view and the scale come before the frame: they are what a frame is
    # a window onto, so until they are answered there is nothing to show
    # inside the rectangle being dragged — and knowing whether the model fits
    # is the whole reason for dragging it slowly.
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

    az, el = _VIEW_ANGLES[view.lower()]
    bounds = ctx.scene.bbox()
    target = [0.0, 0.0, 0.0]
    if bounds is not None:
        target = [(a + b) / 2 for a, b in zip(bounds[0], bounds[1])]
    # One detail, sized as the cursor moves and then placed: the sheet caches
    # a detail's hidden lines under its id, so a preview that made a new one
    # every mouse move would re-project the whole model every mouse move.
    detail = DetailView(azimuth=az, elevation=el, target=target,
                        perspective=(view == "Perspective"),
                        scale_denom=float(denom),
                        display_mode="wireframe")
    if view == "Perspective" and bounds is not None:
        import numpy as np
        radius = float(np.linalg.norm(
            np.subtract(bounds[1], bounds[0]))) / 2 or 10.0
        detail.perspective_distance = radius * 2.5

    c1 = yield PointReq("First corner of detail (on the paper)")

    def _frame_to(p):
        x, y, w, h = _frame(c1, p)
        if w < 1 or h < 1:
            return None                  # nothing a frame that thin can show
        detail.x, detail.y, detail.w, detail.h = x, y, w, h
        return detail

    # No rubber band: the gold frame already shows both corners, and a green
    # diagonal drawn across the view being framed hides the one thing the
    # preview is for.
    c2 = yield PointReq("Opposite corner", preview_fn=_frame_to)

    x, y, w, h = _frame(c1, c2)
    if w < 5 or h < 5:
        ctx.echo("Detail too small (min 5mm).")
        return
    detail.x, detail.y, detail.w, detail.h = x, y, w, h
    # Wireframe was for keeping up with the cursor; the detail that stays on
    # the sheet is a drawing.
    detail.display_mode = "hidden"
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
    from ..core.mesh import MeshShape
    objs = [o for o in objs if not isinstance(o.shape, MeshShape)]
    if not objs:
        ctx.echo("Nothing to project (meshes are skipped — "
                 "use meshtobrep first).")
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
    scope = "Current"
    if len(ctx.scene.layouts) > 1:
        scope = yield OptionReq("Export", options=["Current", "All"],
                                default="All")
    import os
    default_name = (f"~/{lay.name}.pdf" if scope == "Current"
                    else "~/sheets.pdf")
    path = yield TextReq("PDF path", default=default_name)
    path = os.path.abspath(os.path.expanduser(path.strip()))
    if not path.endswith(".pdf"):
        path += ".pdf"
    from ..fileio.pdf import export_layouts_pdf
    layouts = ctx.scene.layouts if scope == "All" else [lay]
    export_layouts_pdf(_window(ctx), layouts, path)
    ctx.echo(f"Exported {len(layouts)} sheet(s) to {path} "
             "(vector linework, raster shaded views).")


# -------------------------------------------------------------- annotations

@command("text", aliases=("note",), space="paper")
def cmd_text(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Text notes go on layouts — switch to one first.")
        return
        yield  # pragma: no cover
    pos = yield PointReq("Text position")
    content = yield TextReq(r"Text (\n for a new line)")
    content = content.replace("\\n", "\n")
    height = yield NumberReq("Text height (mm)", default=4.0, minimum=0.5,
                             choices={"Style": ["None", "Standard", "Small",
                                                "Heading"]})
    style = ctx.opt("Style", "None")
    lay.notes.append(TextNote(x=pos[0], y=pos[1], text=content,
                              height=float(height),
                              style="" if style == "None" else style))
    ctx.scene.notify()
    ctx.echo("Note placed.")


@command("dim", aliases=("dimension", "dimlinear"), space="paper")
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
    dim = LinearDim(x1=p1[0], y1=p1[1], x2=p2[0], y2=p2[1],
                    offset=offset, scale_denom=scale_denom)
    # anchor to the detail: the dim follows detail pan/zoom/rescale
    if detail is not None and not detail.perspective \
            and detail.contains(p1[0], p1[1]) \
            and detail.contains(p2[0], p2[1]):
        from ..core.layout import detail_unproject
        dim.detail_id = detail.id
        dim.m1 = detail_unproject(detail, p1[0], p1[1])
        dim.m2 = detail_unproject(detail, p2[0], p2[1])
    lay.dims.append(dim)
    ctx.scene.notify()
    measured = length * scale_denom
    ctx.echo(f"Dimension placed: {measured:g}"
             + (f" (anchored to detail at {detail.scale_text()})"
                if dim.detail_id else " mm on paper"))

@command("leader", space="paper")
def cmd_leader(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Leaders go on layouts — switch to one first.")
        return
        yield  # pragma: no cover
    from ..core.layout import Leader
    tip = yield PointReq("Arrow point")
    pts = [[tip[0], tip[1]]]
    while True:
        p = yield PointReq("Next point (Enter to finish)",
                           rubber_pts=[(q[0], q[1], 0) for q in pts],
                           allow_empty=len(pts) >= 2)
        if p is None:
            break
        pts.append([p[0], p[1]])
    text = yield TextReq("Leader text")
    lay.leaders.append(Leader(points=pts, text=text))
    ctx.scene.notify()
    ctx.echo("Leader placed.")


def _pattern_choices() -> list[str]:
    """The fills on offer, spelled the way a prompt spells them.

    Read off the same list a layer is set from, so a fill the app learns
    to draw is offered here without anybody remembering to come back.
    """
    from ..core.layout import HATCH_PATTERNS
    return [p.capitalize() for p in HATCH_PATTERNS]


def _layer_pattern(ctx) -> str:
    """The Pattern the layer being drawn on wants, as the prompt spells it.

    A layer is a material and a material has a fill, so hatching a wall
    on the Concrete layer is a click and an Enter rather than the same
    decision taken again on every region. A layer with nothing to say
    leaves the command where it has always been, on lines.
    """
    return (ctx.scene.layers.current.hatch or "lines").capitalize()


@command("hatch", space="paper")
def cmd_hatch(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Hatches go on layouts — switch to one first.")
        return
        yield  # pragma: no cover
    from ..core.layout import Hatch
    choices = _pattern_choices()
    offered = _layer_pattern(ctx)
    pts = []
    first = yield PointReq("First corner of hatch region "
                           "(or click inside detail linework)",
                           choices={"Mode": ["Corners", "Region"]})
    if ctx.opt("Mode", "Corners") == "Region":
        found = _region_at(ctx, lay, first[0], first[1])
        if found is None:
            ctx.echo("No closed linework region found under that point.")
            return
        poly, holes = found
        pattern = yield OptionReq("Pattern", options=choices,
                                  default=offered)
        lay.hatches.append(Hatch(points=[list(p) for p in poly],
                                 holes=[[list(p) for p in ring]
                                        for ring in holes],
                                 pattern=pattern.lower()))
        ctx.scene.notify()
        empty = f", {len(holes)} left empty" if holes else ""
        ctx.echo(f"Region hatched ({len(poly)} vertices{empty}).")
        return
    pts.append([first[0], first[1]])
    while True:
        p = yield PointReq(
            "Next corner (Enter to close)" if len(pts) >= 3
            else "Next corner",
            rubber_pts=[(q[0], q[1], 0) for q in pts],
            allow_empty=len(pts) >= 3)
        if p is None:
            break
        pts.append([p[0], p[1]])
    pattern = yield OptionReq("Pattern", options=choices, default=offered)
    spacing = 3.0
    angle = 45.0
    if pattern != "Solid":
        spacing = yield NumberReq("Line spacing (mm)", default=3.0,
                                  minimum=0.2)
        angle = yield NumberReq("Angle (degrees)", default=45.0)
    lay.hatches.append(Hatch(points=pts, pattern=pattern.lower(),
                             angle=angle, spacing=spacing))
    ctx.scene.notify()
    ctx.echo(f"Hatch placed ({pattern.lower()}).")


def _dim_scale_at(lay, x, y):
    detail = lay.detail_at(x, y)
    return (detail.scale_denom if detail and not detail.perspective
            else 1.0)


@command("dimradius", aliases=("dimr",), space="paper")
def cmd_dimradius(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Dimensions go on layouts — switch to one first.")
        return
        yield  # pragma: no cover
    from ..core.layout import RadialDim
    center = yield PointReq("Circle centre (on the paper)")
    edge = yield PointReq("Point on the circle", rubber_from=center)
    lay.rdims.append(RadialDim(
        cx=center[0], cy=center[1], px=edge[0], py=edge[1],
        diameter=False,
        scale_denom=_dim_scale_at(lay, center[0], center[1])))
    ctx.scene.notify()
    ctx.echo("Radius dimension placed.")


@command("dimdiameter", aliases=("dimdia",), space="paper")
def cmd_dimdiameter(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Dimensions go on layouts — switch to one first.")
        return
        yield  # pragma: no cover
    from ..core.layout import RadialDim
    center = yield PointReq("Circle centre (on the paper)")
    edge = yield PointReq("Point on the circle", rubber_from=center)
    lay.rdims.append(RadialDim(
        cx=center[0], cy=center[1], px=edge[0], py=edge[1], diameter=True,
        scale_denom=_dim_scale_at(lay, center[0], center[1])))
    ctx.scene.notify()
    ctx.echo("Diameter dimension placed.")


@command("dimangle", aliases=("dimangular",), space="paper")
def cmd_dimangle(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Dimensions go on layouts — switch to one first.")
        return
        yield  # pragma: no cover
    from ..core.layout import AngularDim
    vertex = yield PointReq("Angle vertex")
    p1 = yield PointReq("First direction", rubber_from=vertex)
    p2 = yield PointReq("Second direction", rubber_from=vertex)
    lay.adims.append(AngularDim(vx=vertex[0], vy=vertex[1],
                                x1=p1[0], y1=p1[1], x2=p2[0], y2=p2[1]))
    ctx.scene.notify()
    ctx.echo("Angular dimension placed.")


@command("titleblock")
def cmd_titleblock(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Title blocks go on layouts — switch to one first.")
        return
        yield  # pragma: no cover
    existing = lay.title_block.get("fields", {})
    project = yield TextReq("Project", default=existing.get("project", ""))
    title = yield TextReq("Drawing title",
                          default=existing.get("title", lay.name))
    author = yield TextReq("Drawn by", default=existing.get("author", ""))
    lay.title_block = {"template": "standard", "fields": {
        "project": project, "title": title, "author": author,
    }}
    ctx.scene.notify()
    ctx.echo("Title block added (bottom right; date/sheet/scale "
             "fill automatically).")


@command("scalebar", space="paper")
def cmd_scalebar(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Scale bars go on layouts — switch to one first.")
        return
        yield  # pragma: no cover
    pos = yield PointReq("Scale bar position")
    detail = lay.detail_at(pos[0], pos[1])
    denom = detail.scale_denom if detail and not detail.perspective else (
        lay.details[0].scale_denom if lay.details else 10.0)
    lay.scale_bars.append([pos[0], pos[1], denom])
    ctx.scene.notify()
    ctx.echo(f"Scale bar placed (1:{denom:g}).")


@command("detailsection")
def cmd_detailsection(ctx):
    lay, detail = _entered_or_only_detail(ctx)
    if detail is None:
        ctx.echo("Enter a detail first (double-click it).")
        return
        yield  # pragma: no cover
    if detail.perspective:
        ctx.echo("Sections need a parallel view detail.")
        return
    if detail.section_offset is not None:
        choice = yield OptionReq("Section", options=["Move", "Off"],
                                 default="Move")
        if choice == "Off":
            detail.section_offset = None
            ctx.viewport.layout_view._hlr_cache.pop(detail.id, None)
            ctx.scene.notify()
            ctx.echo("Section removed — detail shows the whole model.")
            return
    from .base import LengthReq
    offset = yield LengthReq(
        "Cut plane distance from the detail target (toward the viewer)",
        default=detail.section_offset or 0.0)
    detail.section_offset = float(offset)
    ctx.viewport.layout_view._hlr_cache.pop(detail.id, None)
    ctx.scene.notify()
    ctx.echo(f"Section cut at {offset:g} — geometry in front of the plane "
             "is removed, cut faces hatched.")


@command("exportdxf", mutates=False)
def cmd_exportdxf(ctx):
    """Export the active layout sheet (or the model) to DXF."""
    import os
    lay = _active_layout(ctx)
    path = yield TextReq("DXF path",
                         default=f"~/{lay.name if lay else 'model'}.dxf")
    path = os.path.abspath(os.path.expanduser(path.strip()))
    if not path.endswith(".dxf"):
        path += ".dxf"
    if lay is not None:
        from ..fileio.dxf import export_layout_dxf
        export_layout_dxf(_window(ctx), lay, path)
        ctx.echo(f"Exported sheet '{lay.name}' to {path} (paper mm; "
                 "VISIBLE/HIDDEN/ANNOT layers).")
    else:
        from .. import fileio
        fileio.export_file(ctx.scene, path)
        ctx.echo(f"Exported model to {path}.")


@command("exportsvg", mutates=False)
def cmd_exportsvg(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Switch to a layout to export it as SVG.")
        return
        yield  # pragma: no cover
    import os
    path = yield TextReq("SVG path", default=f"~/{lay.name}.svg")
    path = os.path.abspath(os.path.expanduser(path.strip()))
    if not path.endswith(".svg"):
        path += ".svg"
    from ..fileio.svg import export_layout_svg
    export_layout_svg(_window(ctx), lay, path)
    ctx.echo(f"Exported sheet '{lay.name}' to {path}.")


def _region_at(ctx, lay, px, py):
    """The closed area under a point on the sheet, as (points, holes).

    A section cut is a ring of material with the bore punched out of it,
    and a hatch dropped on the wall has to leave the bore alone. Any
    other bit of linework is a single loop with nothing inside it.
    """
    from ..core.layout import enclosing_polygon
    detail = lay.detail_at(px, py)
    if detail is None or detail.perspective:
        return None
    view = _layout_view(ctx)
    if view is None:
        return None
    data = view._detail_hlr(detail)
    cx = detail.x + detail.w / 2
    cy = detail.y + detail.h / 2
    s = 1.0 / detail.scale_denom

    def paper(poly):
        return [(cx + p[0] * s, cy + p[1] * s) for p in poly]

    regions = [[paper(loop) for loop in region]
               for region in (data.get("cut") or [])]
    polys = [paper(poly) for poly in (data["visible"] or [])]
    polys += [loop for region in regions for loop in region]
    found = enclosing_polygon(polys, px, py)
    if found is None:
        return None
    # Land in the material of a cut face and its holes are the hatch's
    # holes. Land in one of the holes and that hole is what you pointed
    # at, so it is the region and it has nothing punched out of it.
    for region in regions:
        if len(region) > 1 and found == region[0][:-1]:
            return found, [loop[:-1] for loop in region[1:]]
    return found, []


def _layout_view(ctx):
    win = _window(ctx)
    return win.viewport.layout_view if win is not None else None


@command("dimstyle", aliases=("textstyle",))
def cmd_dimstyle(ctx):
    """Create or edit a named annotation style (text height, arrows)."""
    from ..core.layout import DEFAULT_STYLES
    known = sorted(set(DEFAULT_STYLES) | set(ctx.scene.annot_styles))
    ctx.echo("Styles: " + ", ".join(known))
    name = yield TextReq("Style name (new or existing)", default="Standard")
    name = name.strip() or "Standard"
    from ..ui.annot_paint import style_of
    cur = style_of(ctx.scene, name)
    th = yield NumberReq("Text height (mm)", default=cur["text_height"],
                         minimum=0.5)
    ar = yield NumberReq("Arrow size (mm)", default=cur["arrow_size"],
                         minimum=0.2)
    ctx.scene.annot_styles[name] = {"text_height": float(th),
                                    "arrow_size": float(ar),
                                    "dim_offset": cur["dim_offset"]}
    ctx.scene.notify()
    ctx.echo(f"Style '{name}' saved. New text/dims can reference it; "
             "set it on existing annotations with 'annotedit'.")


@command("annotedit", aliases=("editnote", "edittext"), space="paper")
def cmd_annotedit(ctx):
    """Edit the annotation nearest a picked point (text, style)."""
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Annotations live on layouts — switch to one first.")
        return
        yield  # pragma: no cover
    from ..core.layout import annotation_at
    p = yield PointReq("Pick an annotation")
    hit = annotation_at(lay, p[0], p[1], tol=3.0)
    if hit is None:
        ctx.echo("Nothing there. Click on a note, dimension, leader or "
                 "hatch.")
        return
    kind, obj = hit
    if kind in ("note", "leader"):
        new = yield TextReq("Text", default=obj.text.replace("\n", "\\n"))
        obj.text = new.replace("\\n", "\n")
    elif kind in ("dim", "rdim"):
        new = yield TextReq("Override text (Enter for measured)",
                            default=obj.text)
        obj.text = new.strip()
    elif kind == "hatch":
        pattern = yield OptionReq("Pattern",
                                  options=["Lines", "Cross", "Solid"],
                                  default=obj.pattern.capitalize())
        obj.pattern = pattern.lower()
    else:
        ctx.echo("That annotation has nothing editable.")
        return
    ctx.scene.notify()
    ctx.echo("Annotation updated.")


@command("sheetindex", space="paper")
def cmd_sheetindex(ctx):
    """Place an index of all sheets as a note on the current layout."""
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Switch to a layout first.")
        return
        yield  # pragma: no cover
    pos = yield PointReq("Index position")
    lines = ["SHEET INDEX"]
    for i, l in enumerate(ctx.scene.layouts, start=1):
        title = l.title_block.get("fields", {}).get("title", "")
        lines.append(f"{i:>2}  {l.name}" + (f" — {title}" if title else ""))
    lay.notes.append(TextNote(x=pos[0], y=pos[1], text="\n".join(lines),
                              height=3.2))
    ctx.scene.notify()
    ctx.echo(f"Sheet index placed ({len(ctx.scene.layouts)} sheets).")


# `rev` belongs to revolve, in Rhino and here. It resolved that way anyway,
# but only because surfaces.py happens to be imported after this.
@command("revision")
def cmd_revision(ctx):
    """Add a row to this sheet's revision table (drawn by the title block)."""
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Switch to a layout first.")
        return
        yield  # pragma: no cover
    rev = yield TextReq("Revision tag", default=chr(ord("A")
                                                    + len(lay.revisions)))
    note = yield TextReq("Description")
    import datetime
    lay.revisions.append([rev.strip(), datetime.date.today().isoformat(),
                          note.strip()])
    if not lay.title_block:
        lay.title_block = {"fields": {}}
    ctx.scene.notify()
    ctx.echo(f"Revision {rev.strip()} recorded "
             f"({len(lay.revisions)} row(s) in the table).")


@command("dot", aliases=("annotationdot",), space="paper")
def cmd_dot(ctx):
    """Model-space annotation dots: a label bubble anchored to a 3D point.
    Dots keep their size on screen and always face the camera."""
    count = 0
    while True:
        prompt = ("Dot location" if count == 0
                  else "Next dot location (Enter to finish)")
        p = yield PointReq(prompt, allow_empty=count > 0)
        if p is None:
            break
        text = yield TextReq("Dot text", default="A" if count == 0 else "")
        if not text.strip():
            ctx.echo("Empty text — dot skipped.")
            continue
        obj = ctx.scene.add(g.make_point(p))
        ctx.scene.update(obj.id, annotation={"text": text.strip()})
        count += 1
    ctx.echo(f"Placed {count} dot(s).")
