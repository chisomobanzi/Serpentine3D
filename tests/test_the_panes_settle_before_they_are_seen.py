"""Startup left the panes drawn at a geometry they no longer had.

Sometimes on launch the drawing came up torn: the perspective grid ran on
past the edge of its pane and underneath the tool strip, or a pane sat flat
and dark with its neighbour's picture in it. It looked like the toolbar
misbehaving, because the toolbar is what the stale picture was drawn over.

Two things put it there. The toolbar is added to the left edge, so it takes
its width out of the panes — and it was built *after* the saved layout was
restored, so the sizes coming out of the last session were laid into a
window one toolbar wider than the one the user would see, and the toolbar
itself was not in the state at all. Then the evening-out of the quad and the
panel column both run on a zero-timer, after the window is on screen, and
neither asked the panes to draw again at the size they had just been given.
A pane that is not asked keeps whatever its last frame was, at whatever
rectangle it now occupies.
"""

import pytest
from PySide6.QtWidgets import QToolBar


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    w = MainWindow()
    yield w
    w.close()


def _count_repaints(window):
    """Swap each pane's repaint for a tally. Offscreen a real one is a
    segfault waiting to happen, and the question is only who was asked."""
    seen = {}
    for vp in window.all_viewports():
        vp.update = (lambda v=vp: seen.__setitem__(v, seen.get(v, 0) + 1))
    return seen


# -- the toolbar is part of the window before the window is restored --

def test_the_toolbar_is_up_before_the_layout_is_restored(tmp_path,
                                                         monkeypatch):
    """The toolbar takes its width off the left of the panes. Restoring
    dock sizes into a window that has not got one yet lays them out that
    much too wide, and adding it afterwards moves every pane again."""
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    from serpentine3d.app import MainWindow
    seen = {}
    original = MainWindow._restore_window

    def spy(self):
        seen["bars"] = [b.objectName() for b in self.findChildren(QToolBar)]
        return original(self)

    monkeypatch.setattr(MainWindow, "_restore_window", spy)
    w = MainWindow()
    try:
        assert "toolPalette" in seen.get("bars", [])
    finally:
        w.close()


# -- and every pane draws itself again once it has stopped moving --

def test_evening_out_the_quad_asks_the_panes_to_draw_again(window):
    window.set_view_layout("quad")
    seen = _count_repaints(window)
    window._equalize_quad()
    assert set(seen) == set(window.all_viewports()), \
        "a pane resized and not repainted keeps its old picture"


def test_balancing_the_docks_asks_the_panes_to_draw_again(window):
    """The panel column takes its width off the right the same way, and it
    is set from a zero-timer too, after the first frame is on screen."""
    seen = _count_repaints(window)
    window._balance_docks()
    assert set(seen) == set(window.all_viewports())


def test_a_pane_that_has_gone_is_not_asked(window):
    """Repainting walks the live panes, so closing one must not raise."""
    window.set_view_layout("quad")
    window.aux_docks[0].hide()
    window.aux_viewports[0].hide()
    seen = _count_repaints(window)
    window._equalize_quad()
    assert window.aux_viewports[0] not in seen
    assert window.viewport in seen
