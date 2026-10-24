"""Drafting commands: layouts, detail views, make2d, annotations."""

from __future__ import annotations

import numpy as np

from ..core import clipping
from ..core import geometry as g
from ..core.layout import (
    PAPER_SIZES, DetailView, Layout, LinearDim, TextNote, format_scale,
    hatch_patterns_of, parse_scale, pattern_label, pattern_named,
    unique_layout_name,
)
from ..utils.units import TO_MM
# a detail view named "front" should look where the front view looks
from ..ui.camera import STANDARD_VIEWS as _VIEW_ANGLES
from .base import (
    FileReq, FormField, FormReq, NumberReq, OptionReq, PointReq, SelectReq,
    TextReq, TextEditorReq, command, has_text_editor,
)
from .regions import coplanar_curves, pick_regions


def _window(ctx):
    return ctx.window


def _active_layout(ctx):
    space = (ctx.replay_space if ctx.replay_space is not None
             else getattr(ctx.viewport, "space", "model"))
    if space == "model":
        return None
    for lay in ctx.scene.layouts:
        if lay.id == space:
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
        # a copied detail is cut by the planes the original is cut by
        clipping.carry_views(scene, lay.copied_details(copy))
        scene.layouts.append(copy)
        ctx.echo(f"Duplicated as '{copy.name}'.")
    scene.notify()


# ------------------------------------------------------------------ details

def _frame(a, b) -> tuple:
    """The rectangle two opposite corners make, in paper millimetres."""
    return (min(a[0], b[0]), min(a[1], b[1]),
            abs(b[0] - a[0]), abs(b[1] - a[1]))


def _fit_pending_detail(detail, bounds):
    """Fit a preview without notifying or changing the document."""
    if bounds is None:
        return
    import math
    import numpy as np
    from ..ui.layout_view import detail_direction, ZOOM_PAD

    lo, hi = bounds
    detail.target = [(a + b) / 2 for a, b in zip(lo, hi)]
    points = np.asarray([(x, y, z) for x in (lo[0], hi[0])
                         for y in (lo[1], hi[1])
                         for z in (lo[2], hi[2])]) - detail.target
    direction, right, up = detail_direction(detail)
    xs, ys = points @ right, points @ up
    if detail.perspective:
        # The same 45-degree vertical field of view as detail_matrices.
        tangent = math.tan(math.radians(22.5))
        aspect = detail.w / detail.h
        depth = points @ direction
        distance = np.max(depth + ZOOM_PAD * np.maximum(
            np.abs(xs) / (tangent * aspect), np.abs(ys) / tangent))
        detail.perspective_distance = max(float(distance), 1e-6)
    else:
        span = max(float(np.ptp(xs)) / detail.w,
                   float(np.ptp(ys)) / detail.h)
        if span > 1e-9:
            detail.scale_denom = max(span * ZOOM_PAD, 1e-6)


