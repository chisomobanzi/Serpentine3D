"""A temporary result containing free points must deliver visible geometry.

The GL boundary is recorded without creating a platform OpenGL context. The
viewport still tessellates the real shape, places it, and runs its pending
draw path; the recorded vertices are the ones actually submitted to draw.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.layout import DetailView, Layout, detail_project
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui import viewport as vp_mod


class _DrawStream:
    """The buffer upload and draw submissions at the graphics boundary."""

    def __init__(self):
        self.vertices = np.empty((0, 3), np.float32)
        self.draws = []
        self._constants = {}

    def __getattr__(self, name):
        if name.startswith("GL_"):
            return self._constants.setdefault(name, 0x2000 + len(self._constants))
        return lambda *args, **kwargs: 0

    def glDrawArrays(self, mode, first, count):
        assert count > 0
        assert first + count <= len(self.vertices), "draw exceeds the uploaded buffer"
        self.draws.append((mode, self.vertices[first:first + count].copy()))


class _RecordingBatch:
    """A dynamic buffer without GPU handles; no drawing logic lives here."""

    vao = 1

    def __init__(self, stream):
        self.stream = stream
        self.count = 0

    def update(self, vertices):
        self.stream.vertices = np.asarray(vertices).copy()
        self.count = len(vertices)


@pytest.fixture
def pending_draw(monkeypatch):
    stream = _DrawStream()
    monkeypatch.setattr(vp_mod, "GL", stream)
    scene = Scene()
    vp = vp_mod.Viewport(scene, SelectionManager(scene))
    vp.resize(800, 600)
    # The same context-free graphics seam as test_viewport_perf. All shape
    # preparation and marker drawing remain the real viewport methods.
    vp._line_prog = 11
    vp._max_line_width = 1.0
    vp._preview = _RecordingBatch(stream)
    yield vp, stream
    vp.close()
    vp.deleteLater()


def _draw(vp, stream, shape):
    stream.draws.clear()
    vp.set_ghost(shape)
    if shape is not None:
        assert vp._ghost is not None, "the test shape must tessellate successfully"
        free_points = g.free_points(shape)
        if free_points:
            assert vp._ghost.points == pytest.approx(np.asarray(free_points))
    vp._draw_pending(np.eye(4, dtype=np.float32))
    return [(mode, vertices.copy()) for mode, vertices in stream.draws]


def _assert_marker_at(draws, point):
    assert draws, "the point ghost was tessellated but never submitted for drawing"
    vertices = np.concatenate([vertices for _mode, vertices in draws])
    # A point may be drawn as a dot, cross, or another centered marker. Its
    # center, rather than the chosen marker style, is the observable contract.
    assert vertices.mean(axis=0) == pytest.approx(point, abs=1e-4)


@pytest.mark.parametrize("anchor", [None, (500_000.0, -200_000.0, 1_000.0)],
                         ids=["near-origin", "survey-coordinates"])
def test_a_point_only_ghost_draws_at_each_candidate(pending_draw, anchor):
    vp, stream = pending_draw
    frame = np.zeros(3) if anchor is None else np.asarray(anchor)
    vp._frame_anchor = None if anchor is None else frame
    for offset in ((12.0, 16.0, 8.0), (24.0, -8.0, 4.0)):
        candidate = frame + offset
        draws = _draw(vp, stream, g.make_point(tuple(candidate)))
        _assert_marker_at(draws, offset)
    assert vp.scene.all() == [], "a ghost must remain temporary"


def test_a_mixed_ghost_preserves_lines_and_faces_and_draws_its_free_point(pending_draw):
    vp, stream = pending_draw
    curve = g.make_line((1.0, 2.0, 3.0), (11.0, 7.0, 5.0))
    solid = g.make_box((20.0, 25.0, 1.0), 10.0, 8.0, 6.0)
    ordinary = g.make_compound([curve, solid])
    baseline = _draw(vp, stream, ordinary)
    assert len(baseline) == 2, "the fixture must deliver both faces and linework"
    point = (60.0, 75.0, 30.0)
    mixed = _draw(vp, stream, g.make_compound([ordinary, g.make_point(point)]))

    # Remove the unchanged draw packets for the curve and surface. What is
    # left must visibly represent the free point, rather than more corners.
    remaining = list(mixed)
    for mode, vertices in baseline:
        matches = [i for i, (other_mode, other_vertices) in enumerate(remaining)
                   if other_mode == mode and np.array_equal(other_vertices, vertices)]
        assert matches, "adding a point changed existing curve or surface drawing"
        remaining.pop(matches[0])
    _assert_marker_at(remaining, point)


@pytest.mark.parametrize("shape", [
    lambda: g.make_line((1.0, 2.0, 3.0), (11.0, 7.0, 5.0)),
    lambda: g.make_box((20.0, 25.0, 1.0), 10.0, 8.0, 6.0),
], ids=["connected-edge-vertices", "connected-face-vertices"])
def test_connected_vertices_do_not_become_extra_point_markers(pending_draw, shape):
    vp, stream = pending_draw
    draws = _draw(vp, stream, shape())
    mesh = vp._ghost
    expected = []
    if len(mesh.triangles):
        expected.append((stream.GL_TRIANGLES, mesh.vertices[mesh.triangles.ravel()]))
    if len(mesh.edge_segments):
        expected.append((stream.GL_LINES, mesh.edge_segments.reshape(-1, 3)))
    assert len(draws) == len(expected)
    for (mode, vertices), (expected_mode, expected_vertices) in zip(draws, expected):
        assert mode == expected_mode
        assert vertices == pytest.approx(expected_vertices)


def test_a_model_point_ghost_drawn_through_a_detail_lands_on_the_paper(pending_draw):
    vp, stream = pending_draw
    detail = DetailView(x=20.0, y=30.0, w=160.0, h=120.0,
                        scale_denom=2.0, target=[400.0, 250.0, 0.0])
    layout = Layout(name="Point preview sheet")
    layout.details.append(detail)
    vp.scene.layouts.append(layout)
    vp.space = layout.id
    vp.point_space = "any"
    vp.layout_view.entered_detail = detail.id
    candidate = (440.0, 270.0, 0.0)
    x, y = detail_project(detail, candidate)

    _assert_marker_at(_draw(vp, stream, g.make_point(candidate)), (x, y, 0.0))


def test_clearing_a_point_ghost_removes_its_drawn_marker(pending_draw):
    vp, stream = pending_draw
    _assert_marker_at(_draw(vp, stream, g.make_point((12.0, 16.0, 8.0))),
                      (12.0, 16.0, 8.0))
    assert _draw(vp, stream, None) == []
