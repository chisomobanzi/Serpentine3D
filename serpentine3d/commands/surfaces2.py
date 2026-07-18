"""Second surface/curve wave: patch, blends, projection, helix, text,
unroll."""

from ..core import geometry as g
from .base import (
    IntReq, LengthReq, NumberReq, OptionReq, PointReq, SelectReq, TextReq,
    command,
)


@command("patch", aliases=("networksrf",))
def cmd_patch(ctx):
    curves = yield SelectReq("Select boundary curves", kinds=("curve",),
                             min_count=2)
    srf = g.patch_surface([c.shape for c in curves])
    obj = ctx.scene.add(srf)
    ctx.echo(f"Created {obj.name} through {len(curves)} boundary curves.")


@command("blendcrv", aliases=("blend",))
def cmd_blendcrv(ctx):
    a = yield SelectReq("Select first curve", kinds=("curve",), max_count=1)
    b = yield SelectReq("Select second curve", kinds=("curve",),
                        max_count=1, allow_preselected=False)
    cont = yield OptionReq("Continuity", options=["Tangent", "Position"],
                           default="Tangent")
    blend = g.blend_curves(a[0].shape, b[0].shape,
                           continuity=cont.lower())
    obj = ctx.scene.add(blend)
    ctx.echo(f"Created blend {obj.name} ({cont.lower()}).")


@command("project")
def cmd_project(ctx):
    curves = yield SelectReq("Select curves to project", kinds=("curve",))
    targets = yield SelectReq("Select target surface",
                              kinds=("surface", "solid"), max_count=1,
                              allow_preselected=False)
    direction = tuple(-c for c in ctx.cplane.normal)
    n = 0
    for c in curves:
        try:
            for piece in g.project_curve(c.shape, targets[0].shape,
                                         direction):
                ctx.scene.add(piece, layer_id=c.layer_id)
                n += 1
        except g.GeometryError as exc:
            ctx.echo(f"{c.name}: {exc}")
    ctx.echo(f"Projected {n} curve(s) onto {targets[0].name}.")


@command("pull")
def cmd_pull(ctx):
    curves = yield SelectReq("Select curves to pull", kinds=("curve",))
    targets = yield SelectReq("Select target surface",
                              kinds=("surface", "solid"), max_count=1,
                              allow_preselected=False)
    n = 0
    for c in curves:
        try:
            for piece in g.pull_curve(c.shape, targets[0].shape):
                ctx.scene.add(piece, layer_id=c.layer_id)
                n += 1
        except g.GeometryError as exc:
            ctx.echo(f"{c.name}: {exc}")
    ctx.echo(f"Pulled {n} curve(s) onto {targets[0].name}.")


@command("helix")
def cmd_helix(ctx):
    center = yield PointReq("Center of helix base")
    radius = yield LengthReq("Radius", minimum=1e-9)
    pitch = yield LengthReq("Pitch (rise per turn)", minimum=1e-9)
    turns = yield NumberReq("Number of turns", default=5.0, minimum=0.01)
    obj = ctx.scene.add(g.make_helix(center, radius, pitch, turns))
    ctx.echo(f"Created {obj.name} ({turns:g} turns).")


@command("textobject", aliases=("textcurves",))
def cmd_textobject(ctx):
    from ..core.text import text_curves
    content = yield TextReq("Text")
    height = yield LengthReq("Text height", default=10.0, minimum=1e-6)
    position = yield PointReq("Position (baseline start)")
    curves = text_curves(content, height)
    made = []
    for c in curves:
        made.append(ctx.scene.add(g.translate(c, position)))
    ctx.echo(f"Created {len(made)} text outline curve(s) — extrude or "
             "planarsrf them for solid lettering.")


