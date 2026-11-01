"""Join and Explode change little you can see, so what they made stays
selected and lights up white for a moment before settling back to gold."""

import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.ui import theme
from serpentine3d.ui import viewport as viewport_module


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("SERP3D_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    w = MainWindow()
    yield w
    w.processor.cancel()
    w._saved_revision = w.scene.revision
    w.close()


def _lit(window, obj_id):
    return [vp._flash_amount(obj_id) for vp in window.all_viewports()]


def test_joined_curves_light_up(window):
    a = window.scene.add(g.make_line((0, 0, 0), (5, 0, 0)))
    b = window.scene.add(g.make_line((5, 0, 0), (5, 5, 0)))
    window.selection.set([a.id, b.id])
    window.processor.run("join")
    QApplication.processEvents()
    joined, = window.scene.all()
    assert window.selection.ids == [joined.id]
    assert all(amount > 0.5 for amount in _lit(window, joined.id))


def test_exploded_pieces_light_up(window):
    poly = window.scene.add(g.make_polyline([(0, 0, 0), (5, 0, 0), (5, 5, 0)]))
    window.selection.set([poly.id])
    window.processor.run("explode")
    QApplication.processEvents()
    pieces = window.scene.all()
    assert len(pieces) == 2
    assert sorted(window.selection.ids) == sorted(p.id for p in pieces)
    for piece in pieces:
        assert all(amount > 0.5 for amount in _lit(window, piece.id))


def test_the_flash_is_white():
    assert theme.CHANGE_FLASH == (1.0, 1.0, 1.0)


def test_the_flash_holds_white_before_it_fades(window, monkeypatch):
    line = window.scene.add(g.make_line((0, 0, 0), (5, 0, 0)))
    vp = window.viewport
    vp.flash([line.id])
    held = viewport_module.time.monotonic() + theme.CHANGE_FLASH_HOLD * 0.9
    monkeypatch.setattr(viewport_module.time, "monotonic", lambda: held)
    assert vp._flash_amount(line.id) == 1.0


def test_the_flash_fades_back(window, monkeypatch):
    line = window.scene.add(g.make_line((0, 0, 0), (5, 0, 0)))
    vp = window.viewport
    vp.flash([line.id])
    later = viewport_module.time.monotonic() + theme.CHANGE_FLASH_SECONDS + 1e-3
    monkeypatch.setattr(viewport_module.time, "monotonic", lambda: later)
    assert vp._flash_amount(line.id) == 0.0
    vp._flash_tick()
    assert not vp._flashes, "a spent flash is let go of"


def test_nothing_lights_when_explode_has_nothing_to_do(window):
    line = window.scene.add(g.make_line((0, 0, 0), (5, 0, 0)))
    window.selection.set([line.id])
    window.processor.run("explode")
    assert _lit(window, line.id) == [0.0] * len(window.all_viewports())


def test_curves_explode_cannot_split_stay_selected(window):
    a = window.scene.add(g.make_line((0, 0, 0), (5, 0, 0)))
    b = window.scene.add(g.make_line((0, 3, 0), (5, 3, 0)))
    window.selection.set([a.id, b.id])
    window.processor.run("explode")
    assert not window.processor.busy
    assert sorted(window.selection.ids) == sorted([a.id, b.id])


def test_explode_keeps_the_pieces_and_what_stayed_whole_selected(window):
    poly = window.scene.add(g.make_polyline([(0, 0, 0), (5, 0, 0), (5, 5, 0)]))
    line = window.scene.add(g.make_line((0, 9, 0), (5, 9, 0)))
    window.selection.set([poly.id, line.id])
    window.processor.run("explode")
    ids = sorted(o.id for o in window.scene.all())
    assert len(ids) == 3 and line.id in ids
    assert sorted(window.selection.ids) == ids


def test_a_picked_result_shows_the_flash_and_settles_back_to_gold(
        window, monkeypatch):
    """A joined curve stays selected, and a selected curve is drawn in the
    selection colour: the flash has to reach that colour too."""
    import numpy as np
    window.set_view_layout("single")
    window.resize(900, 700)
    window.show()
    vp = window.viewport
    vp.grabFramebuffer()
    if not (vp.isValid() and getattr(vp, "_mesh_prog", 0)):
        pytest.skip("no GL 3.3 to draw with here (CI runs offscreen)")
    a = window.scene.add(g.make_line((0, 5, 0), (20, 5, 0)))
    b = window.scene.add(g.make_line((20, 5, 0), (20, 20, 0)))
    vp.camera.set_standard_view("top")
    vp.camera.target = (10, 10, 0)
    vp.camera.distance = 60

    def brightest():
        image = vp.grabFramebuffer()
        (x, y, _w), = vp.camera.project(np.asarray([(10, 5, 0)], float),
                                        vp.width(), vp.height())
        scale = image.width() / max(vp.width(), 1)
        return max((image.pixelColor(int(x * scale) + dx, int(y * scale) + dy)
                    for dx in range(-3, 4) for dy in range(-3, 4)),
                   key=lambda c: c.red() + c.green() + c.blue())

    window.selection.set([a.id, b.id])
    window.processor.run("join")
    lit = brightest()
    assert lit.blue() > 200, "the joined curve lights up white"
    later = viewport_module.time.monotonic() + theme.CHANGE_FLASH_SECONDS + 1e-3
    monkeypatch.setattr(viewport_module.time, "monotonic", lambda: later)
    settled = brightest()
    assert settled.blue() < 120 and settled.red() > 200, "then gold again"
