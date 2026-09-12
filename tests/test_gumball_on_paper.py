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

import copy
import inspect
import math

import numpy as np
import pytest
from PySide6.QtCore import Qt

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import (DetailView, Layout, TextNote,
                                     annotation_bounds)
from serpentine3d.core.picture import PictureShape
from serpentine3d.ui.camera import STANDARD_VIEWS
from serpentine3d.ui.gumball import ARC_R, CONE1, PAD0, PAD1, SHAFT0, SIZE_PX


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


def _rotation_handle(lv, required=True):
    """Find the paper rotation ring through the public hit-test boundary.

    Its exact radius is presentation, not behaviour, so the interaction tests
    look for the ring around the visible gumball instead of duplicating a
    drawing constant from production.
    """
    ax, ay = lv.gumball.anchor()
    cx, cy = lv.paper_to_screen(ax, ay)
    for radius in range(12, 101, 2):
        for degrees in range(0, 360, 4):
            angle = math.radians(degrees)
            point = (cx + radius * math.cos(angle),
                     cy - radius * math.sin(angle))
            if lv.gumball.hit_test(*point) == ("rot", 2):
                return point
    if required:
        raise AssertionError(
            "selected paper geometry should offer a Z-axis rotation ring")
    return None


def _rotation_point(lv, degrees):
    """A point on the visible paper rotation radius.

    Positive angles run from the red +X arrow towards the green +Y arrow,
    matching paper coordinates even though screen Y runs downwards.
    """
    ax, ay = lv.gumball.anchor()
    cx, cy = lv.paper_to_screen(ax, ay)
    angle = math.radians(degrees)
    radius = ARC_R * SIZE_PX
    return (cx + radius * math.cos(angle),
            cy - radius * math.sin(angle))


def _rotated(points, centre, degrees):
    points = np.asarray(points, float)
    centre = np.asarray(centre, float)
    angle = math.radians(degrees)
    matrix = np.array([[math.cos(angle), -math.sin(angle)],
                       [math.sin(angle), math.cos(angle)]])
    out = points.copy()
    out[:, :2] = centre + (points[:, :2] - centre) @ matrix.T
    return out


def _turn_ring(lv, degrees, modifiers=None):
    """Take the ring and move through `degrees` in paper coordinates."""
    gb = lv.gumball
    sx, sy = _rotation_handle(lv)
    anchor = np.asarray(gb.anchor(), float)
    start = np.asarray(lv.screen_to_paper(sx, sy), float)
    direction = start - anchor
    angle = math.radians(degrees)
    turned = np.array([
        direction[0] * math.cos(angle) - direction[1] * math.sin(angle),
        direction[0] * math.sin(angle) + direction[1] * math.cos(angle),
    ])
    assert gb.begin_drag(("rot", 2), sx, sy, modifiers)
    label = gb.drag_to(*lv.paper_to_screen(*(anchor + turned)), modifiers)
    return gb, label


def _paper_geometry(sheet):
    """An ordinary curve and a picture, spaced so they share one pivot."""
    _w, lv, _det, _note = sheet
    lay = lv.layout
    line = lay.add(g.make_line((20.0, 20.0, 0.0),
                               (40.0, 20.0, 0.0)), name="Line")
    picture = lay.add(PictureShape({
        "origin": [80.0, 40.0, 0.0],
        "u": [20.0, 0.0, 0.0],
        "v": [0.0, 10.0, 0.0],
        "image_data": b"picture bytes",
        "alpha": 1.0,
    }), name="Picture")
    lv.selected = [("object", line), ("object", picture)]
    return line, picture


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


def _drag(lv, handle, dx: float, dy: float, modifiers=None):
    """Take `handle` at its own pixel and pull it by paper millimetres."""
    gb = lv.gumball
    sx, sy = _handle(lv, handle[0], handle[1])
    press = lv.screen_to_paper(sx, sy)
    assert gb.begin_drag(handle, sx, sy, modifiers)
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


