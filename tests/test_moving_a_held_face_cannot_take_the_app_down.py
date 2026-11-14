"""Issue #160: dragging a held face with the Gumball closed Serpentine3D.

The face move ends in the kernel's offset, which can fault natively on
shapes it cannot handle; a fault there takes the whole app with it, so
those shapes must be refused before the kernel sees them. Other shapes it
handled but returned wrong: in pieces, or a solid come back as a shell.
The crashing cases run in their own process, so a fault fails the test
instead of ending the run.
"""

import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from serpentine3d.core import geometry as g


def _run(tmp_path, source):
    env = dict(os.environ, SERP3D_CONFIG=str(tmp_path / "settings.json"),
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    return subprocess.run([sys.executable, "-c", source], cwd=tmp_path,
                          env=env, capture_output=True, text=True,
                          timeout=120)


_SHAPES = '''
import math, resource, sys
from serpentine3d.core import geometry as g
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def bottom(shape):
    for i, f in enumerate(g.faces_of(shape)):
        try:
            if g.face_normal(f)[2] < -0.9:
                return i
        except g.GeometryError:
            pass


def pointed_fan():
    """Six EdgeSrf triangles round an apex: each closes to a point there."""
    apex = (0.0, 0.0, 10.0)
    rim = [(20 * math.cos(math.radians(a)), 20 * math.sin(math.radians(a)),
            0.0) for a in range(0, 360, 60)]
    return g.join_surfaces([
        g.edge_surface([g.make_line(apex, rim[k]),
                        g.make_line(rim[k], rim[(k + 1) % 6]),
                        g.make_line(rim[(k + 1) % 6], apex)])
        for k in range(6)])


def holed_under_a_roof():
    """A block under a curved roof, with a hole up through the roof."""
    body = g.boolean_intersection(
        g.make_box((0, 0, 0), 40, 40, 9),
        g.make_cylinder((-1, 20, -52), 60, 42, axis=(1, 0, 0)))
    return g.boolean_difference(body, g.make_cylinder((20, 20, -1), 6, 20))
'''


def _flat_fan():
    """Six flat triangles round an apex."""
    apex = (0.0, 0.0, 10.0)
    rim = [(20 * math.cos(math.radians(a)), 20 * math.sin(math.radians(a)),
            0.0) for a in range(0, 360, 60)]
    faces = []
    for k in range(6):
        p, q = rim[k], rim[(k + 1) % 6]
        faces.append(g.planar_face(g.make_polyline([apex, p, q],
                                                   closed=True)))
    return g.join_surfaces(faces)


def _bottom(shape):
    for i, f in enumerate(g.faces_of(shape)):
        try:
            if g.face_normal(f)[2] < -0.9:
                return i
        except g.GeometryError:
            pass
    raise AssertionError("no bottom face")


def test_a_face_of_a_holed_solid_moves_and_it_stays_a_solid():
    """A boolean hands back its solid inside a compound; the offset took
    the wrapper for loose faces and gave back a shell. The reporter saw
    this as a solid that "became a shell"."""
    holed = g.boolean_difference(g.make_box((0, 0, 0), 20, 20, 8),
                                 g.make_cylinder((10, 10, -1), 3, 10))
    out = g.offset_face(holed, _bottom(holed), -0.5)
    assert g.shape_kind(out) == "solid"
    assert g.unwrap_compound(out).ShapeType() == g.occ.SOLID
    lo, hi = g.bbox(out)
    assert hi[2] - lo[2] == pytest.approx(7.5, abs=1e-6)
    assert g.volume(out) == pytest.approx(
        g.volume(holed) * 7.5 / 8, rel=1e-6)


def test_an_offset_that_breaks_a_shell_into_pieces_is_refused():
    """Pushed far enough, the kernel returns a fan as three loose shells
    and the old checks let it through: the reporter's model "grew from
    75 mm to about 707 mm"."""
    fan = _flat_fan()
    with pytest.raises(g.GeometryError):
        g.offset_face(fan, 0, 4.0)


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Avoid the OS fault dialog in CI")
def test_a_face_that_closes_to_a_point_is_refused_not_a_crash(tmp_path):
    """EdgeSrf makes a triangle as a surface with one side shrunk to a
    point, where it has no normal; offsetting it faults in the kernel."""
    result = _run(tmp_path, _SHAPES + '''
fan = pointed_fan()
try:
    g.offset_face(fan, 0, 4.0)
except g.GeometryError as e:
    print("refused:", e)
''')
    assert result.returncode == 0, result.stderr[-2000:]
    assert "refused:" in result.stdout


@pytest.mark.skipif(sys.platform == "win32",
                    reason="Avoid the OS fault dialog in CI")
@pytest.mark.parametrize("distance", [-0.5, 0.5])
def test_the_floor_of_a_solid_holed_through_a_curved_roof_moves(
        tmp_path, distance):
    """The reporter's second file: a flat floor whose hole runs up out
    through a curved roof. The kernel's offset faults on it; the walls all
    stand square to the floor, so moving it is a push or pull."""
    result = _run(tmp_path, _SHAPES + f'''
shape = holed_under_a_roof()
before = g.volume(shape)
idx = bottom(shape)
area = g.surface_area(g.faces_of(shape)[idx])
out = g.offset_face(shape, idx, {distance})
lo, hi = g.bbox(out)
print("kind", g.shape_kind(out), g.unwrap_compound(out).ShapeType().name)
print("zspan %.6f" % (hi[2] - lo[2]))
print("dvol %.6f" % ((g.volume(out) - before) / area))
''')
    assert result.returncode == 0, result.stderr[-2000:]
    assert "kind solid TopAbs_SOLID" in result.stdout
    span = float(result.stdout.split("zspan ")[1].split()[0])
    assert span == pytest.approx(8.0 + distance, abs=1e-6)
    grown = float(result.stdout.split("dvol ")[1].split()[0])
    assert grown == pytest.approx(distance, abs=1e-6)
