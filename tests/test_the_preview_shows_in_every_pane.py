"""What you are drawing has to appear in the pane you are drawing in.

Draw a polyline in Top and the rubber band ran in Perspective instead: the
picked points showed up in every pane, the leg between them in only one.
Everything else in the command wiring loops over the panes — the point mode,
the pending points, the ghost being cleared — but the two calls that put the
band, the frame readout and the typed-in ghost on a pane named the primary
one on its own, so they always went to Perspective no matter where the
cursor was.

Nothing about a band is particular to a pane. It is a couple of world points
with a line between them, and each pane already knows how to look at those
from where it stands.
"""

import numpy as np
import pytest

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g


@pytest.fixture
def window():
    w = MainWindow()
    w.resize(1200, 800)
    w.set_view_layout("quad")
    yield w
    w.close()


def _drawing_a_line(w):
    """Part way through `line`: the first point is down, the second is not."""
    w.processor.run("line")
    w.processor.provide((0.0, 0.0, 0.0))
    return w.processor.request


def _panes(w):
    panes = w.all_viewports()
    assert len(panes) == 4, "quad, so there is something to get wrong"
    return panes


# -- the rubber band --

def test_the_band_runs_in_every_pane(window):
    _drawing_a_line(window)
    window._refresh_rubber((10.0, 5.0, 0.0))
    for vp in _panes(window):
        assert len(vp._preview_data), f"{vp._view_name}: no band"
        assert vp._draw_span is not None


def test_the_band_is_the_same_line_wherever_it_is_drawn(window):
    _drawing_a_line(window)
    window._refresh_rubber((10.0, 5.0, 0.0))
    first = _panes(window)[0]._preview_data
    for vp in _panes(window)[1:]:
        assert np.allclose(vp._preview_data, first)


def test_letting_go_of_the_point_clears_every_pane(window):
    _drawing_a_line(window)
    window._refresh_rubber((10.0, 5.0, 0.0))
    window.processor.cancel()
    for vp in _panes(window):
        assert not len(vp._preview_data), f"{vp._view_name}: band left behind"


# -- the frame readout, for the commands a band would only cut across --

def test_the_frame_readout_reaches_every_pane(window):
    window.processor.run("rectangle")
    window.processor.provide((0.0, 0.0, 0.0))
    window._refresh_rubber((10.0, 5.0, 0.0))
    for vp in _panes(window):
        assert vp._draw_frame is not None, f"{vp._view_name}: no readout"


# -- but the number itself belongs beside the cursor, which is in one pane --

def test_only_the_pane_being_drawn_in_puts_a_number_up(window):
    """The band is the same line seen four ways and belongs in all of them.
    The number is how long the leg under the cursor is, and it is written
    beside the cursor. Written in the other three panes as well it is the
    same figure three more times, none of them anywhere you are looking."""
    _drawing_a_line(window)
    window._refresh_rubber((10.0, 5.0, 0.0))
    showing = [vp for vp in _panes(window) if vp._readout_wanted]
    assert showing == [window._active_vp], [v._view_name for v in showing]


def test_the_number_follows_the_pane_you_move_to(window):
    _drawing_a_line(window)
    window._refresh_rubber((10.0, 5.0, 0.0))
    other = [vp for vp in _panes(window) if vp is not window._active_vp][0]
    window._set_active_viewport(other)
    window._refresh_rubber((12.0, 6.0, 0.0))
    assert other._readout_wanted
    assert [vp for vp in _panes(window) if vp._readout_wanted] == [other]


def test_the_band_is_still_in_the_panes_without_the_number(window):
    _drawing_a_line(window)
    window._refresh_rubber((10.0, 5.0, 0.0))
    quiet = [vp for vp in _panes(window) if not vp._readout_wanted]
    assert len(quiet) == 3
    assert all(len(vp._preview_data) for vp in quiet)


# -- and the ghost of what a typed number would make --

def test_a_typed_number_ghosts_in_every_pane(window):
    """Type the length rather than dragging it and the shape it would make
    is drawn for you. In one pane only, it was drawn for whoever happened to
    be looking at Perspective."""
    window.processor.run("circle")
    window.processor.provide((0.0, 0.0, 0.0))
    window._live_preview("40")
    ghosted = [vp for vp in _panes(window) if vp._ghost is not None]
    assert len(ghosted) == 4, [vp._view_name for vp in ghosted]


def test_clearing_the_typed_number_clears_every_pane(window):
    window.processor.run("circle")
    window.processor.provide((0.0, 0.0, 0.0))
    window._live_preview("40")
    window._live_preview("")
    assert all(vp._ghost is None for vp in _panes(window))


def test_a_ghost_still_lands_when_there_is_only_one_pane():
    w = MainWindow()
    w.set_view_layout("single")
    w.processor.run("circle")
    w.processor.provide((0.0, 0.0, 0.0))
    w._live_preview("40")
    assert w.viewport._ghost is not None
    w.close()


# -- the geometry the ghost stands for, so a pane has something to show --

def test_the_ghost_is_the_shape_the_number_would_make():
    w = MainWindow()
    w.processor.run("circle")
    w.processor.provide((0.0, 0.0, 0.0))
    shape = w.processor.preview_shape("40")
    assert shape is not None
    (mn, mx) = g.bbox(shape)
    assert np.allclose([mx[0] - mn[0], mx[1] - mn[1]], [80.0, 80.0], atol=1e-3)
    w.close()