@pytest.mark.parametrize(
    ("handle", "pull", "expected"),
    [
        (("move", 0), (12.0, 7.0), (12.0, 0.0)),
        (("pad", 2), (9.0, 6.0), (9.0, 6.0)),
    ],
    ids=("axis-arrow", "plane-square"),
)
def test_alt_drag_duplicates_the_selected_note_as_one_undo(
        sheet, handle, pull, expected):
    w, lv, _det, note = sheet
    lv.selected = [("note", note)]
    x0, y0 = note.x, note.y
    undo0 = len(w.history._undo)

    gb, _press = _drag(
        lv, handle, *pull, Qt.KeyboardModifier.AltModifier)
    gb.end_drag()

    assert len(w.scene.layouts[0].notes) == 2
    original = next(item for item in w.scene.layouts[0].notes
                    if item.id == note.id)
    duplicate = next(item for item in w.scene.layouts[0].notes
                     if item.id != note.id)
    assert (original.x, original.y) == pytest.approx((x0, y0))
    assert (duplicate.x, duplicate.y) == pytest.approx(
        (x0 + expected[0], y0 + expected[1]))
    assert lv.selected == [("note", duplicate)]
    assert len(w.history._undo) == undo0 + 1

    w.history.undo()
    restored, = w.scene.layouts[0].notes
    assert restored.id == note.id
    assert (restored.x, restored.y) == pytest.approx((x0, y0))


def test_shift_dragging_the_pad_scales_a_note_uniformly_about_its_centre(
        sheet):
    w, lv, _det, note = sheet
    lv.selected = [("note", note)]
    original_state = copy.deepcopy(vars(note))
    original_bounds = annotation_bounds("note", note, w.scene)
    original_centre = ((original_bounds[0] + original_bounds[2]) / 2,
                       (original_bounds[1] + original_bounds[3]) / 2)
    original_size = (original_bounds[2] - original_bounds[0],
                     original_bounds[3] - original_bounds[1])
    undo0 = len(w.history._undo)

    gb = lv.gumball
    original_anchor = gb.anchor()
    assert original_anchor == pytest.approx(original_centre)
    sx, sy = _handle(lv, "pad", 2)
    press = lv.screen_to_paper(sx, sy)
    shift = Qt.KeyboardModifier.ShiftModifier
    assert gb.begin_drag(("pad", 2), sx, sy, shift)
    tx, ty = lv.paper_to_screen(press[0] + 12., press[1] + 12.)
    gb.drag_to(tx, ty, shift)
    gb.end_drag()

    scaled_bounds = annotation_bounds("note", note, w.scene)
    scaled_centre = ((scaled_bounds[0] + scaled_bounds[2]) / 2,
                     (scaled_bounds[1] + scaled_bounds[3]) / 2)
    scaled_size = (scaled_bounds[2] - scaled_bounds[0],
                   scaled_bounds[3] - scaled_bounds[1])
    factors = (scaled_size[0] / original_size[0],
               scaled_size[1] / original_size[1])

    assert factors[0] > 1.1, (
        "Shift-dragging the plane square must materially enlarge the note")
    assert factors[0] == pytest.approx(factors[1])
    assert scaled_centre == pytest.approx(original_centre)
    assert gb.anchor() == pytest.approx(original_anchor)
    assert lv.selected == [("note", note)]
    assert len(w.scene.layouts[0].notes) == 1
    assert len(w.history._undo) == undo0 + 1

    w.history.undo()
    restored, = w.scene.layouts[0].notes
    assert vars(restored) == original_state
    assert annotation_bounds("note", restored, w.scene) == pytest.approx(
        original_bounds)


# ------------------------------------------------------------- rotating it

