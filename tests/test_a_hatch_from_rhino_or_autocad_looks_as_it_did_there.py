"""A hatch read from a .3dm or a .dxf is drawn as Rhino or AutoCAD drew it.

Asked for: imported hatches look exactly as they did in the program they
came from. A .3dm's hatch comes in with the pattern of the file's own
pattern table, at its scale and rotation, laid from its base point in its
plane; a .dxf's with the lines the file writes out. Both are checked line
for line: the Rhino fixture holds the lines Rhino's Explode gives for each
of its hatches (tests/data/make_rhino_hatches.py), and a DXF is checked
against ezdxf's own hatching, which reads the same lines the way AutoCAD
does.

A line that lies along the boundary is the boundary, and is left out as
Rhino leaves it out. A dot is drawn as the shortest dash; Rhino's Explode
gives no line for one, so dots are left out of the comparison.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pytest

from serpentine3d.core.hatch import HatchShape
from serpentine3d.core.scene import Scene

DATA = Path(__file__).parent / "data"


def _mids(segs):
    return np.array([[(a[k] + b[k]) / 2 for k in range(3)]
                     + [math.dist(a, b)] for a, b in segs], float)


def _unmatched(ref, ours, tol):
    """How many of `ref` have no segment of `ours` at the same place and
    of the same length."""
    if not len(ref):
        return 0
    m_o = _mids(ours)
    missing = 0
    for row in _mids(ref):
        d = np.linalg.norm(m_o[:, :3] - row[:3], axis=1)
        j = int(d.argmin())
        if d[j] > tol or abs(m_o[j, 3] - row[3]) > tol:
            missing += 1
    return missing


# --- Rhino ------------------------------------------------------------------

@pytest.fixture(scope="module")
def rhino_hatches():
    """The file's hatches in its own unit, metres, as Rhino's lines are. A
    millimetre drawing takes them a thousand times larger (#101)."""
    from serpentine3d.fileio import rhino
    items = rhino.import_3dm(str(DATA / "rhino_hatches.3dm"), units="m")
    return {name: shape for name, shape, _meta in items}


@pytest.fixture(scope="module")
def rhino_lines():
    return json.loads((DATA / "rhino_hatch_lines.json").read_text())


def test_the_file_s_pattern_table_is_read():
    from serpentine3d.fileio.rhino_hatch import read_hatch_patterns

    table = read_hatch_patterns(str(DATA / "rhino_hatches.3dm"))
    by_name = {p.name: p for p in table.values()}
    assert {"BRICK", "DASHDOT", "Hatch1", "Hatch2", "Grid", "Plus",
            "Solid"} <= set(by_name)
    assert by_name["Solid"].solid
    assert len(by_name["Hatch2"].lines) == 2
    assert by_name["DASHDOT"].lines[0].dashes == pytest.approx(
        (0.3, -0.1, 0.0, -0.1))


def test_every_hatch_comes_in_as_a_hatch(rhino_hatches):
    assert sorted(rhino_hatches) == [f"H{k}" for k in range(9)]
    assert all(isinstance(s, HatchShape) for s in rhino_hatches.values())
    assert rhino_hatches["H6"].solid


def test_a_pattern_that_draws_like_the_app_s_own_is_that_one(rhino_hatches):
    """Rhino's Plus, HatchDash and Grid60 are the app's Plus, Dash and
    Triangles, and a brick written in a file is Brick."""
    assert rhino_hatches["H1"].pattern == "dash"
    assert rhino_hatches["H2"].pattern == "plus"
    assert rhino_hatches["H3"].pattern == "brick"
    assert rhino_hatches["H5"].pattern == "triangles"
    assert rhino_hatches["H0"].pattern == "Hatch2"


@pytest.mark.parametrize("name", [f"H{k}" for k in range(9) if k != 6])
def test_every_line_is_where_rhino_draws_it(rhino_hatches, rhino_lines,
                                            name):
    """Scaled, turned, from a moved base point, round a hole and off the
    XY plane: each of Rhino's lines is one of ours, and each of ours but
    the dots is one of Rhino's."""
    hatch = rhino_hatches[name]
    ours = hatch.pattern_segments()
    ref = [tuple(map(tuple, seg)) for seg in rhino_lines[name]
           if math.dist(*seg) > 1e-9]
    # the circle's boundary is sampled, so its line ends are a hair out
    tol = 1e-3 if name == "H7" else 1e-4
    assert _unmatched(ref, ours, tol) == 0
    dot = 0.1 * hatch.spacing
    dashes = [s for s in ours if math.dist(*s) > dot]
    assert _unmatched(dashes, ref, tol) == 0


def test_a_hatch_off_the_xy_plane_stays_in_its_plane(rhino_hatches):
    for a, b in rhino_hatches["H8"].pattern_segments():
        assert a[1] == pytest.approx(40.0) and b[1] == pytest.approx(40.0)


def test_a_drawing_in_other_units_takes_the_pattern_at_its_size(
        rhino_hatches):
    """Into millimetres, each hatch's lines are a thousand times longer and
    further apart, as its region is: the pattern scales with the drawing,
    not just the boundary round it."""
    from serpentine3d.fileio import rhino

    mm = {name: shape for name, shape, _meta in
          rhino.import_3dm(str(DATA / "rhino_hatches.3dm"), units="mm")}
    for name in ("H0", "H3", "H4", "H8"):
        hatch = rhino_hatches[name]
        assert mm[name].spacing == pytest.approx(1000 * hatch.spacing)
        ours = mm[name].pattern_segments()
        ref = [tuple(tuple(1000 * c for c in end) for end in seg)
               for seg in hatch.pattern_segments()]
        assert len(ours) == len(ref)
        assert _unmatched(ref, ours, 1e-3) == 0


def test_an_imported_pattern_is_offered_in_the_drawing():
    from serpentine3d import fileio

    scene = Scene()
    fileio.import_file(scene, str(DATA / "rhino_hatches.3dm"))
    assert {"Hatch2", "Hatch1", "Grid", "DASHDOT"} <= set(scene.hatch_patterns)
    assert "Plus" not in scene.hatch_patterns, "it is the app's own Plus"


def test_a_hatch_crosses_between_import_processes(rhino_hatches):
    from serpentine3d.fileio.rhino_parallel import _decode, _encode

    hatch = rhino_hatches["H4"]
    back = _decode(_encode(hatch))
    assert isinstance(back, HatchShape)
    assert back.definition == hatch.definition
    assert len(back.pattern_segments()) == len(hatch.pattern_segments())


# --- DXF --------------------------------------------------------------------

def _dxf_with(tmp_path, name, angle=0.0, scale=1.0, shift=None):
    ezdxf = pytest.importorskip("ezdxf")
    doc = ezdxf.new("R2010")
    doc.header["$MEASUREMENT"] = 1
    hatch = doc.modelspace().add_hatch()
    hatch.set_pattern_fill(name, angle=angle, scale=scale)
    hatch.paths.add_polyline_path([(0, 0), (50, 0), (50, 40), (10, 50)],
                                  is_closed=True)
    hatch.paths.add_polyline_path([(20, 15), (30, 15), (30, 25), (20, 25)],
                                  is_closed=True)
    if shift is not None:
        hatch.set_pattern_definition(
            [[ln.angle, (ln.base_point[0] + shift[0],
                         ln.base_point[1] + shift[1]), ln.offset,
              ln.dash_length_items] for ln in hatch.pattern.lines])
    path = tmp_path / f"{name}.dxf"
    doc.saveas(path)
    return path


def _imported(path):
    from serpentine3d.fileio import dxf
    scene = Scene()
    dxf.import_dxf(scene, str(path))
    hatches = [o.shape for o in scene.all() if o.kind == "hatch"]
    return scene, hatches


def _autocad_lines(path):
    """ezdxf's hatching of the file, dots, the slivers it leaves where a
    line grazes a corner and the lines that lie along the boundary left
    out."""
    import ezdxf
    from ezdxf.render.hatching import hatch_entity
    entity = ezdxf.readfile(path).modelspace().query("HATCH")[0]
    out = []
    for a, b in hatch_entity(entity, jiggle_origin=False):
        if (a - b).magnitude < 1e-3:
            continue
        if (abs(a.y - b.y) < 1e-9 and min(abs(a.y), abs(a.y - 15),
                                          abs(a.y - 25)) < 1e-9) or \
                (abs(a.x - b.x) < 1e-9 and min(abs(a.x - 50), abs(a.x - 20),
                                               abs(a.x - 30)) < 1e-9):
            continue
        out.append((tuple(a), tuple(b)))
    return out


@pytest.mark.parametrize("name, angle, scale, shift", [
    ("ANSI31", 0.0, 1.0, None),
    ("ANSI31", 30.0, 2.0, None),
    ("ANSI37", 10.0, 3.0, (2.5, 1.0)),
    ("DASH", 15.0, 2.0, None),
    ("HONEY", 0.0, 1.5, None),
    ("BRICK", 0.0, 1.0, None),
])
def test_every_line_is_where_autocad_draws_it(tmp_path, name, angle, scale,
                                              shift):
    path = _dxf_with(tmp_path, name, angle, scale, shift)
    _scene, hatches = _imported(path)
    ours = [s for h in hatches for s in h.pattern_segments()]
    ref = _autocad_lines(path)
    # ezdxf rounds the distance between lines to four places
    assert _unmatched(ref, ours, 1e-3) == 0
    assert len(ours) == len(ref)


def test_a_pattern_named_like_one_of_the_app_s_own_keeps_the_file_s(
        tmp_path):
    scene, (hatch,) = _imported(_dxf_with(tmp_path, "BRICK"))
    assert hatch.pattern == "BRICK (dxf)"
    assert "BRICK (dxf)" in scene.hatch_patterns


def test_a_pattern_that_draws_like_the_app_s_brick_is_brick(tmp_path):
    _scene, (hatch,) = _imported(_dxf_with(tmp_path, "AR-B816", scale=0.05))
    assert hatch.pattern == "brick"


def test_a_pattern_the_file_only_names_is_looked_up_by_name(tmp_path):
    """Some programs write a predefined pattern's name and not its lines;
    AutoCAD then draws it from acadiso.pat, and so does this, by way of the
    same patterns ezdxf carries."""
    import ezdxf
    path = _dxf_with(tmp_path, "ANSI31", 30.0, 2.0)
    _scene, (whole,) = _imported(path)
    doc = ezdxf.readfile(path)
    doc.modelspace().query("HATCH")[0].pattern.lines.clear()
    bare = tmp_path / "bare.dxf"
    doc.saveas(bare)

    _scene, (named,) = _imported(bare)
    assert named.pattern == "ANSI31"
    assert _unmatched(whole.pattern_segments(), named.pattern_segments(),
                      1e-9) == 0


@pytest.mark.parametrize("pattern", ["lines", "cross", "brick", "dots"])
def test_a_hatch_written_to_a_dxf_is_drawn_there_where_it_is_here(
        tmp_path, pattern):
    """The other way: what AutoCAD reads out of an export is what was
    drawn here, Lines and Cross centred on the region as they are."""
    from serpentine3d.core import geometry as g
    from serpentine3d.fileio.dxf import export_dxf
    pytest.importorskip("ezdxf")
    (face,) = g.planar_regions([g.make_polyline(
        [(0, 0, 0), (50, 0, 0), (50, 40, 0), (10, 50, 0)], closed=True)])
    hatch = HatchShape(face, pattern, angle=30.0, spacing=3.0)
    scene = Scene()
    scene.add(hatch)
    path = tmp_path / "out.dxf"
    export_dxf(scene, str(path))

    import ezdxf
    from ezdxf.render.hatching import hatch_entity
    entity = ezdxf.readfile(path).modelspace().query("HATCH")[0]
    drawn = list(hatch_entity(entity, jiggle_origin=False))
    ref = [(tuple(a), tuple(b)) for a, b in drawn if (a - b).magnitude > 1e-3]
    ours = hatch.line_segments()
    assert _unmatched(ref, ours, 1e-3) == 0
    assert _unmatched(ours, ref, 1e-3) == 0
    # a dot is a point there and a small circle round the same point here
    corners = [(0, 0), (50, 0), (50, 40), (10, 50)]

    def on_boundary(p):
        for (x0, y0), (x1, y1) in zip(corners, corners[1:] + corners[:1]):
            d = np.subtract((x1, y1), (x0, y0))
            t = np.clip(np.dot(np.subtract(p[:2], (x0, y0)), d)
                        / np.dot(d, d), 0, 1)
            if np.linalg.norm(np.add((x0, y0), t * d) - p[:2]) < 1e-6:
                return True
        return False

    points = [(tuple(a), tuple(a)) for a, b in drawn
              if (a - b).magnitude <= 1e-9 and not on_boundary(tuple(a))]
    centres = np.asarray([c for c, _r in hatch.dots()], float).reshape(-1, 3)

    def on_a_dot(p):
        return len(centres) and \
            np.linalg.norm(centres - np.asarray(p), axis=1).min() < 1e-6

    assert all(on_a_dot(a) for a, _b in points)
    assert ref or points
