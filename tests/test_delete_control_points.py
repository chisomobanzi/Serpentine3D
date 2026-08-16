"""Delete removes held control points, not just whole objects.

Points on, click a corner, press Delete: the corner goes and the curve
closes over the gap. Before this, Delete with a control point held did
nothing at all.
"""

import pytest

from serpentine3d.core import geometry as g

SQUARE = [(0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
          (10.0, 10.0, 0.0), (0.0, 10.0, 0.0)]


# ----------------------------------------------------------- geometry

def test_deleting_a_polyline_corner_joins_its_neighbours():
    shape = g.make_polyline(SQUARE)
    out = g.delete_control_points(shape, [1])
    pts = g.get_control_points(out)
    assert len(pts) == 3
    assert (10.0, 0.0, 0.0) not in pts
    assert not g.is_closed_curve(out)


def test_a_closed_polyline_stays_closed():
    shape = g.make_polyline(SQUARE, closed=True)
    out = g.delete_control_points(shape, [2])
    assert g.is_closed_curve(out)
    assert len(g.get_control_points(out)) == 3


def test_a_nurbs_curve_keeps_its_degree():
    poles = [(float(i * 10), float((i % 2) * 5), 0.0) for i in range(6)]
    shape = g.make_control_curve(poles, degree=3)
    out = g.delete_control_points(shape, [2])
    pts = g.get_control_points(out)
    assert len(pts) == 5
    # ends stay anchored (clamped curve)
    assert pts[0] == pytest.approx(poles[0])
    assert pts[-1] == pytest.approx(poles[-1])


def test_deleting_several_at_once():
    shape = g.make_polyline([(float(i), 0.0, 0.0) for i in range(6)])
    out = g.delete_control_points(shape, [1, 3])
    assert len(g.get_control_points(out)) == 4


def test_a_closed_curve_opens_rather_than_refusing():
    """Two points cannot bound an area, so the loop straightens out."""
    shape = g.make_polyline(SQUARE, closed=True)
    out = g.delete_control_points(shape, [1, 2])
    assert not g.is_closed_curve(out)
    assert g.get_control_points(out) == [SQUARE[0], SQUARE[3]]


def test_the_last_pair_collapses_to_a_point_object():
    shape = g.make_polyline([(0.0, 0.0, 0.0), (10.0, 0.0, 0.0),
                             (20.0, 0.0, 0.0)])
    out = g.delete_control_points(shape, [0, 1])
    assert g.shape_kind(out) == "point"
    assert g.point_coords(out) == pytest.approx((20.0, 0.0, 0.0))


def test_a_nurbs_curve_collapses_too():
    poles = [(float(i * 10), 0.0, 0.0) for i in range(4)]
    shape = g.make_control_curve(poles, degree=3)
    out = g.delete_control_points(shape, [0, 1, 2])
    assert g.shape_kind(out) == "point"
    assert g.point_coords(out) == pytest.approx(poles[3])


def test_deleting_every_point_leaves_nothing():
    shape = g.make_polyline(SQUARE)
    assert g.delete_control_points(shape, [0, 1, 2, 3]) is None


# -------------------------------------------------- the delete command

@pytest.fixture
def env():
    import serpentine3d.commands  # registers all commands  # noqa: F401
    from serpentine3d.commands.base import CommandContext, CommandProcessor
    from serpentine3d.core.history import History
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager
    scene = Scene()
    selection = SelectionManager(scene)
    ctx = CommandContext(scene, selection, History(scene))
    proc = CommandProcessor(ctx)
    echoes: list[str] = []
    ctx.add_echo_listener(echoes.append)
    return scene, selection, proc, echoes


def test_typed_delete_takes_preselected_points(env):
    scene, selection, proc, echoes = env
    obj = scene.add(g.make_polyline(SQUARE))
    selection.toggle_subobject(obj.id, "cv", 1)
    proc.run("delete")
    assert not proc.busy
    assert len(g.get_control_points(scene.get(obj.id).shape)) == 3
    assert any("control point" in e for e in echoes)


def test_typed_delete_then_clicked_point(env):
    """delete, click a corner, Enter — the click lands mid-request."""
    scene, selection, proc, _echoes = env
    obj = scene.add(g.make_polyline(SQUARE))
    proc.run("delete")
    assert proc.busy
    selection.toggle_subobject(obj.id, "cv", 2)   # what a CV click does
    proc.finish_selection()
    assert not proc.busy
    assert len(g.get_control_points(scene.get(obj.id).shape)) == 3


def test_typed_delete_with_nothing_says_so(env):
    scene, _selection, proc, echoes = env
    scene.add(g.make_polyline(SQUARE))
    proc.run("delete")
    proc.finish_selection()
    assert not proc.busy
    assert any("othing" in e for e in echoes), echoes


def test_delete_says_when_the_curve_had_to_open(env):
    scene, selection, proc, echoes = env
    obj = scene.add(g.make_polyline(SQUARE, closed=True))
    for i in (1, 2):
        selection.toggle_subobject(obj.id, "cv", i)
    proc.run("delete")
    assert not g.is_closed_curve(scene.get(obj.id).shape)
    assert any("open" in e for e in echoes), echoes


def test_delete_down_to_one_point_leaves_a_point_object(env):
    scene, selection, proc, echoes = env
    obj = scene.add(g.make_polyline(SQUARE))
    for i in (0, 1, 2):
        selection.toggle_subobject(obj.id, "cv", i)
    proc.run("delete")
    assert scene.get(obj.id).kind == "point"
    assert any("point now" in e for e in echoes), echoes


def test_delete_of_the_last_point_removes_the_object(env):
    scene, selection, proc, _echoes = env
    obj = scene.add(g.make_polyline(SQUARE))
    for i in range(4):
        selection.toggle_subobject(obj.id, "cv", i)
    proc.run("delete")
    assert scene.get(obj.id) is None


def test_clicked_point_delete_replays_identically(tmp_path):
    """The mid-request point pick must ride in the journal, or a replayed
    session keeps the corner the live one deleted."""
    from serpentine3d.commands.base import CommandContext, CommandProcessor
    from serpentine3d.core.history import History
    from serpentine3d.core.journal import SessionJournal
    from serpentine3d.core.replay import Replayer, load_events
    from serpentine3d.core.scene import Scene
    from serpentine3d.core.selection import SelectionManager

    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    ctx = CommandContext(scene, selection, history)
    proc = CommandProcessor(ctx)
    journal = SessionJournal(str(tmp_path / "session.jsonl"))
    journal.attach(proc, scene, history)

    proc.run("polyline")
    for t in ("0,0", "10,0", "10,10", "0,10"):
        proc.provide_text(t)
    proc.provide_text("")
    obj = scene.all()[0]
    proc.run("delete")
    selection.toggle_subobject(obj.id, "cv", 1)
    proc.finish_selection()
    assert len(g.get_control_points(scene.get(obj.id).shape)) == 3

    journal.close()
    r = Replayer(load_events(journal.path))
    r.run()
    replayed = r.scene.all()[0]
    assert len(g.get_control_points(replayed.shape)) == 3


# --------------------------------------------- Rhino's name for the same

def test_removecontrolpoint_deletes_the_held_points(env):
    scene, selection, proc, _echoes = env
    obj = scene.add(g.make_polyline(SQUARE))
    selection.toggle_subobject(obj.id, "cv", 1)
    proc.run("removecontrolpoint")
    assert not proc.busy
    assert len(g.get_control_points(scene.get(obj.id).shape)) == 3


def test_removecontrolpoint_with_nothing_held_says_where_to_start(env):
    scene, _selection, proc, echoes = env
    obj = scene.add(g.make_polyline(SQUARE))
    proc.run("removecontrolpoint")
    assert len(g.get_control_points(scene.get(obj.id).shape)) == 4
    assert any("pointson" in m.lower() or "f10" in m.lower() for m in echoes)


# ------------------------------------------------------ the Delete key

def test_delete_takes_the_held_corner_and_undo_puts_it_back(monkeypatch,
                                                            tmp_path):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "s.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    obj = w.scene.add(g.make_polyline(SQUARE))
    w.selection.toggle_subobject(obj.id, "cv", 1)
    w._delete_selected()
    assert len(g.get_control_points(w.scene.get(obj.id).shape)) == 3
    assert w.selection.subobjects == []
    w.history.undo()
    assert len(g.get_control_points(w.scene.get(obj.id).shape)) == 4
    w.mark_saved()
    w.close()
