"""Pressing a space tab has to leave a picture of that space on screen.

`switch_space` told the main pane which space it was drawing, and that
asked for a repaint — and then rearranged the docks underneath it. A dock
put away and brought back loses the repaint it was waiting on, and a
QOpenGLWidget shown without one pending does not draw a frame: it blits the
last one its framebuffer happens to be holding. So the tab changed, the
title changed, the echo changed, and the pane still showed the sheet you
had just left, until a scroll or an orbit asked for a frame by accident.

It only bit when the two tabs held the same arrangement, which is why a
brand new layout always looked right: going from four panes to one moves
every pane, and a pane that moves is a pane that gets resized and redrawn.
Model to sheet and back, both single, moves nothing.

The repaint has to come after the arrangement settles, so nothing is left
to throw it away. That ordering is what these tests hold.
"""

import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core.layout import Layout
from serpentine3d.ui.viewport import Viewport


@pytest.fixture
def win(_qapp):
    w = MainWindow()
    yield w
    w.mark_saved()
    w.close()


def _watch(win, monkeypatch):
    """Log every repaint asked for, and every rearrangement, in order."""
    log = []

    real_update = Viewport.update

    def update(self, *a, **k):
        log.append(("update", self))
        return real_update(self, *a, **k)

    monkeypatch.setattr(Viewport, "update", update)

    def arranging(name, func):
        def wrapper(*a, **k):
            log.append(("arrange", name))
            return func(*a, **k)
        return wrapper

    area = win.viewport_area
    monkeypatch.setattr(area, "restoreState",
                        arranging("restoreState", area.restoreState))
    monkeypatch.setattr(win, "_show_only",
                        arranging("_show_only", win._show_only))
    monkeypatch.setattr(win, "set_view_layout",
                        arranging("set_view_layout", win.set_view_layout))
    return log


def _repainted_after_arranging(log):
    """The panes asked to draw once the docks had stopped moving."""
    moves = [i for i, (kind, _) in enumerate(log) if kind == "arrange"]
    assert moves, "switch_space did not arrange anything"
    return [vp for kind, vp in log[moves[-1] + 1:] if kind == "update"]


def _sheet(win):
    lay = Layout(name="Sheet 1")
    win.scene.layouts.append(lay)
    win._refresh_space_tabs()
    return lay


def test_going_back_to_model_redraws(win, monkeypatch):
    """The reported bug: the model tab kept showing the sheet."""
    lay = _sheet(win)
    win.switch_space(lay.id)
    log = _watch(win, monkeypatch)
    win.switch_space("model")
    assert win.viewport in _repainted_after_arranging(log)


def test_going_back_to_a_sheet_redraws(win, monkeypatch):
    """And the sheet tab kept showing the model."""
    lay = _sheet(win)
    win.switch_space(lay.id)
    win.switch_space("model")
    log = _watch(win, monkeypatch)
    win.switch_space(lay.id)
    assert win.viewport in _repainted_after_arranging(log)


def test_opening_a_sheet_the_first_time_redraws(win, monkeypatch):
    """The path that always worked, held so it keeps working."""
    lay = _sheet(win)
    log = _watch(win, monkeypatch)
    win.switch_space(lay.id)
    assert win.viewport in _repainted_after_arranging(log)


def test_every_pane_that_comes_back_redraws(win, monkeypatch):
    """Model space opens in four. Three of them were put away while the
    sheet was up, and a pane that has been away has nothing to show."""
    lay = _sheet(win)
    win.switch_space(lay.id)
    log = _watch(win, monkeypatch)
    win.switch_space("model")
    drawn = _repainted_after_arranging(log)
    for pane in win.all_viewports():
        assert pane in drawn


def test_a_pane_put_away_is_not_asked_to_draw(win, monkeypatch):
    """Repainting the world on every tab press would undo the point of
    putting panes away: a hidden pane costs a frame it cannot show."""
    lay = _sheet(win)
    log = _watch(win, monkeypatch)
    win.switch_space(lay.id)
    hidden = [vp for vp in win.aux_viewports if not win._pane_alive(vp)]
    assert hidden, "opening a sheet should have put the aux panes away"
    drawn = _repainted_after_arranging(log)
    for pane in hidden:
        assert pane not in drawn
