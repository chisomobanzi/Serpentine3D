"""The gumball on the paper itself.

Inside a detail what is picked is a model object, and it has had the model
window's gumball for a while. On bare paper what is picked is a detail frame,
a note or a dimension, and the only way to move one was to drag its ink, which
moves it in both directions at once. Lining a detail up with the one above it
meant dragging and squinting.

So the sheet gets a gumball of its own: two arrows and the one plane pad that
a sheet has, in paper millimetres, anchored on the middle of whatever is
picked. Nothing here turns or scales because nothing on a sheet has an angle
or a size to change — a detail frame is a rectangle with corner grips for
that — so the handles that would lie about what they do are not drawn.
"""

from __future__ import annotations

import inspect

import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.app import MainWindow
from serpentine3d.core.layout import DetailView, Layout, TextNote
from serpentine3d.ui.camera import STANDARD_VIEWS
from serpentine3d.ui.gumball import CONE1, PAD0, PAD1, SHAFT0


@pytest.fixture
def sheet(tmp_path, monkeypatch):
    """A sheet with one detail and one note, the detail picked."""
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    w = MainWindow()
    w.resize(1200, 800)
    lay = Layout(name="Sheet1")
    az, el = STANDARD_VIEWS["front"]
    det = DetailView(x=160.0, y=100.0, w=120.0, h=90.0, azimuth=az,
                     elevation=el, target=[0.0, 0.0, 0.0], scale_denom=2.0)
    note = TextNote(x=40.0, y=40.0, text="NOTE", height=5.0)
    lay.details.append(det)
    lay.notes.append(note)
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    # Nothing lays out a window that was never shown, so say what size the
    # pane is before anything is measured in its pixels.
    w.viewport.resize(640, 480)
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    lv.selected = [("detail", det)]
    yield w, lv, det, note
    w.mark_saved()
    w.close()


def _handle(lv, kind: str, axis: int) -> tuple[float, float]:
    """A pixel on the given handle, as it is drawn."""
    gb = lv.gumball
    ax, ay = gb.anchor()
    s = gb._size_mm()
    if kind == "move":
        reach = (SHAFT0 + CONE1) / 2 * s
        px = ax + (reach if axis == 0 else 0.0)
        py = ay + (reach if axis == 1 else 0.0)
    else:                                   # the middle of the pad
        mid = (PAD0 + PAD1) / 2 * s
        px, py = ax + mid, ay + mid
    return lv.paper_to_screen(px, py)


# ------------------------------------------------------------- when it shows

def test_a_picked_sheet_item_gets_a_gumball(sheet):
    _w, lv, _det, _note = sheet
    assert lv.gumball.active()


def test_nothing_picked_means_no_gumball(sheet):
    _w, lv, _det, _note = sheet
    lv.selected = []
    assert not lv.gumball.active()


def test_inside_a_detail_the_paper_gumball_stands_down(sheet):
    """Two gumballs on one sheet would be two answers to one press. In a
    detail you are holding the model, so the model's one has it."""
    _w, lv, det, _note = sheet
    lv.entered_detail = det.id
    assert not lv.gumball.active()


def test_a_command_asking_for_a_point_hides_it(sheet):
    w, lv, _det, _note = sheet
    w.viewport.point_mode = True
    assert not lv.gumball.active()


def test_a_locked_detail_offers_nothing_to_hold(sheet):
    """A lock is the whole reason a detail is not dragged by its ink. It
    should not gain a set of arrows that would move it anyway."""
    _w, lv, det, _note = sheet
    det.locked = True
    assert not lv.gumball.active()


def test_the_viewport_hands_a_press_to_whichever_is_live(sheet):
    """One accessor decides, so a press, a hover and a keystroke can never
    disagree about which gumball they are talking to."""
    w, lv, det, _note = sheet
    vp = w.viewport
    assert vp._live_gumball() is lv.gumball
    lv.entered_detail = det.id
    assert vp._live_gumball() is vp.gumball
    w.switch_space("model")
    assert w.viewport._live_gumball() is w.viewport.gumball


# --------------------------------------------------------------- where it is

def test_it_stands_on_the_middle_of_what_is_picked(sheet):
    _w, lv, det, _note = sheet
    ax, ay = lv.gumball.anchor()
    assert ax == pytest.approx(det.x + det.w / 2)
    assert ay == pytest.approx(det.y + det.h / 2)


