"""F1 turns the pane to Top rather than cutting to it.

Same reason as the Alt swipe, and the same flight underneath: a cut from
Front to Back says nothing about which way you went, and on a symmetric
model the two look identical. The eye follows a turn; it cannot follow a
cut.

Scripts are the other half of it. The RPC bridge, the MCP server and the
E2E scripts read the camera the moment they set it, so `set_view` stays
instant, and anything that reads the camera lands a turn already going
rather than reporting a pose halfway to somewhere.
"""

import pytest

from serpentine3d.api import SerpApi
from serpentine3d.ui.camera import STANDARD_VIEWS


@pytest.fixture
def win(monkeypatch, tmp_path):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "s.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    yield w
    w.mark_saved()
    w.close()


def test_the_top_command_turns_the_pane(win):
    """Which is what F1 and the View menu both run."""
    win.processor.run("top")
    vp = win.viewport
    assert vp.flying
    vp.land_flight()
    assert (vp.camera.azimuth, vp.camera.elevation) == STANDARD_VIEWS["top"]
    assert vp._view_name == "top"


def test_the_pane_becomes_that_view_when_it_arrives(win):
    """The label, the construction plane and the projection all together."""
    win.processor.run("front")
    vp = win.viewport
    seen = []
    vp.viewChanged.connect(seen.append)
    assert seen == []
    vp.land_flight()
    assert seen == ["front"]
    assert vp.camera.projection == "parallel"


def test_it_stops_foreshortening_as_it_starts_turning(win):
    """A perspective pane asked for Top has two things to change, and the
    projection is the one you cannot ease. It goes at the start, where the
    ease is quickest, rather than as everything settles."""
    vp = win.viewport
    assert vp.camera.projection == "perspective"
    win.processor.run("top")
    assert vp.flying
    assert vp.camera.projection == "parallel"


def test_the_rpc_sets_a_view_at_once(win):
    """A script that sets a view and reads it back must not race a turn."""
    SerpApi(win).set_viewport(view="top")
    vp = win.viewport
    assert not vp.flying
    assert (vp.camera.azimuth, vp.camera.elevation) == STANDARD_VIEWS["top"]


def test_reading_the_camera_lands_a_turn_already_going(win):
    """`command top` over RPC is the interactive path underneath."""
    win.processor.run("top")
    assert win.viewport.flying
    info = SerpApi(win).viewport_info()
    assert not win.viewport.flying
    assert info["camera"]["azimuth"] == STANDARD_VIEWS["top"][0]
    assert info["camera"]["elevation"] == STANDARD_VIEWS["top"][1]


def test_the_panes_you_start_with_are_not_mid_turn(win):
    """Building a pane sets its view; nothing was asked for, so nothing
    turns."""
    assert not any(vp.flying for vp in win.all_viewports())
