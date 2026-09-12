"""Paper transform gestures obey the model viewport's point-input rules."""
import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from tests.test_a_picture_can_be_dropped_onto_paper import paper_window
from serpentine3d.core.picture import PictureShape

@pytest.mark.parametrize('ortho,shift,expected', [
    (False, False, (85., 67., 0.)), (False, True, (85., 60., 0.)),
    (True, False, (85., 60., 0.)), (True, True, (85., 67., 0.)),
])
@pytest.mark.parametrize('command', ['move', 'rotate', 'line'])
def test_paper_point_commands_share_shift_and_ortho(paper_window, monkeypatch,
                                                   ortho, shift, expected, command):
    w, lay = paper_window
    obj = lay.add(PictureShape(dict(origin=[40.,60.,0.],u=[60.,0.,0.],
                                   v=[0.,40.,0.],image_data=b'image')))
    vp = w.viewport; lv = vp.layout_view
    lv.selected = [('object', obj)]
    vp.snaps.enabled = False; vp.ortho = ortho; vp.grid_snap = False
    monkeypatch.setattr(QApplication, 'queryKeyboardModifiers', staticmethod(
        lambda: Qt.KeyboardModifier.ShiftModifier if shift else Qt.KeyboardModifier.NoModifier))
    w.processor.run(command)
    w.processor.provide((40.,60.,0.))
    assert vp.snap_base == (40.,60.,0.)
    assert vp.world_point_at(*lv.paper_to_screen(85.,67.)) == pytest.approx(expected)


def test_paper_grid_uses_step_and_explicit_direction(paper_window):
    w, _ = paper_window; vp=w.viewport; lv=vp.layout_view
    vp.snaps.enabled=False; vp.ortho=False
    vp.grid_snap=True; vp.grid_snap_step=5.
    assert vp.world_point_at(*lv.paper_to_screen(12.,18.)) == pytest.approx((10.,20.,0.))
    vp.point_axis=((10.,10.,0.),(1.,0.,0.))
    assert vp.world_point_at(*lv.paper_to_screen(22.,38.)) == pytest.approx((20.,10.,0.))


def test_typed_paper_gumball_value_survives_mouse_motion_and_zero_is_noop(paper_window):
    w, lay=paper_window; lv=w.viewport.layout_view
    obj=lay.add(PictureShape(dict(origin=[40.,60.,0.],u=[60.,0.,0.],v=[0.,40.,0.])))
    lv.selected=[('object',obj)]; gb=lv.gumball
    start=lv.paper_to_screen(70.,80.)
    before=obj.shape.vertices.copy(); undo=len(w.history._undo)
    gb.begin_drag(('move',0),*start)
    gb.type_char('0')
    gb.drag_to(*lv.paper_to_screen(170.,180.))
    np.testing.assert_allclose(obj.shape.vertices,before)
    assert gb.commit_typed()
    assert len(w.history._undo)==undo
    gb.begin_drag(('rot',2),*start)
    for c in '30': gb.type_char(c)
    rotated=obj.shape.vertices.copy()
    gb.drag_to(*lv.paper_to_screen(170.,180.))
    np.testing.assert_allclose(obj.shape.vertices,rotated)
    gb.cancel_drag()
    np.testing.assert_allclose(obj.shape.vertices,before)
