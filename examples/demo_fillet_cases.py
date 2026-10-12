# One scene, every hard fillet case this branch handled. Run headless:
#   uv run python -m serpentine3d.batch examples/demo_fillet_cases.py
# then open it in the app:
#   uv run python -m serpentine3d build/demo_fillet_cases.serp
import math

SCENE = "build/demo_fillet_cases.serp"


def extent(e):
    mn, mx = geo.bbox(e)
    return [mx[i] - mn[i] for i in range(3)]


def edge_at(shape, span, near, eps=1e-4):
    """The straight edge spanning the `span` axes, starting at `near`
    (fixed on the other axes, a start point along the span)."""
    for e in geo.edges_of(shape):
        ex = extent(e)
        axes = [k for k in range(3) if ex[k] > 1e-3]
        if axes != list(span):
            continue
        mn, mx = geo.bbox(e)
        if (all(abs(mn[k] - near[k]) < eps and abs(mx[k] - near[k]) < eps
                for k in range(3) if k not in span)
                and all(abs(mn[k] - near[k]) < eps for k in span)):
            return e
    raise AssertionError(f"edge not found: span={span} near={near}")


def edges_at_vertex(shape, vertex, eps=1e-4):
    out = []
    for i, e in enumerate(geo.edges_of(shape)):
        ex = extent(e)
        if len([k for k in range(3) if ex[k] > 1e-3]) != 1:
            continue
        mn, mx = geo.bbox(e)
        if all(mn[k] - eps <= vertex[k] <= mx[k] + eps for k in range(3)):
            out.append(i)
    assert len(out) == 3, out
    return out


def report(name, expect=None, rel=1e-3):
    v = doc.volume(name)
    note = ""
    if expect is not None:
        ok = math.isclose(v, expect, rel_tol=rel)
        note = f"  expected {expect:.4f} -> {'ok' if ok else 'MISMATCH'}"
    print(f"  {name:16s} volume={v:14.4f}{note}")


# 1. Concave inner edge: the blend ADDS material into an inside corner.
base = geo.make_box((0, 0, 0), 10, 10, 10)
notch = geo.make_box((5, 0, 0), 5, 5, 10)
lblock = geo.boolean_difference(base, notch)
concave = geo.fillet_edges(lblock, 1.0, edges=[edge_at(lblock, [2], (5, 5, 0))])
doc.add(geo.translate(concave, (0, 0, 0)), name="ConcaveFillet")

# 2. Three edges meeting at one vertex, one radius, the corner closes.
box = geo.make_box((0, 0, 0), 10, 10, 10)
picks = edges_at_vertex(box, (0, 0, 0))
corner3 = geo.fillet_edges(box, 1.0, edges=[geo.edges_of(box)[i] for i in picks])
doc.add(geo.translate(corner3, (30, 0, 0)), name="VertexThree")

# 3. Same vertex, different sizes per edge: 1 / 1 / 3 still closes.
box = geo.make_box((0, 0, 0), 10, 10, 10)
picks = edges_at_vertex(box, (0, 0, 0))
edges = geo.edges_of(box)
mixed = geo.fillet_edges(box, radii=[3.0, 1.0, 1.0],
                         edges=[edges[i] for i in picks])
doc.add(geo.translate(mixed, (60, 0, 0)), name="VertexMixed")

# 4. A closed rim (the cylinder's top circle) through the filletedge
#    command, by preselecting the edge and refusing chain extension.
doc.add(geo.make_cylinder((0, 0, 0), 5.0, 10.0), name="RimFillet")
rim_obj = doc.get("RimFillet")
mn, mx = geo.bbox(rim_obj.shape)
rim_idx = next(i for i, e in enumerate(geo.edges_of(rim_obj.shape))
               if extent(e)[2] < 1e-3 and geo.bbox(e)[1][2] > 9.9)
doc.selection.set_subobjects([(rim_obj.id, "edge", rim_idx)])
msgs = doc.run("filletedge", ["No", "1"])
print("  filletedge rim:", " | ".join(msgs))

