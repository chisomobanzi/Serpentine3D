"""Editable model text offers useful semantic object snaps."""

from collections import Counter

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.snaps import SnapIndex, _static_snap_points
from serpentine3d.core.text import TextShape
from serpentine3d.ui.camera import Camera


def _mapped(matrix, point):
    return tuple((np.asarray(matrix, float) @ np.r_[point, 1.0])[:3])


def _positions(candidates, kind):
    return sorted(tuple(float(c) for c in point)
                  for point, candidate_kind in candidates
                  if candidate_kind == kind)


def test_editable_text_has_semantic_snaps_on_its_transformed_visible_bounds():
    local = TextShape("SNAP", 8.0)
    lo, hi = g.bbox(local)
    x0, y0 = lo[:2]
    x1, y1 = hi[:2]

    # Place the text on a vertical 3D plane, then transform it again as an
    # ordinary model object. Its semantic points must follow both operations.
    placement = np.array([
        [1.0, 0.0, 0.0, 10.0],
        [0.0, 0.0, -1.0, 20.0],
        [0.0, 1.0, 0.0, 30.0],
        [0.0, 0.0, 0.0, 1.0],
    ])
    later = np.array([
        [0.0, -1.0, 0.0, 3.0],
        [1.0, 0.0, 0.0, 4.0],
        [0.0, 0.0, 1.0, 5.0],
        [0.0, 0.0, 0.0, 1.0],
    ])
    shape = g.apply_matrix(g.apply_matrix(local, placement), later)
    frame = later @ placement

    corners = [(x0, y0, 0.0), (x1, y0, 0.0),
               (x1, y1, 0.0), (x0, y1, 0.0)]
    midpoints = [tuple((np.asarray(a) + np.asarray(b)) / 2.0)
                 for a, b in zip(corners, corners[1:] + corners[:1])]
    center = ((x0 + x1) / 2.0, (y0 + y1) / 2.0, 0.0)

    candidates = _static_snap_points(shape)
    assert Counter(kind for _point, kind in candidates) == {
        "point": 1, "end": 4, "mid": 4, "center": 1,
    }, "editable text should expose ten semantic snaps, not glyph vertices"
    np.testing.assert_allclose(
        _positions(candidates, "point"), [_mapped(frame, (0.0, 0.0, 0.0))],
        atol=1e-5,
    )
    np.testing.assert_allclose(
        _positions(candidates, "end"),
        sorted(_mapped(frame, point) for point in corners), atol=1e-5,
    )
    np.testing.assert_allclose(
        _positions(candidates, "mid"),
        sorted(_mapped(frame, point) for point in midpoints), atol=1e-5,
    )
    np.testing.assert_allclose(
        _positions(candidates, "center"), [_mapped(frame, center)], atol=1e-5,
    )


def test_move_can_snap_the_text_insertion_point_to_an_ordinary_curve_end(env):
    scene, _selection, _history, _ctx, processor = env
    label = scene.add(TextShape("MOVE", 8.0))
    target = (35.0, -5.0, 0.0)
    scene.add(g.make_line(target, (35.0, 5.0, 0.0)))

    camera = Camera()
    camera.set_standard_view("top")
    camera.target[:] = (17.5, 0.0, 0.0)
    camera.distance = 80.0
    index = SnapIndex(scene)

    def snap_at(point):
        screen = camera.project(np.asarray([point], float), 1000, 700)[0]
        return index.find(camera, screen[0], screen[1], 1000, 700)

    base_snap = snap_at(label.shape.origin)
    assert base_snap is not None and base_snap[1] == "point"
    assert base_snap[0] == pytest.approx(label.shape.origin, abs=1e-7)
    target_snap = snap_at(target)
    assert target_snap is not None and target_snap[1] == "end"
    assert target_snap[0] == pytest.approx(target, abs=1e-7)

    processor.run("move")
    processor.click_object(label.id)
    processor.finish_selection()
    processor.provide(base_snap[0])
    processor.provide(target_snap[0])

    moved = scene.get(label.id).shape
    assert isinstance(moved, TextShape)
    assert moved.origin == pytest.approx(target, abs=1e-7)


def test_converted_text_curves_keep_their_ordinary_contour_snaps():
    curves = TextShape("SNAP", 8.0).to_curves()

    assert curves and all(not isinstance(curve, TextShape) for curve in curves)
    candidates = [candidate for curve in curves
                  for candidate in _static_snap_points(curve)]
    kinds = Counter(kind for _point, kind in candidates)
    assert kinds["end"] > 4
    assert kinds["mid"] > 4
    assert kinds["point"] == 0