def test_a_handful_of_things_share_one_anchor(sheet):
    """The middle of the lot, not the middle of the first one."""
    _w, lv, det, note = sheet
    lv.selected = [("detail", det), ("note", note)]
    from serpentine3d.core.layout import sheet_item_bounds
    a = sheet_item_bounds("detail", det)
    b = sheet_item_bounds("note", note)
    ax, ay = lv.gumball.anchor()
    assert ax == pytest.approx((min(a[0], b[0]) + max(a[2], b[2])) / 2)
    assert ay == pytest.approx((min(a[1], b[1]) + max(a[3], b[3])) / 2)


def test_it_is_the_size_the_model_gumball_is(sheet):
    """78 pixels of arrow, whatever the sheet is zoomed to."""
    from serpentine3d.ui.gumball import SIZE_PX
    _w, lv, _det, _note = sheet
    assert lv.gumball._size_mm() * lv.px_per_mm == pytest.approx(SIZE_PX)


# -------------------------------------------------------------- hit  testing

def test_the_arrows_and_the_pad_are_where_they_are_drawn(sheet):
    _w, lv, _det, _note = sheet
    gb = lv.gumball
    assert gb.hit_test(*_handle(lv, "move", 0)) == ("move", 0)
    assert gb.hit_test(*_handle(lv, "move", 1)) == ("move", 1)
    assert gb.hit_test(*_handle(lv, "pad", 2)) == ("pad", 2)


def test_bare_paper_is_not_a_handle(sheet):
    _w, lv, _det, _note = sheet
    gb = lv.gumball
    ax, ay = gb.anchor()
    far = lv.paper_to_screen(ax + gb._size_mm() * 4, ay)
    assert gb.hit_test(*far) is None


def test_a_cursor_on_a_handle_lights_it(sheet):
    _w, lv, _det, _note = sheet
    gb = lv.gumball
    assert gb.update_hover(*_handle(lv, "move", 1))
    assert gb.hover == ("move", 1)


# --------------------------------------------------------------- dragging it

def _pull(lv, gb, press, dx: float, dy: float):
    """Carry a live drag `dx, dy` paper millimetres from where it started."""
    gb.drag_to(*lv.paper_to_screen(press[0] + dx, press[1] + dy))


def _drag(lv, handle, dx: float, dy: float):
    """Take `handle` at its own pixel and pull it by paper millimetres."""
    gb = lv.gumball
    sx, sy = _handle(lv, handle[0], handle[1])
    press = lv.screen_to_paper(sx, sy)
    assert gb.begin_drag(handle, sx, sy)
    _pull(lv, gb, press, dx, dy)
    return gb, press


def test_the_x_arrow_moves_only_in_x(sheet):
    _w, lv, det, _note = sheet
    x0, y0 = det.x, det.y
    _drag(lv, ("move", 0), 25.0, 40.0)
    assert det.x == pytest.approx(x0 + 25.0)
    assert det.y == pytest.approx(y0)


def test_the_y_arrow_moves_only_in_y(sheet):
    _w, lv, det, _note = sheet
    x0, y0 = det.x, det.y
    _drag(lv, ("move", 1), 40.0, -12.0)
    assert det.x == pytest.approx(x0)
    assert det.y == pytest.approx(y0 - 12.0)


def test_the_pad_moves_in_both(sheet):
    _w, lv, det, _note = sheet
    x0, y0 = det.x, det.y
    _drag(lv, ("pad", 2), 9.0, 6.0)
    assert det.x == pytest.approx(x0 + 9.0)
    assert det.y == pytest.approx(y0 + 6.0)


def test_everything_picked_travels_together(sheet):
    _w, lv, det, note = sheet
    lv.selected = [("detail", det), ("note", note)]
    x0, nx0 = det.x, note.x
    _drag(lv, ("move", 0), 15.0, 0.0)
    assert det.x == pytest.approx(x0 + 15.0)
    assert note.x == pytest.approx(nx0 + 15.0)


def test_dragging_on_does_not_move_it_twice(sheet):
    """Each move is measured from where the drag started, so passing over
    a spot twice leaves the thing where that spot says."""
    _w, lv, det, _note = sheet
    x0 = det.x
    gb, press = _drag(lv, ("move", 0), 30.0, 0.0)
    _pull(lv, gb, press, 10.0, 0.0)
    assert det.x == pytest.approx(x0 + 10.0)