@command("unrollsrf", aliases=("unroll",))
def cmd_unrollsrf(ctx):
    objs = yield SelectReq("Select surfaces to unroll (planar, cylindrical "
                           "or conical faces)", kinds=("surface", "solid"))
    layer = ctx.scene.layers.find_by_name("Unrolled")
    layer_id = layer.id if layer else ctx.scene.layers.create(
        "Unrolled", (0.55, 0.85, 0.65)).id
    offset_x = 0.0
    total = 0
    for o in objs:
        for face in g.faces_of(o.shape):
            try:
                curves = g.unroll_face(face)
            except g.GeometryError as exc:
                ctx.echo(f"{o.name}: {exc}")
                continue
            import numpy as np
            mins = np.full(3, np.inf)
            maxs = np.full(3, -np.inf)
            for c in curves:
                mn, mx = g.bbox(c)
                mins = np.minimum(mins, mn)
                maxs = np.maximum(maxs, mx)
            shift = (offset_x - mins[0], -mins[1], 0)
            for c in curves:
                ctx.scene.add(g.translate(c, shift), layer_id=layer_id)
                total += 1
            offset_x += (maxs[0] - mins[0]) + max(
                (maxs[0] - mins[0]) * 0.1, 1.0)
    ctx.scene.notify()
    if total:
        ctx.echo(f"Unrolled {total} boundary curve(s) onto layer "
                 "'Unrolled' (laid out along +X from the origin).")

@command("pipe")
def cmd_pipe(ctx):
    rails = yield SelectReq("Select rail curves", kinds=("curve",))

    def _preview(r):
        try:
            return g.make_compound(
                [g.pipe(o.shape, r, cap=False) for o in rails])
        except g.GeometryError:
            return None

    radius = yield LengthReq("Pipe radius", minimum=1e-9, default=1.0,
                             choices={"Cap": ["Yes", "No"]},
                             preview_fn=_preview)
    cap = ctx.opt("Cap", "Yes") == "Yes"
    made = []
    for o in rails:
        try:
            made.append(ctx.scene.add(g.pipe(o.shape, radius, cap=cap),
                                      layer_id=o.layer_id))
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    ctx.echo(f"Piped {len(made)} curve(s).")


@command("edgesrf", aliases=("srfedges",))
def cmd_edgesrf(ctx):
    curves = yield SelectReq("Select 2, 3 or 4 connected curves",
                             kinds=("curve",), min_count=2, max_count=4)
    srf = g.edge_surface([c.shape for c in curves])
    obj = ctx.scene.add(srf)
    ctx.echo(f"Created {obj.name} from {len(curves)} edge curves.")


@command("dupborder")
def cmd_dupborder(ctx):
    objs = yield SelectReq("Select surfaces or polysurfaces",
                           kinds=("surface", "solid"))
    made = []
    for o in objs:
        for w in g.free_boundaries(o.shape):
            made.append(ctx.scene.add(w, layer_id=o.layer_id))
    if made:
        ctx.echo(f"Duplicated {len(made)} border curve(s).")
    else:
        ctx.echo("No naked borders found (solids have none).")


@command("dupedge")
def cmd_dupedge(ctx):
    """Duplicate Ctrl+Shift-picked edges as curves."""
    from .solids_edit import _subobject_edge_map
    picked = _subobject_edge_map(ctx)
    if not picked:
        ctx.echo("Ctrl+Shift-click edges first, then run DupEdge.")
        yield from ()
        return
    made = []
    for obj_id, edges in picked.items():
        obj = ctx.scene.get(obj_id)
        for e in edges:
            made.append(ctx.scene.add(g.copy_shape(e),
                                      layer_id=obj.layer_id))
    ctx.echo(f"Duplicated {len(made)} edge(s) as curves.")
    yield from ()


@command("untrim")
def cmd_untrim(ctx):
    objs = yield SelectReq(
        "Select trimmed surfaces",
        kinds=("surface",),
        choices={"Mode": ["Holes", "All"]})
    holes_only = ctx.opt("Mode", "Holes") == "Holes"
    n = 0
    for o in objs:
        try:
            ctx.scene.replace_shape(o.id,
                                    g.untrim(o.shape, holes_only=holes_only))
            n += 1
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    ctx.echo(f"Untrimmed {n} surface(s)"
             + (" (holes removed)." if holes_only else " (all trims)."))


