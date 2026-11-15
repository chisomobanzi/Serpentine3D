"""Lock, LockOther and UnlockAll work on what a sheet holds.

Reported straight after #130: `lock` on a picked detail did nothing. It did
nothing to anything on a sheet. The command asked the model for objects to
lock, and nothing picked on paper is a model object, so it sat at a "Select
objects" prompt no click on the sheet could answer. No sheet item could be
locked at all: a detail's `locked` is the lock on its view (#130), and the
rest had no lock.

As in Rhino, and as `lock` already works in the model, a locked sheet item
is still drawn and still snapped to, but a click or a band no longer picks
it, so it cannot be moved, scaled or deleted by accident. It is drawn faded
on screen to say so, and prints as it always did. A detail keeps its two
locks apart: locked as an item, its frame cannot be picked and you can still
double-click into it; its view lock is still `detaillock` and Properties.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QColor, QImage, QPainter

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import (
    AngularDim,
    DetailView,
    Hatch,
    Layout,
    Leader,
    LinearDim,
    PaperObject,
    RadialDim,
    TextNote,
    layouts_from_json,
    layouts_to_json,
)
from serpentine3d.ui import annot_paint

FRAME = {"x": 20.0, "y": 30.0, "w": 160.0, "h": 120.0}


@pytest.fixture
def sheet():
    w = MainWindow()
    w.resize(1200, 800)
    box = w.scene.add(g.make_box((0, 0, 0), 40, 30, 20), name="Box")
    lay = Layout(name="Sheet1")
    lay.details.append(DetailView(**FRAME, scale_denom=2.0,
                                  target=[20.0, 15.0, 10.0]))
    lay.objects.append(PaperObject(
        shape=g.make_line((230.0, 20.0, 0.0), (330.0, 20.0, 0.0)),
        name="Rule"))
    lay.notes.append(TextNote(x=230.0, y=200.0, text="NOTE"))
    lay.dims.append(LinearDim(x1=230.0, y1=60.0, x2=330.0, y2=60.0,
                              offset=8.0))
    lay.leaders.append(Leader(points=[[230.0, 100.0], [260.0, 120.0]],
                              text="typ."))
    # over the middle of the detail, so a click there finds it first
    lay.hatches.append(Hatch(points=[[90.0, 80.0], [110.0, 80.0],
                                     [110.0, 100.0], [90.0, 100.0]]))
    lay.rdims.append(RadialDim(cx=360.0, cy=200.0, px=375.0, py=200.0))
    lay.adims.append(AngularDim(vx=360.0, vy=100.0, x1=380.0, y1=100.0,
                                x2=360.0, y2=120.0, radius=15.0))
    w.scene.layouts.append(lay)
    w.switch_space(lay.id)
    lv = w.viewport.layout_view
    lv.fit()
    lv._fitted_for = lay.id
    said: list = []
    w.ctx.add_echo_listener(said.append)
    yield w, lv, lay, box, said
    w.processor.cancel()
    w.mark_saved()
    w.close()


def _items(lay) -> dict:
    return {"detail": lay.details[0], "object": lay.objects[0],
            "note": lay.notes[0], "dim": lay.dims[0],
            "leader": lay.leaders[0], "hatch": lay.hatches[0],
            "rdim": lay.rdims[0], "adim": lay.adims[0]}


# a point on each item's ink, where a click picks it
WHERE = {"detail": (40.0, 140.0), "object": (280.0, 20.0),
         "note": (232.0, 201.0), "dim": (280.0, 68.0),
         "leader": (245.0, 110.0), "hatch": (100.0, 90.0),
         "rdim": (367.0, 200.0), "adim": (375.0, 106.2)}


def _pick(w, lv, *picks):
    lv.selected = list(picks)
    w.viewport.layoutSelectionChanged.emit()


def _press(lv, px, py, add=False):
    lv.press(*lv.paper_to_screen(px, py), add=add)
    lv.release_drag()


def _band(lv, x0, y0, x1, y1):
    lv.press(*lv.paper_to_screen(x0, y0))
    lv.drag_selected(*lv.paper_to_screen(x1, y1))
    lv.release_drag()


# ---------------------------------------------------------------- lock

@pytest.mark.parametrize("kind", list(WHERE))
def test_a_click_picks_each_kind_before_it_is_locked(sheet, kind):
    """The test's own footing: each point is on the item it names."""
    _w, lv, lay, _box, _said = sheet
    _press(lv, *WHERE[kind])
    assert lv.selected == [(kind, _items(lay)[kind])]


