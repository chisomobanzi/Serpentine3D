"""Live distance readout beside the cursor while a command picks points.

Asked for on the Rhino forum: "a small window, next to the cursor, which
indicates the distances when drawing a line."
"""

import numpy as np

from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


def _vp():
    from serpentine3d.ui.viewport import Viewport
    scene = Scene()
    vp = Viewport(scene, SelectionManager(scene))
    vp.resize(900, 700)
    vp.camera.target = np.zeros(3)
    vp.camera.distance = 40.0
    return vp, scene


def _seg(a, b):
    return np.asarray([[a, b]], np.float32)


def test_hidden_until_something_is_being_drawn():
    vp, _ = _vp()
    vp._update_draw_readout()
    assert vp._draw_readout.isHidden()


def test_reads_the_length_of_the_segment_being_drawn():
    vp, scene = _vp()
    vp.set_preview(_seg((0, 0, 0), (3, 4, 0)), [(0, 0, 0)])
    vp._update_draw_readout()
    assert not vp._draw_readout.isHidden()
    assert vp._draw_readout.text() == scene.format_length(5.0)


def test_reads_in_document_units():
    vp, scene = _vp()
    scene.units = "in"
    vp.set_preview(_seg((0, 0, 0), (3, 4, 0)), [(0, 0, 0)])
    vp._update_draw_readout()
    assert vp._draw_readout.text() == '5"'


def test_polyline_reads_the_open_segment_not_the_whole_chain():
    vp, scene = _vp()
    segs = np.asarray([[(0, 0, 0), (6, 0, 0)],
                       [(6, 0, 0), (6, 8, 0)]], np.float32)
    vp.set_preview(segs, [(0, 0, 0), (6, 0, 0)])
    vp._update_draw_readout()
    assert vp._draw_readout.text() == scene.format_length(8.0)


def test_label_sits_by_the_cursor_end_not_the_base():
    vp, _ = _vp()
    base, cursor = (0.0, 0.0, 0.0), (10.0, 0.0, 0.0)
    vp.set_preview(_seg(base, cursor), [base])
    vp._update_draw_readout()
    scr = vp.camera.project(np.asarray([base, cursor], float),
                            vp.width(), vp.height())
    pos = np.asarray([vp._draw_readout.x(), vp._draw_readout.y()], float)
    assert (np.linalg.norm(pos - scr[1][:2])
            < np.linalg.norm(pos - scr[0][:2]))


def test_clearing_the_preview_hides_it():
    vp, _ = _vp()
    vp.set_preview(_seg((0, 0, 0), (3, 4, 0)), [(0, 0, 0)])
    vp._update_draw_readout()
    assert not vp._draw_readout.isHidden()
    vp.set_preview(None)
    vp._update_draw_readout()
    assert vp._draw_readout.isHidden()


def test_stays_inside_the_viewport_when_the_cursor_is_at_the_edge():
    vp, _ = _vp()
    # a point far to the right projects off-widget; the label must not
    # follow it out of the window
    vp.set_preview(_seg((0, 0, 0), (400, 0, 0)), [(0, 0, 0)])
    vp._update_draw_readout()
    if not vp._draw_readout.isHidden():
        assert 0 <= vp._draw_readout.x() <= vp.width()
        assert 0 <= vp._draw_readout.y() <= vp.height()


def test_a_zero_length_segment_shows_nothing():
    """The instant after the base point is picked the cursor is still on
    it; a flickering '0' there is noise."""
    vp, _ = _vp()
    vp.set_preview(_seg((2, 2, 0), (2, 2, 0)), [(2, 2, 0)])
    vp._update_draw_readout()
    assert vp._draw_readout.isHidden()
