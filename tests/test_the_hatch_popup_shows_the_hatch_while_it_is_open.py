"""The hatch popup shows the hatch it would make while it is still open.

Asked for: seeing the hatch live while the popup is open. The popup used
to ghost only the region about to be filled, so a pattern, a spacing or an
angle was only seen once OK had made it. Now the form says what its
answers would make, and the window ghosts that as the answers change: the
lines in the model, and the hatch itself on a sheet.

The dialog is never exec()d here; a modal loop has nothing to close it
under the offscreen runner.
"""

from __future__ import annotations

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.hatch import HatchShape
from serpentine3d.core.layout import Hatch

pytest.importorskip("PySide6.QtWidgets")


def _square(size=10.0):
    return g.make_polyline([(0, 0, 0), (size, 0, 0), (size, size, 0),
                            (0, size, 0)], closed=True)


def _asking(env):
    scene, _sel, _hist, _ctx, proc = env
    outline = scene.add(_square(), name="Outline")
    proc.run("hatch")
    proc.click_object(outline.id)
    proc.finish_selection()
    return proc.form


def test_the_form_says_what_its_answers_would_make(env):
    form = _asking(env)

    ghost = form.preview_fn({"pattern": "Cross", "spacing": 2.0,
                             "angle": 30.0})
    assert isinstance(ghost, HatchShape)
    assert (ghost.pattern, ghost.spacing, ghost.angle) == ("cross", 2.0, 30.0)


def test_a_spacing_too_fine_to_draw_ghosts_the_region_instead(env):
    form = _asking(env)

    ghost = form.preview_fn({"pattern": "Lines", "spacing": 1e-6,
                             "angle": 0.0})
    assert not isinstance(ghost, HatchShape)
    assert g.surface_area(ghost) == pytest.approx(100.0)


def test_at_the_prompt_each_answer_shows_the_hatch_it_would_make(env):
    form = _asking(env)
    proc = env[4]

    ghost = proc.preview_for("Cross")
    assert isinstance(ghost, HatchShape) and ghost.pattern == "cross"
    assert form.fields[0].req.preview_fn is not None


def test_the_dialog_says_when_its_answers_change(_qapp):
    from serpentine3d.commands.base import (FormField, FormReq, NumberReq,
                                            OptionReq)
    from serpentine3d.ui.form_dialog import FormDialog

    told = []
    form = FormReq("Hatch", title="Hatch", fields=(
        FormField("pattern", OptionReq("Pattern", options=["Lines", "Cross"],
                                       default="Lines")),
        FormField("spacing", NumberReq("Line spacing", default=1.0)),
    ))
    dialog = FormDialog(form, changed=told.append)
    try:
        dialog._widgets["pattern"].setCurrentText("Cross")
        dialog._widgets["spacing"].setValue(2.5)
        assert told[-2]["pattern"] == "Cross"
        assert told[-1] == {"pattern": "Cross", "spacing": 2.5}
    finally:
        dialog.deleteLater()


@pytest.fixture
def window(_qapp, monkeypatch):
    """A main window whose popup records the ghost each pane had while it
    was open, then answers OK with a change made in it."""
    from PySide6.QtWidgets import QApplication, QDialog

    from serpentine3d.app import MainWindow
    from serpentine3d.ui import form_dialog

    w = MainWindow()
    w.ghosts = []

    def _exec(dialog):
        dialog._tell()
        w.ghosts.append(w.viewport._ghost)
        dialog._widgets["pattern"].setCurrentText("Cross")
        w.ghosts.append(w.viewport._ghost)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(form_dialog.FormDialog, "exec", _exec)
    yield w
    w.mark_saved()
    w.close()
    QApplication.processEvents()


def test_the_window_ghosts_the_hatch_while_the_popup_is_open(window):
    from PySide6.QtWidgets import QApplication

    outline = window.scene.add(_square(), name="Outline")
    window.selection.set([outline.id])
    window.processor.run("hatch")
    QApplication.processEvents()        # the turn the popup waits for

    first, changed = window.ghosts
    assert first is not None and changed is not None
    assert changed is not first, "the ghost did not follow the popup"
    assert window.viewport._ghost is None, "the ghost outlived the popup"
    (made,) = [o for o in window.scene.all() if o.kind == "hatch"]
    assert made.shape.pattern == "cross"


def test_a_sheet_s_hatch_is_ghosted_as_itself(_qapp):
    from PySide6.QtWidgets import QApplication

    from serpentine3d.app import MainWindow

    w = MainWindow()
    try:
        hatch = Hatch(points=[[0, 0], [10, 0], [10, 10]], pattern="cross")
        w.viewport.set_ghost(hatch)
        assert w.viewport.layout_view._ghost_hatch is hatch
        assert w.viewport._ghost is None
        w.viewport.set_ghost(None)
        assert w.viewport.layout_view._ghost_hatch is None
    finally:
        w.mark_saved()
        w.close()
        QApplication.processEvents()