@pytest.mark.parametrize("kind", list(WHERE))
def test_lock_locks_what_is_picked_on_the_sheet(sheet, kind):
    w, lv, lay, box, said = sheet
    item = _items(lay)[kind]
    _pick(w, lv, (kind, item))
    w.run_command("lock")
    assert not w.processor.busy, "lock is waiting for a model pick"
    assert item.item_locked
    assert lv.selected == []
    assert not w.scene.get(box.id).locked
    assert "Locked 1 sheet item" in said[-1], said
    if kind == "detail":
        assert not item.locked, "locking the frame is not locking the view"


@pytest.mark.parametrize("kind", list(WHERE))
def test_a_locked_item_cannot_be_clicked_or_banded(sheet, kind):
    _w, lv, lay, _box, _said = sheet
    item = _items(lay)[kind]
    item.item_locked = True
    _press(lv, *WHERE[kind])
    assert (kind, item) not in lv.selected
    _band(lv, 5.0, 5.0, 415.0, 290.0)
    assert (kind, item) not in lv.selected
    assert len(lv.selected) == len(WHERE) - 1


def test_a_click_on_a_locked_hatch_picks_the_detail_under_it(sheet):
    _w, lv, lay, _box, _said = sheet
    lay.hatches[0].item_locked = True
    _press(lv, *WHERE["hatch"])
    assert lv.selected == [("detail", lay.details[0])]


def test_lock_with_nothing_picked_says_how_and_waits_for_nothing(sheet):
    w, _lv, lay, _box, said = sheet
    w.run_command("lock")
    assert not w.processor.busy
    assert not any(i.item_locked for i in _items(lay).values())
    assert "pick" in said[-1].lower(), said


def test_locking_is_one_undo_step(sheet):
    w, lv, lay, _box, _said = sheet
    _pick(w, lv, ("note", lay.notes[0]), ("detail", lay.details[0]))
    w.run_command("lock")
    w.history.undo()
    lay = w.scene.layouts[0]
    assert not lay.notes[0].item_locked
    assert not lay.details[0].item_locked
    w.history.redo()
    lay = w.scene.layouts[0]
    assert lay.notes[0].item_locked and lay.details[0].item_locked


def test_inside_a_detail_lock_still_locks_the_model(sheet):
    w, lv, lay, box, _said = sheet
    lv.entered_detail = lay.details[0].id
    w.selection.set([box.id])
    w.run_command("lock")
    assert w.scene.get(box.id).locked
    assert not any(i.item_locked for i in _items(lay).values())


def test_a_locked_item_is_still_snapped_to(sheet):
    """Visible and snappable, but not pickable: Rhino's lock."""
    w, lv, lay, _box, _said = sheet
    lay.objects[0].item_locked = True
    vp = w.viewport
    vp.snaps.enabled = True
    for key in vp.snaps.types:
        vp.snaps.types[key] = key == "end"
    w.run_command("line")
    sx, sy = lv.paper_to_screen(331.0, 21.0)
    assert vp.world_point_at(sx, sy)[:2] == pytest.approx((330.0, 20.0))


def test_a_locked_detail_can_still_be_stepped_into(sheet):
    _w, lv, lay, _box, _said = sheet
    det = lay.details[0]
    det.item_locked = True
    lv.double_click(*lv.paper_to_screen(40.0, 60.0))
    assert lv.entered_detail == det.id


def test_a_locked_note_is_not_opened_by_a_double_click(sheet):
    _w, lv, lay, _box, _said = sheet
    lay.notes[0].item_locked = True
    assert lv.double_click(*lv.paper_to_screen(*WHERE["note"])) is None
    assert lv.selected == []


def test_annotedit_passes_over_a_locked_note(sheet):
    w, _lv, lay, _box, said = sheet
    note = lay.notes[0]
    note.item_locked = True
    w.run_command("annotedit")
    w.processor.provide((*WHERE["note"], 0.0))
    assert not w.processor.busy
    assert note.text == "NOTE"
    assert "nothing there" in said[-1].lower(), said


