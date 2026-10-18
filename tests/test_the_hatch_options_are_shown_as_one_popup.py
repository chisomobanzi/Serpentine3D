"""Hatch asks for its pattern, spacing and angle in one popup (#45).

What was asked three prompts in a row is asked as one thing now. The
command still only yields a FormReq, so this is two separate claims and
they are tested apart: that Hatch asks for a form at all, and that the
window draws one as a dialog with a widget per field, greying the fields
that do not apply.

The dialog is built but never exec()d here: a modal loop has nothing to
close it under the offscreen runner.
"""

from __future__ import annotations

import math

import pytest

from serpentine3d.commands.base import FormReq, NumberReq, OptionReq
from serpentine3d.core import geometry as g

pytest.importorskip("PySide6.QtWidgets")


def _square(size=10.0, corner=(0.0, 0.0)):
    x, y = corner
    return g.make_polyline([(x, y, 0), (x + size, y, 0),
                            (x + size, y + size, 0), (x, y + size, 0)],
                           closed=True)


# -- what the command asks for ---------------------------------------------

def test_hatch_asks_for_its_three_answers_as_one_form(env):
    scene, _sel, _hist, _ctx, proc = env
    outline = scene.add(_square(), name="Outline")

    proc.run("hatch")
    proc.click_object(outline.id)
    proc.finish_selection()

    form = proc.form
    assert isinstance(form, FormReq)
    assert [f.name for f in form.fields] == ["pattern", "spacing", "angle"]
    assert isinstance(form.fields[0].req, OptionReq)
    assert isinstance(form.fields[1].req, NumberReq)
    assert form.title == "Hatch"


def test_the_spacing_and_angle_do_not_apply_to_a_solid_hatch(env):
    scene, _sel, _hist, _ctx, proc = env
    outline = scene.add(_square(), name="Outline")

    proc.run("hatch")
    proc.click_object(outline.id)
    proc.finish_selection()
    fields = {f.name: f for f in proc.form.fields}

    assert fields["pattern"].when is None
    assert fields["spacing"].when({"pattern": "Solid"}) is False
    assert fields["spacing"].when({"pattern": "Lines"}) is True


def test_the_popup_can_answer_the_whole_thing(env):
    scene, sel, _hist, _ctx, proc = env
    outline = scene.add(_square(), name="Outline")

    proc.run("hatch")
    proc.click_object(outline.id)
    proc.finish_selection()
    proc.provide_form({"pattern": "Lines", "spacing": 0.5, "angle": 30.0})

    hatches = [o for o in scene.all() if o.kind == "hatch"]
    assert len(hatches) == 1
    shape = hatches[0].shape
    assert (shape.pattern, shape.spacing, shape.angle) == ("lines", 0.5, 30.0)
    assert sel.ids == [hatches[0].id]


def test_the_area_about_to_be_filled_is_ghosted_while_it_asks(env):
    """With nothing to pick there is nothing else to see, and which area
    the pattern is about to land on is worth as much as it is during a
    pick of several curves."""
    scene, _sel, _hist, _ctx, proc = env
    outline = scene.add(_square(), name="Outline")
    island = scene.add(g.make_circle((5.0, 5.0, 0.0), 2.0), name="Island")

    proc.run("hatch")
    proc.click_object(outline.id)
    proc.click_object(island.id)
    proc.finish_selection()

    req = proc.request
    assert req.preview_fn is not None, "nothing would be ghosted"
    ghost = proc.preview_for(req.default)
    # the area that will be filled, hole and all
    assert g.surface_area(ghost) == pytest.approx(100.0 - math.pi * 4,
                                                  rel=1e-3)


def test_the_spacing_question_ghosts_the_same_area(env):
    scene, _sel, _hist, _ctx, proc = env
    outline = scene.add(_square(), name="Outline")

    proc.run("hatch")
    proc.click_object(outline.id)
    proc.finish_selection()
    proc.provide_text("Lines")

    assert proc.request.prompt.startswith("Line spacing")
    assert proc.request.preview_fn is not None


# -- what the window draws it as -------------------------------------------

@pytest.fixture
def dialog(_qapp):
    from serpentine3d.commands.base import FormField
    from serpentine3d.ui.form_dialog import FormDialog
    not_solid = lambda a: str(a.get("pattern", "")).lower() != "solid"
    form = FormReq("Hatch", title="Hatch", fields=(
        FormField("pattern", OptionReq("Pattern",
                                       options=["Lines", "Solid"],
                                       default="Lines")),
        FormField("spacing", NumberReq("Line spacing", default=0.5,
                                       minimum=1e-6), when=not_solid),
        FormField("angle", NumberReq("Angle (degrees)", default=45.0),
                  when=not_solid),
    ))
    d = FormDialog(form)
    yield d
    d.deleteLater()


