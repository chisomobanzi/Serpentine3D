"""Solid editing: edge fillets/chamfers, capping, intersection, contours."""

from ..core import geometry as g
from .base import OptionReq, SelectReq, command


def _parse_radius(ctx, text):
    from ..utils.units import parse_length
    text = text.strip()
    if "," in text:
        a, _, b = text.partition(",")
        ra = parse_length(a, ctx.scene.units)
        rb = parse_length(b, ctx.scene.units)
        return (ra, rb) if ra and rb else None
    return parse_length(text, ctx.scene.units)


def _edge_size_req(ctx, objs, prompt, build):
    """A radius/chamfer distance dragged off the side of what is selected.

    `build(size)` returns the shape to ghost. The drag starts on the surface
    being cut back, so a 1 mm fillet on a 100 mm box is a 1 mm drag.
    """
    from . import dragging
    from .base import PointReq
    side = tuple(ctx.cplane.xdir)
    base = dragging.edge_point(objs, side)
    read = dragging.distance_from(base)

    def _ghost(p):
        size = read(p)
        if size < 1e-9:
            return None
        try:
            return build(size)
        except g.GeometryError:
            return None

    return read, PointReq(prompt, number_from=(base, side),
                          rubber_from=base, preview_fn=_ghost)


def _subobject_edge_map(ctx):
    """{obj_id: [edge shapes]} from the current sub-object selection."""
    out = {}
    for (obj_id, kind, idx) in ctx.selection.subobjects:
        if kind != "edge":
            continue
        obj = ctx.scene.get(obj_id)
        if obj is None:
            continue
        edges = g.edges_of(obj.shape)
        if 0 <= idx < len(edges):
            out.setdefault(obj_id, []).append(edges[idx])
    return out


@command("filletedge", aliases=("fe",))
def cmd_filletedge(ctx):
    """Fillet edges. Ctrl+Shift-click edges first to fillet only those;
    otherwise fillets every edge of the selected solids."""
    picked = _subobject_edge_map(ctx)
    if picked:
        chain = yield OptionReq("Extend picks to smooth chains?",
                                options=["No", "Yes"], default="No")
        from .base import TextReq
        r_text = yield TextReq("Fillet radius (or start,end for variable)",
                               default="1")
        radius = _parse_radius(ctx, r_text)
        if radius is None:
            ctx.echo("Could not parse the radius.")
            return
        done = 0
        for obj_id, edges in picked.items():
            obj = ctx.scene.get(obj_id)
            if chain == "Yes":
                all_edges = g.edges_of(obj.shape)
                idx_set = set()
                for (oid, kind, idx) in ctx.selection.subobjects:
                    if oid == obj_id and kind == "edge":
                        idx_set.update(g.edge_chain(obj.shape, idx))
                edges = [all_edges[i] for i in sorted(idx_set)]
            try:
                ctx.scene.replace_shape(
                    obj_id, g.fillet_edges(obj.shape, radius, edges=edges))
                done += len(edges)
            except g.GeometryError as exc:
                ctx.echo(f"{obj.name}: {exc}")
        ctx.selection.clear()
        ctx.echo(f"Filleted {done} edge(s).")
        return
    objs = yield SelectReq("Select solids to fillet (Ctrl+Shift-click "
                           "edges beforehand to fillet specific ones)",
                           kinds=("solid", "surface"))
    read, req = _edge_size_req(
        ctx, objs, "Fillet radius (click, or type a number)",
        lambda r: g.make_compound(
            [g.fillet_edges(o.shape, r) for o in objs]))
    radius = read((yield req))
    if radius < 1e-9:
        ctx.echo("Zero radius — nothing filleted.")
        return
    done = 0
    for o in objs:
        try:
            ctx.scene.replace_shape(o.id, g.fillet_edges(o.shape, radius))
            done += 1
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    if done:
        ctx.echo(f"Filleted all edges of {done} object(s) at r={radius:g}.")