def test_a_locked_detail_in_the_handful_stays_put(sheet):
    _w, lv, det, note = sheet
    det.locked = True
    lv.selected = [("detail", det), ("note", note)]
    x0, nx0 = det.x, note.x
    _drag(lv, ("move", 0), 20.0, 0.0)
    assert det.x == pytest.approx(x0)
    assert note.x == pytest.approx(nx0 + 20.0)


# ------------------------------------------------------------ typing a value

def test_it_takes_a_typed_distance(sheet):
    """The reason to want a gumball on paper at all: 25mm across, exactly,
    without a steady hand."""
    _w, lv, det, _note = sheet
    x0, y0 = det.x, det.y
    gb = lv.gumball
    assert gb.begin_drag(("move", 0), *_handle(lv, "move", 0))
    gb.arm()
    assert gb.accepts_typing()
    for ch in "25":
        gb.type_char(ch)
    assert gb.commit_typed()
    assert det.x == pytest.approx(x0 + 25.0)
    assert det.y == pytest.approx(y0)
    assert gb.drag is None


def test_a_typed_value_can_go_backwards(sheet):
    _w, lv, det, _note = sheet
    y0 = det.y
    gb = lv.gumball
    assert gb.begin_drag(("move", 1), *_handle(lv, "move", 1))
    gb.arm()
    for ch in "-8":
        gb.type_char(ch)
    assert gb.commit_typed()
    assert det.y == pytest.approx(y0 - 8.0)


def test_the_pad_takes_no_typed_value(sheet):
    """Two directions cannot be told by one number."""
    _w, lv, _det, _note = sheet
    gb = lv.gumball
    assert gb.begin_drag(("pad", 2), *_handle(lv, "pad", 2))
    assert not gb.accepts_typing()


def test_the_readout_says_how_far(sheet):
    _w, lv, _det, _note = sheet
    gb, _press = _drag(lv, ("move", 0), 12.0, 0.0)
    text, _at = gb.readout()
    assert "12" in text


# ---------------------------------------------------------------- undoing it

def test_the_whole_drag_is_one_undo(sheet):
    _w, lv, _det, _note = sheet
    vp = lv.vp
    taken = []
    vp.window_checkpoint = lambda label: taken.append(label)
    gb, press = _drag(lv, ("move", 0), 5.0, 0.0)
    _pull(lv, gb, press, 9.0, 0.0)
    gb.end_drag()
    assert len(taken) == 1


def test_escape_puts_it_back(sheet):
    _w, lv, det, _note = sheet
    x0 = det.x
    gb, _press = _drag(lv, ("move", 0), 40.0, 0.0)
    gb.cancel_drag()
    assert det.x == pytest.approx(x0)
    assert gb.drag is None


def test_a_drag_that_never_moved_leaves_no_checkpoint(sheet):
    """Clicking an arrow to type into it, then thinking better of it."""
    _w, lv, _det, _note = sheet
    vp = lv.vp
    discarded = []
    vp.window_discard_checkpoint = lambda: discarded.append(1)
    gb = lv.gumball
    gb.begin_drag(("move", 0), *_handle(lv, "move", 0))
    gb.end_drag()
    assert discarded


# ------------------------------------------------------------------ drawn on

def test_it_is_painted_over_the_sheet(sheet):
    """Last of the overlay, so a detail's own linework cannot cover it."""
    src = inspect.getsource(type(sheet[1]).paint_overlay)
    assert "gumball.paint(painter)" in src


def test_the_arrows_actually_land_on_the_paper(sheet):
    """Paint it and look: the pixel the hit test names as the X arrow is
    one the paint pass drew on."""
    from PySide6.QtGui import QImage, QPainter
    _w, lv, _det, _note = sheet
    img = QImage(lv.vp.width(), lv.vp.height(), QImage.Format.Format_RGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    lv.gumball.paint(painter)
    painter.end()
    sx, sy = _handle(lv, "move", 0)
    near = [img.pixel(int(sx) + dx, int(sy) + dy)
            for dx in range(-2, 3) for dy in range(-2, 3)]
    assert any(p != 0xFFFFFFFF for p in near)