@command("detail", space="paper")
def cmd_detail(ctx):
    lay = _active_layout(ctx)
    if lay is None:
        ctx.echo("Switch to a layout first (create one with 'layout').")
        return
        yield  # pragma: no cover
    owner = _window(ctx) or ctx
    units = ctx.scene.units
    # remembered as the ratio it was, which is the same in any units
    view, ratio = getattr(owner, "_detail_placement_settings", ("Top", 100.0))
    bounds = ctx.scene.bbox()
    target = [0.0, 0.0, 0.0]
    if bounds is not None:
        target = [(a + b) / 2 for a, b in zip(bounds[0], bounds[1])]
    az, el = _VIEW_ANGLES[view.lower()]
    # Keep one identity throughout placement, for the detail rendering cache.
    detail = DetailView(azimuth=az, elevation=el, target=target,
                        perspective=(view == "Perspective"),
                        scale_denom=float(ratio) / TO_MM[units],
                        display_mode="wireframe")
    if bounds is not None:
        import math
        radius = math.dist(bounds[0], bounds[1]) / 2 or 10.0
        detail.perspective_distance = radius * 2.5
    c1 = None
    fit_model = False

    def _frame_to(p):
        x, y, w, h = _frame(c1, p)
        if w < 1 or h < 1:
            return None
        detail.x, detail.y, detail.w, detail.h = x, y, w, h
        if fit_model:
            _fit_pending_detail(detail, bounds)
        return detail

    while True:
        stage = ("First corner of detail (on the paper)" if c1 is None
                 else "Opposite corner")
        setting = "Fit model" if fit_model else detail.scale_text(units)
        value = yield PointReq(
            f"{stage} · {view} · {setting}",
            extra_options=("View", "Scale", "Fit"),
            preview_fn=_frame_to if c1 is not None else None)
        if isinstance(value, str) and value == "View":
            view = yield OptionReq(
                "View direction",
                options=["Top", "Front", "Right", "Left", "Back", "Bottom",
                         "Perspective"], default=view)
            detail.azimuth, detail.elevation = _VIEW_ANGLES[view.lower()]
            detail.perspective = view == "Perspective"
        elif isinstance(value, str) and value == "Scale":
            scale_text = yield TextReq("Scale (e.g. 1:10, 1:50)",
                                       default=detail.scale_text(units))
            denom = parse_scale(scale_text, units)
            if denom is None:
                ctx.echo(f"Could not parse scale '{scale_text}' — keeping "
                         f"{detail.scale_text(units)}.")
            else:
                detail.scale_denom = float(denom)
                fit_model = False
        elif isinstance(value, str) and value == "Fit":
            fit_model = True
            ctx.echo("Fit model to the frame. Choose Scale to return to a fixed scale.")
        elif c1 is None:
            c1 = value
        else:
            c2 = value
            break

    x, y, w, h = _frame(c1, c2)
    if w < 5 or h < 5:
        ctx.echo("Detail too small (min 5mm).")
        return
    _frame_to(c2)
    detail.display_mode = "hidden"
    lay.details.append(detail)
    owner._detail_placement_settings = (view,
                                        detail.scale_denom * TO_MM[units])
    lv = ctx.viewport.layout_view
    lv.selected = [("detail", detail)]
    lv.corners = []
    ctx.scene.notify("layouts")
    ctx.echo(f"Detail created: {view} at {detail.scale_text(units)} "
             f"({w:g}x{h:g}mm). Edit it in Properties or double-click to enter.")