@command("extractisocurve", aliases=("isocurve",))
def cmd_extractisocurve(ctx):
    srfs = yield SelectReq("Select surface", kinds=("surface",), max_count=1)
    o = srfs[0]
    made = 0
    while True:
        p = yield PointReq("Point on surface (Enter to finish)",
                           allow_empty=True,
                           choices={"Direction": ["U", "V", "Both"]})
        if p is None:
            break
        d = ctx.opt("Direction", "U").lower()
        for along in (("u", "v") if d == "both" else (d,)):
            try:
                ctx.scene.add(g.iso_curve(o.shape, p, along),
                              layer_id=o.layer_id)
                made += 1
            except g.GeometryError as exc:
                ctx.echo(str(exc))
    ctx.echo(f"Extracted {made} isocurve(s).")


@command("dupfaceborder")
def cmd_dupfaceborder(ctx):
    """Duplicate the border wires of Ctrl+Shift-picked faces as curves."""
    from ..core import occ
    from OCP.TopExp import TopExp_Explorer
    picked = []
    for (obj_id, kind, idx) in ctx.selection.subobjects:
        if kind != "face":
            continue
        obj = ctx.scene.get(obj_id)
        if obj is None:
            continue
        faces = g.faces_of(obj.shape)
        if 0 <= idx < len(faces):
            picked.append((obj, faces[idx]))
    if not picked:
        ctx.echo("Ctrl+Shift-click faces first, then run DupFaceBorder.")
        yield from ()
        return
    made = 0
    for obj, face in picked:
        exp = TopExp_Explorer(face, occ.WIRE)
        while exp.More():
            ctx.scene.add(g.copy_shape(exp.Current()),
                          layer_id=obj.layer_id)
            made += 1
            exp.Next()
    ctx.echo(f"Duplicated {made} border wire(s) as curves.")
    yield from ()


def _picked_face_edges(ctx):
    """[(obj, face_shape, edge_shape, edge_index)] from Ctrl+Shift picks."""
    out = []
    for (obj_id, kind, idx) in ctx.selection.subobjects:
        if kind != "edge":
            continue
        obj = ctx.scene.get(obj_id)
        if obj is None:
            continue
        edges = g.edges_of(obj.shape)
        faces = g.faces_of(obj.shape)
        if not (0 <= idx < len(edges)) or not faces:
            continue
        edge = edges[idx]
        support = next(
            (f for f in faces
             if any(e.IsSame(edge) for e in g.edges_of(f))), faces[0])
        out.append((obj, support, edge, idx))
    return out


@command("extendsrf")
def cmd_extendsrf(ctx):
    """Extend a surface past a Ctrl+Shift-picked boundary edge."""
    picked = _picked_face_edges(ctx)
    if not picked:
        ctx.echo("Ctrl+Shift-click a surface boundary edge first, "
                 "then run ExtendSrf.")
        yield from ()
        return
    obj, _, _, idx = picked[0]

    def _preview(d):
        try:
            return g.extend_surface(obj.shape, idx, d)
        except g.GeometryError:
            return None

    length = yield LengthReq("Extension length", minimum=1e-9, default=1.0,
                             preview_fn=_preview)
    ctx.scene.replace_shape(obj.id, g.extend_surface(obj.shape, idx, length))
    ctx.echo(f"Extended {obj.name} by {length:g}.")


@command("blendsrf")
def cmd_blendsrf(ctx):
    """G1 blend surface between two Ctrl+Shift-picked surface edges."""
    picked = _picked_face_edges(ctx)
    if len(picked) != 2:
        ctx.echo("Ctrl+Shift-click one edge on each of two surfaces, "
                 "then run BlendSrf.")
        yield from ()
        return
    (oa, fa, ea, _), (ob, fb, eb, _) = picked
    blend = g.blend_surfaces(fa, ea, fb, eb)
    obj = ctx.scene.add(blend, layer_id=oa.layer_id)
    ctx.echo(f"Created blend {obj.name} between "
             f"{oa.name} and {ob.name}.")
    yield from ()
