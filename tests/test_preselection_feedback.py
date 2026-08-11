"""A selection a command cannot use must say so, not sit silent.

Running booleanunion with 17 meshes selected used to park the command at
"Select 2 or more solids" with no word about why the selection was ignored
— and every click after that looked like a dead viewport. Any SelectReq
with a kinds filter had the same hole, so the feedback lives in the
processor, not in each command.
"""

import numpy as np
import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.commands.base import (
    CommandContext,
    CommandProcessor,
    IntReq,
    SelectReq,
)
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.mesh import MeshShape
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


@pytest.fixture
def env():
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    ctx = CommandContext(scene, selection, history)
    proc = CommandProcessor(ctx)
    echoes: list[str] = []
    ctx.add_echo_listener(echoes.append)
    return scene, selection, proc, echoes


def _mesh(scene, name):
    tri = MeshShape(np.array([[0.0, 0, 0], [1.0, 0, 0], [0, 1.0, 0]]),
                    np.array([[0, 1, 2]], np.uint32))
    return scene.add(tri, name=name)


def _curve(scene, name, y=0.0):
    return scene.add(g.make_line((0, y, 0), (10, y, 0)), name=name)


def test_wholly_ineligible_preselection_is_called_out(env):
    scene, selection, proc, echoes = env
    a, b = _mesh(scene, "MeshA"), _mesh(scene, "MeshB")
    selection.set([a.id, b.id])
    proc.run("booleanunion")
    said = " ".join(echoes)
    assert "2" in said and "solid" in said, \
        f"no word about the unusable selection, only: {echoes}"
    # the command still waits — the message explains, it does not cancel
    assert isinstance(proc.request, SelectReq)


def test_partly_ineligible_preselection_names_what_it_skipped(env):
    scene, selection, proc, echoes = env
    c, m = _curve(scene, "C"), _mesh(scene, "M")
    selection.set([c.id, m.id])
    proc.run("divide")            # kinds=("curve",), min_count=1
    said = " ".join(echoes)
    assert "1" in said and "curve" in said, \
        f"the skipped mesh went unmentioned: {echoes}"
    # the eligible curve was consumed and the command moved on
    assert isinstance(proc.request, IntReq)


def test_too_few_eligible_keeps_them_and_says_why(env):
    scene, selection, proc, echoes = env
    c, m = _curve(scene, "C"), _mesh(scene, "M")
    selection.set([c.id, m.id])
    proc.run("join")              # kinds=("curve",), min_count=2
    said = " ".join(echoes)
    assert "curve" in said, f"nothing said about the mesh: {echoes}"
    assert isinstance(proc.request, SelectReq)
    # the usable curve is carried into the pending selection, so adding
    # one more curve completes it — no need to re-click the first
    c2 = _curve(scene, "C2", y=5.0)
    proc.click_object(c2.id)
    proc.finish_selection()
    assert not proc.busy
    assert len(scene.all()) < 4   # join consumed the two curves


def test_max_count_truncation_is_announced(env):
    scene, selection, proc, echoes = env
    c1, c2 = _curve(scene, "C1"), _curve(scene, "C2", y=5.0)
    selection.set([c1.id, c2.id])
    proc.run("offset")            # kinds=("curve",), max_count=1
    said = " ".join(echoes)
    assert "first" in said.lower(), \
        f"silently dropped the second curve: {echoes}"


def test_box_selecting_only_ineligible_objects_says_so(env):
    scene, _selection, proc, echoes = env
    m = _mesh(scene, "M")
    proc.run("join")              # waits for curves
    assert isinstance(proc.request, SelectReq)
    echoes.clear()
    proc.box_objects([m.id])
    assert any("not accepted" in e or "cannot" in e or "needs" in e
               for e in echoes), \
        f"box select of a mesh said nothing: {echoes}"


def test_typing_all_with_no_eligible_objects_does_not_cancel(env):
    scene, _selection, proc, echoes = env
    _mesh(scene, "M")
    proc.run("join")
    echoes.clear()
    proc.provide_text("all")
    # used to fall through to finish_selection -> cancel; the command
    # should instead explain and keep waiting
    assert proc.busy and isinstance(proc.request, SelectReq)
    assert echoes, "no explanation for why 'all' selected nothing"