def test_paper_geometry_gets_a_visible_blue_rotation_ring(sheet):
    _w, lv, _det, _note = sheet
    _line, picture = _paper_geometry(sheet)
    lv.selected = [("object", picture)]

    sx, sy = _rotation_point(lv, 45)
    assert lv.gumball.hit_test(sx, sy) == ("rot", 2)

    # Paint through the same overlay path the user sees.  At least one pixel
    # around the hit target must carry the blue Z-axis ink of the ring.
    from PySide6.QtGui import QColor, QImage, QPainter
    img = QImage(lv.vp.width(), lv.vp.height(), QImage.Format.Format_RGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    lv.gumball.paint(painter)
    painter.end()
    colours = [QColor.fromRgba(img.pixel(int(sx) + dx, int(sy) + dy))
               for dx in range(-5, 6) for dy in range(-5, 6)]
    assert any(c.blue() > c.red() + 20 and c.blue() > c.green() + 20
               for c in colours), "the Z rotation ring should be blue"


@pytest.mark.parametrize("degrees", [10, 80, 135, 225, 315])
def test_rotation_is_only_hit_on_the_arc_between_the_positive_arrows(
        sheet, degrees):
    """The handle is a short first-quadrant arc with room at both ends."""
    _w, lv, _det, _note = sheet
    _line, picture = _paper_geometry(sheet)
    lv.selected = [("object", picture)]

    assert lv.gumball.hit_test(*_rotation_point(lv, degrees)) \
        != ("rot", 2)


def test_rotation_ink_ends_where_its_hit_target_ends(sheet):
    """No invisible ring target remains where the blue arc is absent."""
    _w, lv, _det, _note = sheet
    _line, picture = _paper_geometry(sheet)
    lv.selected = [("object", picture)]

    from PySide6.QtGui import QColor, QImage, QPainter
    img = QImage(lv.vp.width(), lv.vp.height(), QImage.Format.Format_RGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    lv.gumball.paint(painter)
    painter.end()

    def blue_near(point):
        px, py = map(int, point)
        colours = [QColor.fromRgba(img.pixel(px + dx, py + dy))
                   for dx in range(-3, 4) for dy in range(-3, 4)]
        return any(c.blue() > c.red() + 20 and c.blue() > c.green() + 20
                   for c in colours)

    assert blue_near(_rotation_point(lv, 45))
    for degrees in (10, 80, 135, 225, 315):
        point = _rotation_point(lv, degrees)
        assert lv.gumball.hit_test(*point) != ("rot", 2)
        assert not blue_near(point)


def test_rotation_arc_preserves_arrow_and_pad_hit_priority(sheet):
    _w, lv, _det, _note = sheet
    _line, picture = _paper_geometry(sheet)
    lv.selected = [("object", picture)]

    assert lv.gumball.hit_test(*_handle(lv, "move", 0)) == ("move", 0)
    assert lv.gumball.hit_test(*_handle(lv, "move", 1)) == ("move", 1)
    assert lv.gumball.hit_test(*_handle(lv, "pad", 2)) == ("pad", 2)


@pytest.mark.parametrize("selection", ["detail", "note", "mixed"])
def test_items_without_a_rotation_representation_offer_no_ring(sheet,
                                                                selection):
    _w, lv, det, note = sheet
    if selection == "detail":
        lv.selected = [("detail", det)]
    elif selection == "note":
        lv.selected = [("note", note)]
    else:
        line, _picture = _paper_geometry(sheet)
        lv.selected = [("object", line), ("note", note)]
    assert _rotation_handle(lv, required=False) is None


def test_dragging_the_ring_rotates_geometry_live_about_its_shared_centre(
        sheet):
    w, lv, _det, _note = sheet
    line, picture = _paper_geometry(sheet)
    centre = np.asarray(lv.gumball.anchor(), float)
    line_before = np.asarray(line.polylines[0], float).copy()
    picture_before = picture.shape.vertices.copy()
    picture_data = picture.shape.plane["image_data"]
    undo0 = len(w.history._undo)

    gb, label = _turn_ring(lv, 90.0)

    # This is asserted before mouse-up: rotation is a live preview, and the
    # positive drag direction is counter-clockwise on the paper.
    np.testing.assert_allclose(
        line.polylines[0], _rotated(line_before, centre, 90.0), atol=1e-6)
    np.testing.assert_allclose(
        picture.shape.vertices,
        _rotated(picture_before, centre, 90.0), atol=1e-6)
    assert picture.shape.plane["image_data"] == picture_data
    assert "90" in label
    assert "°" in label or "deg" in label.lower()

    gb.end_drag()
    assert len(w.history._undo) == undo0 + 1
    assert lv.selected == [("object", line), ("object", picture)]

    w.history.undo()
    restored_line, restored_picture = w.scene.layouts[0].objects
    np.testing.assert_allclose(restored_line.polylines[0], line_before,
                               atol=1e-6)
    np.testing.assert_allclose(restored_picture.shape.vertices,
                               picture_before, atol=1e-6)


def test_alt_dragging_the_ring_rotates_fresh_copies_as_one_undo(sheet):
    w, lv, _det, _note = sheet
    line, picture = _paper_geometry(sheet)
    line.color = (0.2, 0.4, 0.6)
    line.linetype = "Dashed"
    line.lineweight = 0.7
    centre = np.asarray(lv.gumball.anchor(), float)
    line_before = np.asarray(line.polylines[0], float).copy()
    picture_before = picture.shape.vertices.copy()
    original_ids = {line.id, picture.id}
    original_selection = list(lv.selected)
    undo0 = len(w.history._undo)

    gb, _label = _turn_ring(
        lv, 90.0, Qt.KeyboardModifier.AltModifier)

    objects = w.scene.layouts[0].objects
    originals = {obj.id: obj for obj in objects if obj.id in original_ids}
    duplicates = [obj for obj in objects if obj.id not in original_ids]
    assert len(duplicates) == 2
    duplicate_line = next(obj for obj in duplicates if obj.name == line.name)
    duplicate_picture = next(obj for obj in duplicates
                             if obj.name == picture.name)

    # Alt-copy leaves the source geometry exactly where it was and previews
    # the turn on the fresh, selected copies around the original shared pivot.
    np.testing.assert_allclose(originals[line.id].polylines[0], line_before,
                               atol=1e-6)
    np.testing.assert_allclose(originals[picture.id].shape.vertices,
                               picture_before, atol=1e-6)
    np.testing.assert_allclose(
        duplicate_line.polylines[0],
        _rotated(line_before, centre, 90.0), atol=1e-6)
    np.testing.assert_allclose(
        duplicate_picture.shape.vertices,
        _rotated(picture_before, centre, 90.0), atol=1e-6)
    assert [obj.id for _kind, obj in lv.selected] == [
        duplicate_line.id, duplicate_picture.id]

    # A copy keeps everything the user sees and everything needed to render
    # an embedded picture, while its identity is independent of the source.
    assert duplicate_line.id != line.id
    assert duplicate_line.name == line.name
    assert duplicate_line.color == line.color
    assert duplicate_line.linetype == line.linetype
    assert duplicate_line.lineweight == line.lineweight
    assert duplicate_picture.id != picture.id
    assert duplicate_picture.name == picture.name
    assert duplicate_picture.shape.plane["image_data"] \
        == picture.shape.plane["image_data"]
    assert duplicate_picture.shape.plane["alpha"] \
        == picture.shape.plane["alpha"]

    gb.end_drag()
    assert len(w.history._undo) == undo0 + 1

    w.history.undo()
    restored = w.scene.layouts[0].objects
    assert {obj.id for obj in restored} == original_ids
    restored_by_id = {obj.id: obj for obj in restored}
    np.testing.assert_allclose(restored_by_id[line.id].polylines[0],
                               line_before, atol=1e-6)
    np.testing.assert_allclose(restored_by_id[picture.id].shape.vertices,
                               picture_before, atol=1e-6)
    assert [obj.id for _kind, obj in lv.selected] == [
        obj.id for _kind, obj in original_selection]


def test_alt_clicking_the_rotation_arc_without_turning_abandons_the_copies(
        sheet):
    w, lv, _det, _note = sheet
    line, picture = _paper_geometry(sheet)
    original_ids = [line.id, picture.id]
    undo0 = len(w.history._undo)
    sx, sy = _rotation_handle(lv)

    gb = lv.gumball
    assert gb.begin_drag(("rot", 2), sx, sy,
                         Qt.KeyboardModifier.AltModifier)
    assert len(w.scene.layouts[0].objects) == 4
    assert all(obj.id not in original_ids for _kind, obj in lv.selected)

    gb.end_drag()

    assert [obj.id for obj in w.scene.layouts[0].objects] == original_ids
    assert [obj.id for _kind, obj in lv.selected] == original_ids
    assert len(w.history._undo) == undo0


def test_escape_abandons_live_alt_rotation_copies(sheet):
    w, lv, _det, _note = sheet
    line, picture = _paper_geometry(sheet)
    line_before = np.asarray(line.polylines[0], float).copy()
    picture_before = picture.shape.vertices.copy()
    original_ids = [line.id, picture.id]
    undo0 = len(w.history._undo)

    gb, _label = _turn_ring(
        lv, 38.0, Qt.KeyboardModifier.AltModifier)
    assert len(w.scene.layouts[0].objects) == 4
    assert all(obj.id not in original_ids for _kind, obj in lv.selected)

    gb.cancel_drag()

    assert [obj.id for obj in w.scene.layouts[0].objects] == original_ids
    assert [obj.id for _kind, obj in lv.selected] == original_ids
    np.testing.assert_allclose(line.polylines[0], line_before, atol=1e-6)
    np.testing.assert_allclose(picture.shape.vertices, picture_before,
                               atol=1e-6)
    assert len(w.history._undo) == undo0


def test_shift_snaps_paper_rotation_to_fifteen_degrees(sheet):
    _w, lv, _det, _note = sheet
    _line, picture = _paper_geometry(sheet)
    lv.selected = [("object", picture)]
    original_u = np.asarray(picture.shape.plane["u"], float)
    shift = Qt.KeyboardModifier.ShiftModifier

    gb, label = _turn_ring(lv, 22.0, shift)
    turned_u = np.asarray(picture.shape.plane["u"], float)
    angle = math.degrees(math.atan2(
        original_u[0] * turned_u[1] - original_u[1] * turned_u[0],
        original_u[:2] @ turned_u[:2]))

    assert angle == pytest.approx(15.0, abs=1e-6)
    assert "15" in label
    assert "°" in label or "deg" in label.lower()
    gb.end_drag()


def test_escape_restores_paper_geometry_after_a_live_rotation(sheet):
    _w, lv, _det, _note = sheet
    line, picture = _paper_geometry(sheet)
    line_before = np.asarray(line.polylines[0], float).copy()
    picture_before = picture.shape.vertices.copy()

    gb, _label = _turn_ring(lv, -38.0)
    assert not np.allclose(line.polylines[0], line_before)
    gb.cancel_drag()

    np.testing.assert_allclose(line.polylines[0], line_before, atol=1e-6)
    np.testing.assert_allclose(picture.shape.vertices, picture_before,
                               atol=1e-6)
    assert gb.drag is None


def test_the_paper_rotation_ring_takes_a_typed_angle(sheet):
    _w, lv, _det, _note = sheet
    _line, picture = _paper_geometry(sheet)
    lv.selected = [("object", picture)]
    original_u = np.asarray(picture.shape.plane["u"], float)
    gb = lv.gumball
    sx, sy = _rotation_handle(lv)

    assert gb.begin_drag(("rot", 2), sx, sy)
    gb.arm()
    assert gb.accepts_typing()
    for char in "30":
        assert gb.type_char(char)
    text, _position = gb.readout()
    assert "30" in text
    assert "angle" in text.lower() or "°" in text or "deg" in text.lower()
    assert gb.commit_typed()

    turned_u = np.asarray(picture.shape.plane["u"], float)
    angle = math.degrees(math.atan2(
        original_u[0] * turned_u[1] - original_u[1] * turned_u[0],
        original_u[:2] @ turned_u[:2]))
    assert angle == pytest.approx(30.0, abs=1e-6)
    assert gb.drag is None


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
