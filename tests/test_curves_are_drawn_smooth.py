"""Curves and the edges of surfaces are drawn smooth (#168).

A curve is exact NURBS here as in Rhino; only the picture of it is made of
straight pieces. Each piece used to turn up to 14 degrees from the next, so
a gentle 60 mm curve showed as nine visible kinks. Rhino's own display is
far finer. Surfaces were already finer than curves (about 10 degrees
between facets), so only curves and edges change.
"""
import numpy as np

from serpentine3d.core import geometry as g
from serpentine3d.core.tessellate import tessellate


def _joint_turns(mesh) -> np.ndarray:
    segs = mesh.edge_segments.reshape(-1, 2, 3)
    d = segs[:, 1] - segs[:, 0]
    d /= np.linalg.norm(d, axis=1)[:, None]
    # only joints where one segment runs on into the next
    joined = np.linalg.norm(segs[1:, 0] - segs[:-1, 1], axis=1) < 1e-9
    cos = np.clip((d[:-1] * d[1:]).sum(axis=1), -1.0, 1.0)
    return np.degrees(np.arccos(cos))[joined]


def test_a_gentle_curve_has_no_visible_kinks():
    """#168's curve: about 60 mm with one bend."""
    curve = g.make_interp_curve([(0, 0, 0), (8, 15, 0), (20, 30, 0),
                                 (38, 40, 0), (55, 44, 0)])
    turns = _joint_turns(tessellate(curve))
    assert turns.max() <= 1.5


def test_a_circle_is_drawn_round():
    turns = _joint_turns(tessellate(g.make_circle((0, 0, 0), 20.0)))
    assert turns.max() <= 1.5