@command("chamferedge", aliases=("che",))
def cmd_chamferedge(ctx):
    picked = _subobject_edge_map(ctx)
    if picked:
        chosen = [ctx.scene.get(oid) for oid in picked]
        read, req = _edge_size_req(
            ctx, [o for o in chosen if o is not None],
            "Chamfer distance (click, or type a number)",
            lambda d: g.make_compound(
                [g.fillet_edges(ctx.scene.get(oid).shape, d, edges=edges,
                                chamfer=True)
                 for oid, edges in picked.items()]))
        dist = read((yield req))
        if dist < 1e-9:
            ctx.echo("Zero distance — nothing chamfered.")
            return
        done = 0
        for obj_id, edges in picked.items():
            obj = ctx.scene.get(obj_id)
            try:
                ctx.scene.replace_shape(
                    obj_id, g.fillet_edges(obj.shape, dist, edges=edges,
                                           chamfer=True))
                done += len(edges)
            except g.GeometryError as exc:
                ctx.echo(f"{obj.name}: {exc}")
        ctx.selection.clear()
        ctx.echo(f"Chamfered {done} picked edge(s) at {dist:g}.")
        return
    objs = yield SelectReq("Select solids to chamfer",
                           kinds=("solid", "surface"))
    read, req = _edge_size_req(
        ctx, objs, "Chamfer distance (click, or type a number)",
        lambda d: g.make_compound(
            [g.fillet_edges(o.shape, d, chamfer=True) for o in objs]))
    dist = read((yield req))
    if dist < 1e-9:
        ctx.echo("Zero distance — nothing chamfered.")
        return
    done = 0
    for o in objs:
        try:
            ctx.scene.replace_shape(
                o.id, g.fillet_edges(o.shape, dist, chamfer=True))
            done += 1
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    if done:
        ctx.echo(f"Chamfered {done} object(s) at {dist:g}.")


@command("cap")
def cmd_cap(ctx):
    objs = yield SelectReq("Select open surfaces to cap",
                           kinds=("surface", "solid", "compound"))
    done = 0
    for o in objs:
        try:
            capped = g.cap_holes(o.shape)
            new = ctx.scene.replace_shape(o.id, capped)
            done += 1
            ctx.echo(f"{o.name} -> {new.kind}.")
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
    if done:
        ctx.echo(f"Capped {done} object(s).")


@command("intersect", aliases=("int",))
def cmd_intersect(ctx):
    a = yield SelectReq("Select first object", kinds=("surface", "solid"),
                        max_count=1)
    b = yield SelectReq("Select second object", kinds=("surface", "solid"),
                        max_count=1, allow_preselected=False)
    curves = g.intersect_shapes(a[0].shape, b[0].shape)
    for c in curves:
        ctx.scene.add(c)
    ctx.echo(f"Created {len(curves)} intersection curve(s).")


@command("contour")
def cmd_contour(ctx):
    objs = yield SelectReq("Select objects to contour",
                           kinds=("surface", "solid"))
    axis = yield OptionReq("Contour direction",
                           options=["Z", "X", "Y", "CPlane"], default="Z")
    direction = {"X": (1, 0, 0), "Y": (0, 1, 0), "Z": (0, 0, 1),
                 "CPlane": tuple(ctx.cplane.normal)}[axis]
    from . import dragging
    from .base import PointReq
    # the spacing is a step up the contour axis, so it is dragged up that
    # axis from the bottom of the stack: one drag, one visible gap
    start = dragging.edge_point(objs, tuple(-c for c in direction))
    read = dragging.signed_along(start, direction)
    span = dragging.bounds(objs)
    reach = max(abs(h - lo) for lo, h in zip(*span)) if span else 0.0

    def _levels_to(p):
        step = read(p)
        # a hair of spacing over a big solid is thousands of slices; that is
        # not a preview, it is a hang
        if step < 1e-9 or (reach and step < reach / 200):
            return None
        out = []
        for o in objs:
            try:
                for _, curves in g.contour(o.shape, direction, step):
                    out.extend(curves)
            except g.GeometryError:
                return None
        return g.make_compound(out) if out else None

    sp = yield PointReq("Distance between contours (click, or type a number)",
                        axis_lock=(start, direction),
                        number_from=(start, direction),
                        rubber_from=start, preview_fn=_levels_to)
    spacing = read(sp)
    if spacing < 1e-9:
        ctx.echo("Zero spacing — no contours created.")
        return
    layer = ctx.scene.layers.find_by_name("Contours")
    layer_id = layer.id if layer else ctx.scene.layers.create(
        "Contours", (0.95, 0.75, 0.35)).id
    total = 0
    for o in objs:
        try:
            levels = g.contour(o.shape, direction, spacing)
        except g.GeometryError as exc:
            ctx.echo(f"{o.name}: {exc}")
            continue
        for _, curves in levels:
            for c in curves:
                ctx.scene.add(c, layer_id=layer_id)
                total += 1
    ctx.scene.notify()
    ctx.echo(f"Created {total} contour curve(s) on layer 'Contours' "
             f"(spacing {spacing:g}).")