def test_the_dialog_shows_a_widget_for_every_field(dialog):
    assert sorted(dialog.values()) == ["angle", "pattern", "spacing"]
    assert dialog.values()["pattern"] == "Lines"
    assert dialog.values()["spacing"] == pytest.approx(0.5)


def test_the_dialog_greys_what_does_not_apply(dialog):
    from PySide6.QtWidgets import QComboBox

    assert dialog._widgets["spacing"].isEnabled()
    box = dialog._widgets["pattern"]
    assert isinstance(box, QComboBox)
    box.setCurrentText("Solid")

    assert not dialog._widgets["spacing"].isEnabled()
    assert not dialog._widgets["angle"].isEnabled()


def test_the_number_box_can_hold_a_millimetre_spacing(_qapp):
    """A hatch over a 4mm detail opens on a spacing of 0.0002, and a box
    counting to two decimals would round that to nothing and refuse."""
    from serpentine3d.commands.base import FormField
    from serpentine3d.ui.form_dialog import FormDialog

    form = FormReq("Hatch", title="Hatch", fields=(
        FormField("spacing", NumberReq("Line spacing", default=0.0002,
                                       minimum=1e-6)),
    ))
    d = FormDialog(form)
    try:
        assert d.values()["spacing"] == pytest.approx(0.0002)
    finally:
        d.deleteLater()


def test_a_number_shows_the_digits_it_has_and_no_more(_qapp):
    """The box counts to seven places so a 4mm detail can be hatched;
    a spacing of half a unit must not read as 0.5000 because of it."""
    from serpentine3d.commands.base import FormField
    from serpentine3d.ui.form_dialog import FormDialog

    form = FormReq("Hatch", title="Hatch", fields=(
        FormField("spacing", NumberReq("Line spacing", default=0.5,
                                       minimum=1e-6)),
        FormField("angle", NumberReq("Angle (degrees)", default=45.0)),
        FormField("fine", NumberReq("Fine spacing", default=0.0002,
                                    minimum=1e-6)),
    ))
    d = FormDialog(form)
    try:
        point = str(d._widgets["spacing"].locale().decimalPoint())
        assert d._widgets["spacing"].text() == f"0{point}5"
        assert d._widgets["angle"].text() == f"45{point}0"
        assert d._widgets["fine"].text() == f"0{point}0002"
        assert d.values()["fine"] == pytest.approx(0.0002)
    finally:
        d.deleteLater()


def test_the_dialog_hands_back_what_it_was_left_showing(dialog):
    dialog._widgets["pattern"].setCurrentText("Solid")
    dialog._widgets["angle"].setValue(12.5)

    values = dialog.values()
    assert values["pattern"] == "Solid"
    assert values["angle"] == pytest.approx(12.5)


# -- in the window -----------------------------------------------------------

@pytest.fixture
def window(_qapp, monkeypatch):
    """A main window whose hatch popup records itself instead of blocking,
    and answers OK with whatever it is showing."""
    from PySide6.QtWidgets import QApplication, QDialog

    from serpentine3d.app import MainWindow
    from serpentine3d.ui import form_dialog

    shown = []

    def _exec(dialog):
        shown.append(dialog.values())
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(form_dialog.FormDialog, "exec", _exec)
    w = MainWindow()
    w.shown_forms = shown
    yield w
    w.mark_saved()
    w.close()
    QApplication.processEvents()


def _hatch_held_square(w, typed=""):
    from PySide6.QtWidgets import QApplication

    outline = w.scene.add(_square(), name="Outline")
    w.selection.set([outline.id])
    w.processor.run(f"hatch {typed}".strip())
    QApplication.processEvents()        # the turn the popup waits for
    return [o for o in w.scene.all() if o.kind == "hatch"]


def test_answers_typed_after_the_command_name_are_not_overruled(window):
    """`hatch Solid` means solid. The popup used to open before the typed
    answer was read, showing the layer's pattern, and OK made that."""
    hatches = _hatch_held_square(window, "Solid")

    assert [h.shape.pattern for h in hatches] == ["solid"]
    assert window.shown_forms == [], "the answer was typed, nothing to ask"


def test_a_partly_typed_form_carries_on_at_the_prompt(window):
    """Someone who typed the pattern is typing: the popup would open on
    the layer's pattern again, so the rest is asked where they are."""
    hatches = _hatch_held_square(window, "Cross")

    assert hatches == []
    assert window.shown_forms == []
    assert window.processor.busy
    assert "spacing" in window.processor.request.prompt.lower()
    window.processor.cancel()


def test_with_nothing_typed_the_popup_asks(window):
    hatches = _hatch_held_square(window)

    assert len(window.shown_forms) == 1
    assert [h.shape.pattern for h in hatches] == [
        window.shown_forms[0]["pattern"].lower()]