@command("detailscale")
def cmd_detailscale(ctx):
    lay, detail = _entered_or_only_detail(ctx)
    if detail is None:
        ctx.echo("Enter a detail first (double-click it).")
        return
        yield  # pragma: no cover
    units = ctx.scene.units
    text = yield TextReq("New scale (e.g. 1:20)",
                         default=detail.scale_text(units))
    denom = parse_scale(text, units)
    if denom is None:
        ctx.echo(f"Could not parse '{text}'.")
        return
    detail.scale_denom = float(denom)
    ctx.scene.notify()
    ctx.echo(f"Detail scale set to {detail.scale_text(units)}.")


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
    from ..core.pointcloud import PointCloudShape
    objs = [o for o in objs
            if not isinstance(o.shape, (MeshShape, PointCloudShape))]
    if not objs:
        ctx.echo("Nothing to project (meshes and point clouds are skipped — "
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
    def layer_for(name, color, linetype="Continuous"):
        existing = layers.find_by_name(name)
        if existing:
            return existing.id
        layer = layers.create(name, color)
        layers.set_linetype(layer.id, linetype)
        return layer.id

    made = 0
    visible_edges = res["visible"] + res["outline"]
    if visible_edges:
        vis_layer = layer_for("Make2D visible", (0.9, 0.9, 0.92))
        ctx.scene.add(g.make_compound(visible_edges),
                      name="2D drawing (visible)", layer_id=vis_layer)
        made += len(visible_edges)
    if res["hidden"]:
        hid_layer = layer_for("Make2D hidden", (0.5, 0.5, 0.55), "Hidden")
        ctx.scene.add(g.make_compound(res["hidden"]),
                      name="2D drawing (hidden)", layer_id=hid_layer)
        made += len(res["hidden"])
    ctx.echo(f"Make2D: projected {len(objs)} object(s) into {made} curves "
             "on the world XY plane (Make2D layers). 'explode' to edit "
             "individual curves.")


@command("printsheets", aliases=("print", "plot"), mutates=False)
def cmd_printsheets(ctx):
    """Print sheets, or save them as one PDF, choosing them from the set.

    With a window this is the print dialog (#38). Scripts and a headless
    run have no dialog to show, so they get exportpdf's prompts instead."""
    win = _window(ctx)
    if win is None or not hasattr(win, "print_sheets"):
        yield from cmd_exportpdf(ctx)
        return
    win.print_sheets()
    return
    yield  # pragma: no cover


@command("exportpdf", aliases=("pdf",), mutates=False)
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
    path = yield FileReq("PDF path", default=default_name, save=True,
                         title="Export PDF", filters="PDF (*.pdf)")
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
    pos = yield PointReq("Text position (baseline anchor)")
    if has_text_editor(ctx) or getattr(ctx, "replay_text_inline", False):
        answer = yield TextEditorReq(
            "Text", units="mm", anchor=pos, paper_layout=lay)
        if isinstance(answer, dict):
            ctx.echo("Note placed.")
            return
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
             + (f" (anchored to detail at "
                f"{detail.scale_text(ctx.scene.units)})"
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


def _pattern_choices(ctx) -> list[str]:
    """The fills on offer, spelled the way a prompt spells them.

    Read off the same list a layer is set from, so a fill the app learns
    to draw is offered here without anybody remembering to come back, and
    a pattern loaded from a .pat file is offered beside the app's own.
    """
    return [pattern_label(p) for p in hatch_patterns_of(ctx.scene)]


def _pattern_answer(ctx, answer) -> tuple:
    """(name, definition) for the pattern a prompt was answered with: the
    name as the drawing keeps it, and the HatchPattern a loaded pattern
    is drawn from, None for the app's own."""
    name = pattern_named(ctx.scene, answer) or str(answer).lower()
    return name, ctx.scene.hatch_pattern(name)


def _layer_pattern(ctx) -> str:
    """The Pattern the layer being drawn on wants, as the prompt spells it.

    A layer is a material and a material has a fill, so hatching a wall
    on the Concrete layer is a click and an Enter rather than the same
    decision taken again on every region. A layer whose material has no
    fill leaves the command where it has always been, on lines: a hatch
    drawn by hand is there to be seen.
    """
    fill = ctx.scene.layers.current.hatch
    if fill.lower() not in [p.lower() for p in hatch_patterns_of(ctx.scene)]:
        fill = "lines"
    return pattern_label(fill)


# "paper" still, though it hatches in the model too: the space only says what
# a picked point means, and the model hatch picks curves, never a point. As
# "any", a click on a sheet stepped into the detail under it instead of
# placing the hatch's corner there.
@command("hatch", space="paper")
def cmd_hatch(ctx):
    """Fill a region with a pattern: on a sheet, as it always was, and in
    the model as an object of its own (#33)."""
    lay = _active_layout(ctx)
    if lay is None:
        yield from _hatch_in_the_model(ctx)
        return
    from ..core.layout import Hatch
    choices = _pattern_choices(ctx)
    offered = _layer_pattern(ctx)
    pts = []
    first = yield PointReq("First corner of hatch region "
                           "(or click inside detail linework)",
                           choices={"Mode": ["Corners", "Region"]})
    if ctx.opt("Mode", "Corners") == "Region":
        found = _region_and_fill_at(ctx, lay, first[0], first[1])
        if found is None:
            ctx.echo("No closed linework region found under that point.")
            return
        poly, holes, material, fill = found
        # Its lines lie the way the cut's already do, in the cut's
        # colour; off a cut, the way the layer says.
        look = fill if fill is not None else _layer_look(ctx)
        # The face is already drawn in its material, so that is what the
        # prompt opens on: hatching a cut for real should not change what
        # the cut is made of. Off a cut, or on one left empty, the layer
        # answers as it always did.
        material = pattern_label(material)
        rings = ([list(p) for p in poly],
                 [[list(p) for p in ring] for ring in holes])
        pattern = yield OptionReq(
            "Pattern", options=choices,
            default=material if material in choices else offered,
            preview_fn=lambda answer: Hatch(
                points=rings[0], holes=rings[1],
                pattern=_pattern_answer(ctx, answer)[0], angle=look.angle,
                spacing=look.spacing, color=_color_list(look.color)))
        lay.hatches.append(Hatch(points=rings[0], holes=rings[1],
                                 pattern=_pattern_answer(ctx, pattern)[0],
                                 angle=look.angle, spacing=look.spacing,
                                 color=_color_list(look.color)))
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
    look = _layer_look(ctx)

    def sheet_hatch(answers):
        return Hatch(points=pts,
                     pattern=_pattern_answer(ctx, answers["pattern"])[0],
                     angle=float(answers["angle"]),
                     spacing=float(answers["spacing"]),
                     color=_color_list(look.color))

    answers = yield _hatch_form(ctx, spacing=look.spacing, angle=look.angle,
                                pattern=offered, unit=" (mm)", minimum=0.2,
                                live=sheet_hatch)
    hatch = sheet_hatch(answers)
    lay.hatches.append(hatch)
    ctx.scene.notify()
    ctx.echo(f"Hatch placed ({hatch.pattern}).")


def _hatch_in_the_model(ctx):
    """Hatch the closed planar curves picked, one hatch per region.

    Curves that run through each other leave regions nobody can guess at,
    so those are picked: Rhino's boundary mode (#45), and the pick is the
    one CurveBoolean asks. Anywhere the answer is obvious there is no
    question at all: one closed curve is its own boundary, curves lying
    apart make one hatch each, and a curve inside another is its hole.
    The curves are kept, as Rhino keeps them, and what was made is left
    selected.
    """
    from ..core.hatch import HatchShape
    objs = yield SelectReq("Select closed planar curves to hatch",
                           kinds=("curve",))
    boundaries, refused = [], []
    for obj in objs:
        try:
            g.planar_face(obj.shape)          # closed and flat, or it says
            boundaries.append(obj)
        except (g.GeometryError, Exception):  # noqa: BLE001
            refused.append(obj.name)
    if refused:
        ctx.echo(f"Not hatched, a hatch needs closed flat curves: "
                 f"{', '.join(refused)}.")
    if not boundaries:
        return
    if _curves_overlap(boundaries):
        regions = yield from _regions_to_fill(ctx, boundaries)
    else:
        try:
            regions = g.planar_regions([o.shape for o in boundaries])
        except g.GeometryError as exc:
            ctx.echo(f"Could not make a region to hatch: {exc}")
            return
    if not regions:
        return
    size = max(float(np.ptp(np.array(g.bbox(r)), axis=0).max())
               for r in regions)
    xdir = tuple(ctx.cplane.xdir) if ctx.cplane is not None else None

    def hatches(answers):
        pattern, definition = _pattern_answer(ctx, answers["pattern"])
        return pattern, [HatchShape(region, pattern,
                                    angle=float(answers["angle"]),
                                    spacing=float(answers["spacing"]),
                                    xdir=xdir, definition=definition)
                         for region in regions]

    def live(answers):
        # What OK would make, while the popup is still open; a spacing too
        # fine to draw shows the regions instead, as before.
        from ..core.hatch import HatchGroup
        try:
            made = hatches(answers)[1]
        except g.GeometryError:
            return _region_ghost(regions)
        return made[0] if len(made) == 1 else HatchGroup(made)

    answers = yield _hatch_form(ctx, spacing=_round_spacing(size),
                                preview=_region_ghost(regions), live=live)
    pattern, definition = _pattern_answer(ctx, answers["pattern"])
    made = []
    for region in regions:
        try:
            shape = HatchShape(region, pattern,
                               angle=float(answers["angle"]),
                               spacing=float(answers["spacing"]),
                               xdir=xdir, definition=definition)
        except g.GeometryError as exc:
            ctx.echo(f"Not hatched: {exc}")
            continue
        made.append(ctx.scene.add(shape, name="Hatch"))
    if made:
        ctx.select_result(made)
        ctx.echo(f"{len(made)} hatch{'es' if len(made) != 1 else ''} "
                 f"placed ({pattern}).")


def _curves_overlap(curves) -> bool:
    """Whether any two of these outlines cross, so there is a choice.

    Boundary mode is only worth asking about when the answer is not
    already obvious. Curves that lie apart make one hatch each and a
    curve inside another is its hole, which is what the command has
    always done and what Rhino does; it is two outlines running through
    each other that leave regions nobody can guess at.

    Only pairs whose boxes meet are intersected, so a sheet of separate
    outlines costs a box comparison per pair rather than a boolean, and
    is filled without asking however many outlines it has.
    """
    if len(curves) < 2:
        return False
    faces, areas, boxes = [], [], []
    for obj in curves:
        try:
            face = g.planar_face(obj.shape)
        except (g.GeometryError, Exception):          # noqa: BLE001
            return True            # cannot tell: let the pick decide
        faces.append(face)
        areas.append(g.surface_area(face))
        boxes.append(g.bbox(face))
    lo, hi = np.array(boxes, float).transpose(1, 0, 2)
    tol = g.tol()
    # Every pair's boxes at once. Inclusive, so a flat box (every curve on
    # z=0 has one) still meets the boxes beside it on its own plane.
    meet = np.all((lo[:, None] <= hi[None] + tol)
                  & (lo[None] <= hi[:, None] + tol), axis=2)
    for i, j in zip(*np.nonzero(np.triu(meet, k=1))):
        try:
            common = g.surface_area(
                g.boolean_intersection(faces[i], faces[j]))
        except (g.GeometryError, Exception):          # noqa: BLE001
            continue               # they do not meet at all
        if common <= tol:
            continue               # apart, or touching along an edge
        # Sharing all of one of them is nesting, not crossing.
        if abs(common - areas[i]) > tol and abs(common - areas[j]) > tol:
            return True
    return False


def _hatch_form(ctx, spacing: float, angle: float = 45.0, pattern=None,
                unit: str = "", minimum: float = 1e-6, preview=None,
                live=None):
    """What a hatch is made of, asked as one thing (#45).

    A window shows the three together, so the pattern, how close its lines
    run and which way they lie can be read off and changed in one place,
    the way Rhino's hatch dialog does. Without one they are three prompts
    in a row, as they always were, and a solid pattern is not asked about
    a spacing or an angle it has no use for.

    `preview` is what is about to be filled, ghosted while the question
    stands. A pick of several curves shows the regions as they are
    clicked; where there was nothing to pick there would otherwise be
    nothing to see, and which area a pattern is about to land on is worth
    as much then as it is during the pick.

    `live(answers)` is the hatch the answers would make, shown while the
    popup is open and redrawn as it changes. At the prompt each answer
    shows the hatch it would make with the rest left as they stand.
    """
    def not_solid(answers):
        name, definition = _pattern_answer(ctx, answers.get("pattern", ""))
        return name != "solid" and not (definition and definition.solid)

    first = pattern or _layer_pattern(ctx)
    defaults = {"pattern": first, "spacing": float(spacing),
                "angle": float(angle)}

    def ghost(name):
        if live is not None:
            return lambda value: live({**defaults, name: value})
        return None if preview is None else (lambda _value: preview)

    return FormReq(
        "Hatch", title="Hatch",
        fields=(
            FormField("pattern",
                      OptionReq("Pattern", options=_pattern_choices(ctx),
                                default=first,
                                preview_fn=ghost("pattern"))),
            FormField("spacing",
                      NumberReq(f"Line spacing{unit}", default=float(spacing),
                                minimum=float(minimum),
                                preview_fn=ghost("spacing")),
                      when=not_solid),
            FormField("angle",
                      NumberReq("Angle (degrees)", default=float(angle),
                                preview_fn=ghost("angle")),
                      when=not_solid),
        ),
        preview_fn=live)


def _region_ghost(regions):
    """The area about to be hatched, as one shape to ghost."""
    if not regions:
        return None
    if len(regions) == 1:
        return regions[0]
    try:
        return g.make_compound(list(regions))
    except Exception:                                 # noqa: BLE001
        return regions[0]


def _regions_to_fill(ctx, curves):
    """The regions of several curves that the pick kept, or an empty list.

    Boundary mode. Curves off the first one's plane are dropped with a
    word, and if that leaves a single curve it is its own boundary again.
    """
    try:
        coplanar, origin, normal = coplanar_curves(ctx, curves)
    except (g.GeometryError, Exception) as exc:    # noqa: BLE001
        ctx.echo(f"Could not make a region to hatch: {exc}")
        return []
    if len(coplanar) < 2:
        try:
            return g.planar_regions([o.shape for o in coplanar])
        except g.GeometryError as exc:
            ctx.echo(f"Could not make a region to hatch: {exc}")
            return []
    try:
        regions = g.curve_regions([o.shape for o in coplanar])
    except g.GeometryError as exc:
        ctx.echo(f"Could not make a region to hatch: {exc}")
        return []
    if not regions:
        ctx.echo("The curves share no usable regions.")
        return []
    kept = yield from pick_regions(
        ctx, regions, origin, normal,
        prompt="Pick region to hatch (Enter to finish)")
    if not kept:
        ctx.echo("No regions picked, nothing hatched.")
        return []
    return [regions[i] for i in kept]


@command("hatchpatterns", aliases=("loadpat", "loadhatchpatterns"))
def cmd_hatchpatterns(ctx):
    """Hatch patterns from .pat files (#92): Load installs the patterns in
    one, Delete takes one off again. The app's own are always there.

    An installed pattern is offered in every drawing, as a font is, and a
    drawing saves the patterns it uses, so it is drawn the same on a
    computer that never installed them. AutoCAD's acad.pat and
    acadiso.pat, a Revit export and most patterns found online are .pat
    files.
    """
    # Patterns are not the picked objects': whatever was picked, often the
    # very hatch a pattern is being loaded for, stays.
    held = list(ctx.selection.ids)
    action = yield OptionReq("Hatch patterns", options=["Load", "Delete"],
                             default="Load")
    if action == "Delete":
        yield from _delete_pattern(ctx)
    else:
        yield from _load_patterns(ctx)
    if held:
        ctx.select_result(held)


def _load_patterns(ctx):
    import os
    from ..core.hatch_patterns import PatternError, install, read_pat
    path = yield FileReq("Hatch pattern file", default="~/",
                         title="Load hatch patterns",
                         filters="Hatch patterns (*.pat);;All files (*)")
    path = os.path.abspath(os.path.expanduser(path.strip()))
    source = os.path.splitext(os.path.basename(path))[0]
    try:
        patterns = read_pat(path)
    except (OSError, PatternError) as exc:
        ctx.echo(f"Could not read {os.path.basename(path)}: {exc}")
        return
    try:
        named = install(patterns, source=source)
    except OSError as exc:
        ctx.echo(f"Could not install the patterns: {exc}")
        return
    # what they are called now, in the file's order, for the window that
    # asked for the file to switch to the first
    ctx.scene.loaded_patterns = list(dict.fromkeys(named.values()))
    ctx.scene.notify()
    if not named:
        ctx.echo(f"No hatch patterns in {os.path.basename(path)}.")
        return
    shown = [new if new == old else f"{old} as {pattern_label(new)}"
             for old, new in named.items()]
    listed = ", ".join(shown[:8]) + (", …" if len(shown) > 8 else "")
    ctx.echo(f"Installed {len(named)} hatch pattern"
             f"{'s' if len(named) != 1 else ''} from "
             f"{os.path.basename(path)}: {listed}.")


def _delete_pattern(ctx):
    """Uninstall a pattern, or take one a drawing brought with it out of
    the drawing. Nothing drawn with it changes: a drawing that uses it
    keeps it, and goes on saving it, so deleting is never a way to break
    a drawing."""
    from ..core.hatch_patterns import installed, lookup, resolve, uninstall
    scene = ctx.scene
    names: dict = {}
    for name in (*installed(), *scene.hatch_patterns):
        names.setdefault(name.lower(), name)
    options = sorted(names.values(), key=str.lower)
    if not options:
        ctx.echo("No hatch patterns to delete; the app's own always stay.")
        return
    name = yield OptionReq("Pattern to delete", options=options,
                           default=options[0])
    name = names.get(str(name).lower())
    if name is None:
        return
    in_use = any(scene.hatch_pattern_users(name).values())
    pattern = resolve(scene.hatch_patterns, name)
    was_installed = uninstall(name)
    if in_use:
        if pattern is not None and lookup(scene.hatch_patterns, name) is None:
            scene.hatch_patterns[pattern.name] = pattern
    else:
        for key in [k for k in scene.hatch_patterns
                    if k.lower() == name.lower()]:
            del scene.hatch_patterns[key]
    scene.notify()
    if in_use:
        ctx.echo(f"{'Deleted' if was_installed else 'Kept'} hatch pattern "
                 f"{name}; this drawing uses it and keeps it.")
    else:
        ctx.echo(f"Deleted hatch pattern {name}.")


def _round_spacing(size: float) -> float:
    """A round spacing that draws some twenty-five lines across `size`:
    1, 2 or 5 times a power of ten, so the prompt offers 0.5, not 0.4137."""
    import math
    raw = max(size, 1e-9) / 25.0
    step = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 5, 10):
        if raw <= m * step:
            return float(m * step)
    return float(10 * step)


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
    units = ctx.scene.units
    detail = lay.detail_at(pos[0], pos[1])
    denom = detail.scale_denom if detail and not detail.perspective else (
        lay.details[0].scale_denom if lay.details else 10.0 / TO_MM[units])
    lay.scale_bars.append([pos[0], pos[1], denom])
    ctx.scene.notify()
    ctx.echo(f"Scale bar placed ({format_scale(denom, units)}).")


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
    path = yield FileReq("DXF path",
                         default=f"~/{lay.name if lay else 'model'}.dxf",
                         save=True, title="Export DXF",
                         filters="DXF (*.dxf)")
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
    path = yield FileReq("SVG path", default=f"~/{lay.name}.svg", save=True,
                         title="Export SVG", filters="SVG (*.svg)")
    path = os.path.abspath(os.path.expanduser(path.strip()))
    if not path.endswith(".svg"):
        path += ".svg"
    from ..fileio.svg import export_layout_svg
    export_layout_svg(_window(ctx), lay, path)
    ctx.echo(f"Exported sheet '{lay.name}' to {path}.")


def _layer_look(ctx):
    """How the layer being drawn on hatches: its angle, its spacing on the
    paper and its colour, the pattern aside (`_layer_pattern` has that)."""
    layer = ctx.scene.layers.current
    from ..core.layout import SectionFill
    return SectionFill(layer.hatch, layer.hatch_angle, layer.hatch_spacing,
                       ctx.scene.layers.hatch_rgb(layer.id))


def _color_list(color):
    """A colour as a paper hatch keeps it: [r, g, b], or None for ink."""
    return None if color is None else [float(c) for c in color[:3]]


def _region_at(ctx, lay, px, py):
    """The closed area under a point, as (points, holes, material); see
    `_region_and_fill_at`, which has the fill as well."""
    found = _region_and_fill_at(ctx, lay, px, py)
    return None if found is None else found[:3]


def _region_and_fill_at(ctx, lay, px, py):
    """The closed area under a point, as (points, holes, material, fill).

    A section cut is a ring of material with the bore punched out of it,
    and a hatch dropped on the wall has to leave the bore alone. Any
    other bit of linework is a single loop with nothing inside it.

    The material is the fill the face is already drawn in, off the layer
    it was cut from, so hatching a cut face for real does not change
    what it is made of. Linework that is not a cut has none, and neither
    has the bore: a hole is not made of anything. The fill is the whole
    of how the face is drawn (`SectionFill`), or None off a cut.
    """
    from ..core.layout import cut_patterns, enclosing_polygon
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
    patterns = cut_patterns(data)
    region_fills = getattr(view, "_region_fills", None)
    fills = region_fills(data) if region_fills is not None else []
    for i, region in enumerate(regions):
        if found == region[0][:-1]:
            return (found, [loop[:-1] for loop in region[1:]],
                    patterns[i] if i < len(patterns) else "",
                    fills[i] if i < len(fills) else None)
    return found, [], "", None


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
    hit = annotation_at(lay, p[0], p[1], tol=3.0, scene=ctx.scene)
    if hit is None:
        ctx.echo("Nothing there. Click on a note, dimension, leader or "
                 "hatch.")
        return
    kind, obj = hit
    if kind in ("note", "leader"):
        req = TextReq("Text", default=obj.text.replace("\n", "\\n"))
        if kind == "note" and has_text_editor(ctx):
            from ..ui.text_editor import typography_of
            req = TextEditorReq(
                "Edit text", values=typography_of(obj),
                anchor=(obj.x, obj.y, 0.), paper_layout=lay,
                target_id=obj.id)
        new = yield req
        if kind == "note" and isinstance(new, dict):
            values = dict(new)
            values.pop("output", None)
            values.pop("group_output", None)
            values.pop("solid_depth", None)
            for name, value in values.items():
                setattr(obj, name, value)
            obj.style = ""
        else:
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