@command("booleansplit", aliases=("bsplit",))
def cmd_booleansplit(ctx):
    """Split solids with cutters, keeping every piece."""
    targets = yield SelectReq("Select solids to split", kinds=("solid",))
    cutters = yield SelectReq("Select cutting objects",
                              allow_preselected=False)
    total = 0
    for t in targets:
        try:
            pieces = g.split_shape(t.shape, [c.shape for c in cutters])
        except g.GeometryError as exc:
            ctx.echo(f"{t.name}: {exc}")
            continue
        for p in pieces:
            ctx.scene.add(p, layer_id=t.layer_id)
            total += 1
        ctx.scene.remove(t.id)
    ctx.echo(f"Split into {total} piece(s).")


@command("pushpull", aliases=("pp", "moveface"))
def cmd_pushpull(ctx):
    """SketchUp-style push/pull on a planar face.

    Ctrl+Shift-click a face first, then run pushpull with a distance:
    positive pushes the face outward, negative carves inward."""
    faces = [(oid, idx) for (oid, kind, idx) in ctx.selection.subobjects
             if kind == "face"]
    if not faces:
        ctx.echo("Ctrl+Shift-click a planar face first, then run pushpull.")
        return
        yield  # pragma: no cover
    from . import dragging
    from .base import PointReq
    # the face knows which way it goes, so the drag rides its own normal:
    # out of the solid adds material, into it carves
    first = ctx.scene.get(faces[0][0])
    origin, normal = g.face_point_normal(g.faces_of(first.shape)[faces[0][1]])
    read = dragging.signed_along(origin, normal)

    def _push_to(p):
        v = read(p)
        if abs(v) < 1e-9:
            return None
        made = []
        for obj_id, idx in faces:
            obj = ctx.scene.get(obj_id)
            if obj is None:
                continue
            try:
                made.append(g.push_pull(obj.shape, idx, v))
            except g.GeometryError:
                return None
        return g.make_compound(made) if made else None

    dp = yield PointReq("Distance (drag the face, or type a number — "
                        "positive = outward, negative = cut)",
                        axis_lock=(origin, normal),
                        number_from=(origin, normal),
                        rubber_from=origin, preview_fn=_push_to)
    dist = read(dp)
    if abs(dist) < 1e-9:
        ctx.echo("Zero distance — nothing moved.")
        return
    done = 0
    for obj_id, idx in faces:
        obj = ctx.scene.get(obj_id)
        if obj is None:
            continue
        try:
            ctx.scene.replace_shape(
                obj_id, g.push_pull(obj.shape, idx, dist))
            done += 1
        except g.GeometryError as exc:
            ctx.echo(f"{obj.name}: {exc}")
    ctx.selection.clear()
    if done:
        ctx.echo(f"Push/pulled {done} face(s) by "
                 f"{ctx.scene.format_length(dist)}.")