# 5. A variable law tapering to ZERO at its end, through the command's
#    u:r law syntax.
doc.add(geo.make_box((0, 0, 0), 10, 10, 10), name="TaperLaw")
taper_obj = doc.get("TaperLaw")
doc.selection.set_subobjects([(taper_obj.id, "edge", 0)])
msgs = doc.run("filletedge", ["No", "0:0;0.5:6;1:0.5", "Smooth"])
print("  filletedge taper:", " | ".join(msgs))
doc.run("move", ["TaperLaw", "", "0,0,0", "90,0,0"])

# 6. A fillet laid next to an existing fillet (the new edge runs against
#    the blend's tangent face).
box = geo.make_box((0, 0, 0), 10, 10, 10)
edges = geo.edges_of(box)
v0 = edge_at(box, [2], (0, 0, 0))
once = geo.fillet_edges(box, 1.0, edges=[v0])
again = geo.fillet_edges(
    once, 0.5,
    edges=[e for e in geo.edges_of(once)
           if extent(e)[0] > 5 and extent(e)[1] < 1e-3 and extent(e)[2] < 1e-3
           and geo.bbox(e)[0][1] < 1e-3 and geo.bbox(e)[0][2] < 1e-3])
doc.add(geo.translate(again, (120, 0, 0)), name="FilletOnFillet")

# 7. A space-curve intersection edge: the T of two cylinders, filleting
#    the curved seam where their walls cross.
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
v = geo.make_cylinder((0, 0, 0), 5.0, 20.0)
h = BRepPrimAPI_MakeCylinder(
    gp_Ax2(gp_Pnt(-5, 4, 10), gp_Dir(1, 0, 0)), 3.0, 20.0).Shape()
tee = geo.boolean_union(v, h)
seam = next(e for e in geo.edges_of(tee)
            if all(d > 0.3 for d in extent(e)) and extent(e)[2] < 8.0)
seam_fillet = geo.fillet_edges(tee, 0.8, edges=[seam])
doc.add(geo.translate(seam_fillet, (150, 0, 0)), name="SpaceCurve")

# 8. Extreme model scales both hold their blends.
doc.add(geo.fillet_edges(geo.make_box((0, 0, 0), 0.01, 0.01, 0.01), 0.001),
        name="TinyScale")
doc.run("move", ["TinyScale", "", "0,0,0", "0,40,0"])
doc.add(geo.fillet_edges(
    geo.make_box((0, 0, 0), 10000, 10000, 10000), 1000.0),
    name="HugeScale")
doc.run("move", ["HugeScale", "", "0,0,0", "30000,30000,0"])

# 9. Two refusals, reported instead of returned broken: a radius wider
#    than the plate it runs along, and a radius that meets the far side.
doc.add(geo.make_box((0, 0, 0), 20, 20, 1), name="PlateRefused")
doc.run("move", ["PlateRefused", "", "0,0,0", "40,40,0"])
try:
    msgs = doc.run("filletedge", ["PlateRefused", "", "0.6"])
    print(f"  PlateRefused r=0.6 refused, as designed: {' | '.join(msgs)}")
except Exception as exc:
    print(f"  PlateRefused r=0.6 refused, as designed: {exc}")

doc.add(geo.make_box((0, 0, 0), 10, 10, 10), name="MeetRefused")
doc.run("move", ["MeetRefused", "", "0,0,0", "80,40,0"])
try:
    msgs = doc.run("filletedge", ["MeetRefused", "", "5"])
    print(f"  MeetRefused r=5 refused, as designed: {' | '.join(msgs)}")
except Exception as exc:
    print(f"  MeetRefused r=5 refused, as designed: {exc}")

print("scene contents:")
report("ConcaveFillet", 750 + (1 - math.pi / 4) * 10)
report("VertexThree", 993.7293, rel=1e-4)
report("VertexMixed")
report("RimFillet", 778.9574, rel=1e-4)
report("TaperLaw")
report("FilletOnFillet")
report("SpaceCurve", 2000.764, rel=1e-4)
report("TinyScale")
report("HugeScale")
report("PlateRefused", 400.0)
report("MeetRefused", 1000.0)

doc.save(SCENE)
print(f"saved {SCENE} with {len(doc.objects())} objects")