# ----------------------------------------------------- lockother, unlock

def test_lockother_locks_the_rest_of_this_sheet(sheet):
    w, lv, lay, box, said = sheet
    keep = ("note", lay.notes[0])
    other = Layout(name="Sheet2")
    other.notes.append(TextNote(x=10.0, y=10.0, text="ELSEWHERE"))
    w.scene.layouts.append(other)
    _pick(w, lv, keep)
    w.run_command("lockother")
    assert not w.processor.busy
    assert not lay.notes[0].item_locked
    assert all(i.item_locked for k, i in _items(lay).items() if k != "note")
    assert not other.notes[0].item_locked
    assert not w.scene.get(box.id).locked
    assert lv.selected == [keep], "what you kept stays picked"
    assert "Locked 7 sheet item" in said[-1], said


def test_unlockall_on_a_sheet_unlocks_every_sheet_and_the_model(sheet):
    w, _lv, lay, box, said = sheet
    other = Layout(name="Sheet2")
    other.notes.append(TextNote(x=10.0, y=10.0, text="ELSEWHERE",
                                item_locked=True))
    w.scene.layouts.append(other)
    for item in _items(lay).values():
        item.item_locked = True
    w.scene.update(box.id, locked=True)
    lay.details[0].locked = True            # its view: not unlockall's
    w.run_command("unlockall")
    assert not any(i.item_locked for i in _items(lay).values())
    assert not other.notes[0].item_locked
    assert not w.scene.get(box.id).locked
    assert lay.details[0].locked, "the view lock is detaillock's"
    assert "1 object" in said[-1] and "9 sheet item" in said[-1], said


def test_unlockall_from_the_model_unlocks_sheet_items_too(sheet):
    w, _lv, lay, _box, said = sheet
    lay.notes[0].item_locked = True
    w.switch_space("model")
    said.clear()
    w.run_command("unlockall")
    assert not lay.notes[0].item_locked
    assert said[-1] == "Unlocked 1 sheet item(s).", said


# -------------------------------------------------------- kept and drawn

def test_the_lock_is_saved_and_read_back():
    lay = Layout(name="S")
    lay.details.append(DetailView(item_locked=True))
    lay.notes.append(TextNote(text="N", item_locked=True))
    lay.objects.append(PaperObject(
        shape=g.make_line((0.0, 0.0, 0.0), (10.0, 0.0, 0.0)),
        item_locked=True))
    back, = layouts_from_json(layouts_to_json([lay]))
    assert back.details[0].item_locked and not back.details[0].locked
    assert back.notes[0].item_locked
    assert back.objects[0].item_locked


def test_a_file_from_before_the_lock_opens_unlocked():
    data = layouts_to_json([Layout(name="S", notes=[TextNote(text="N")])])
    del data[0]["notes"][0]["item_locked"]
    back, = layouts_from_json(data)
    assert not back.notes[0].item_locked


def _ink_of_note(locked: bool, faded: bool) -> int:
    """How dark the darkest pixel of a note comes out, 0 black."""
    lay = Layout(name="S", notes=[TextNote(x=2.0, y=2.0, text="WWW",
                                           height=8.0, item_locked=locked)])
    img = QImage(400, 120, QImage.Format.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    annot_paint.draw_all(p, lambda x, y: (x * 4.0, 120 - y * 4.0), 4.0, lay,
                         faded=faded)
    p.end()
    return min(img.pixelColor(x, y).value()
               for x in range(0, 400, 2) for y in range(0, 120, 2))


def test_on_screen_a_locked_item_is_faded():
    assert _ink_of_note(locked=True, faded=True) > \
        _ink_of_note(locked=False, faded=True) + 60


def test_printed_a_locked_item_is_drawn_as_it_always_was():
    assert _ink_of_note(locked=True, faded=False) == \
        _ink_of_note(locked=False, faded=False)


def test_locked_paper_geometry_is_faded_on_screen(sheet):
    _w, lv, lay, _box, _said = sheet
    rule = lay.objects[0]
    ink = lv._object_ink(rule)
    rule.item_locked = True
    faded = lv._object_ink(rule)
    assert sum(faded[:3]) > sum(ink[:3]) + 0.6
