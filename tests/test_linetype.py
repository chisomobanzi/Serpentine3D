"""Linetypes — dash patterns defined in model units. TDD on the pure core:
splitting a polyline into dash segments, and by-layer resolution.
"""

import numpy as np

from serpentine3d.core import linetype


def _drawn_length(segs):
    return sum(float(np.linalg.norm(np.subtract(b, a))) for a, b in segs)


def test_continuous_is_passthrough():
    pts = [(0, 0, 0), (10, 0, 0)]
    segs = linetype.dash_polyline(pts, linetype.pattern_for("Continuous"))
    assert len(segs) == 1
    assert _drawn_length(segs) == 10


def test_dashed_leaves_gaps():
    pts = [(0, 0, 0), (20, 0, 0)]
    segs = linetype.dash_polyline(pts, [5, 5])       # 5 on, 5 off
    # roughly half the length is drawn, in two dashes
    assert len(segs) == 2
    assert abs(_drawn_length(segs) - 10) < 0.6
    # the first dash starts at the polyline start
    assert np.allclose(segs[0][0], [0, 0, 0])


def test_scale_changes_dash_density():
    pts = [(0, 0, 0), (40, 0, 0)]
    coarse = linetype.dash_polyline(pts, [5, 5], scale=2.0)
    fine = linetype.dash_polyline(pts, [5, 5], scale=0.5)
    assert len(fine) > len(coarse)


def test_dashing_follows_corners():
    # an L-shaped polyline: dashes continue across the vertex, arc-length based
    pts = [(0, 0, 0), (10, 0, 0), (10, 10, 0)]
    segs = linetype.dash_polyline(pts, [3, 3])
    # every emitted segment lies on one of the two legs (no diagonal shortcuts)
    for a, b in segs:
        on_leg1 = abs(a[1]) < 1e-6 and abs(b[1]) < 1e-6
        on_leg2 = abs(a[0] - 10) < 1e-6 and abs(b[0] - 10) < 1e-6
        assert on_leg1 or on_leg2


def test_bylayer_resolution():
    assert linetype.resolve("ByLayer", "Dashed") == "Dashed"
    assert linetype.resolve("Hidden", "Dashed") == "Hidden"      # object wins
    assert linetype.resolve(None, "Center") == "Center"


def test_known_names_have_patterns():
    for name in ("Continuous", "Dashed", "Dotted", "Hidden", "Center"):
        assert name in linetype.LINETYPES
    assert linetype.pattern_for("Continuous") == []
    assert len(linetype.pattern_for("Dashed")) >= 2


def test_linetype_persists_through_serp(tmp_path):
    from serpentine3d import fileio
    from serpentine3d.core import geometry as g
    from serpentine3d.core.scene import Scene
    sc = Scene()
    lyr = sc.layers.create("Hiddens")
    sc.layers.set_linetype(lyr.id, "Hidden")
    o = sc.add(g.make_circle((0, 0, 0), 5), name="c1")
    sc.update(o.id, linetype="Dashed")
    p = str(tmp_path / "x.serp")
    fileio.export_file(sc, p)

    sc2 = Scene()
    fileio.import_file(sc2, p)
    assert sc2.layers.find_by_name("Hiddens").linetype == "Hidden"
    assert sc2.find_by_name("c1").linetype == "Dashed"


def test_linetype_command_sets_objects():
    from serpentine3d.scripting import Document
    doc = Document()
    doc.add(doc.geo.make_circle((0, 0, 0), 5), name="c1")
    doc.run("linetype", ["c1", "", "Center"])        # select, finish, choose
    assert doc.get("c1").linetype == "Center"


def test_hlr_per_shape_occlusion():
    """Dashed-solid export relies on per-shape visible edges from ONE
    occlusion-correct HLR pass: a bar behind a solid must lose the hidden
    portion, yet still be reported as its own shape (so it keeps its linetype).
    """
    from serpentine3d.core import geometry as g
    from serpentine3d.core import hlr
    back = g.make_box((-25, 6, -20), 40, 12, 10)
    front = g.make_box((5, -5, 10), 30, 30, 20)      # covers the bar's right end

    def vlen(edges):
        return sum(float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())
                   for p in hlr.edges_to_polylines(edges))

    both = hlr.hlr_project_safe([front, back], origin=(0, 0, 0),
                                view_dir=(0, 0, 1), x_dir=(1, 0, 0))
    assert len(both["visible_by_shape"]) == 2         # one edge list per shape
    solo = hlr.hlr_project_safe([back], origin=(0, 0, 0),
                                view_dir=(0, 0, 1), x_dir=(1, 0, 0))
    # the bar hidden behind the front solid shows less than the bar alone
    assert vlen(both["visible_by_shape"][1]) < vlen(solo["visible_by_shape"][0])
