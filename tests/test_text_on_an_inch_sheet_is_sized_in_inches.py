"""Text on a sheet is sized in the units the sheet is read in.

An inch or a feet document reads its sheets in inches (#113), but a note's
cap height and a style's text and arrow sizes still read and were typed in
millimetres there: 1/8" text had to be typed as 3.175. CAD letters a drawing
in the drawing's own units, so these now follow the sheet: in Properties and
at the `text` and `dimstyle` prompts, where `5mm` and `1/8"` still mean what
they say. An inch drawing's built-in styles start from round inches near the
metric ones, 1/8" for Standard.

Lettering is still kept in millimetres, and a drawing lettered before keeps
the sizes it was lettered at, whatever its units, so it opens and plots as
it did. Print widths and hatch spacing stay in millimetres.
"""

from __future__ import annotations

import json
import zipfile

import pytest
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox

from serpentine3d.app import MainWindow
from serpentine3d.core.layout import (Layout, LinearDim, TextNote,
                                      annotation_style, default_note_height)
from serpentine3d.core.scene import Scene
from serpentine3d.fileio.native import load_scene, save_scene
from tests.conftest import StubViewport

INCH = 25.4


def _sheet(scene):
    lay = Layout(name="Sheet1")
    scene.layouts.append(lay)
    return lay


def _lettered(scene):
    """A sheet with a dimension on it, which is lettered in Standard."""
    lay = _sheet(scene)
    lay.dims.append(LinearDim(x1=20.0, y1=20.0, x2=70.8, y2=20.0,
                              measures_paper=True))
    return lay


def _saved_by_an_older_release(scene, path):
    """`scene` written as a release before inch lettering wrote it: all of
    it, but no word on which built-in styles its lettering is in."""
    save_scene(scene, str(path))
    with zipfile.ZipFile(path) as z:
        members = {name: z.read(name) for name in z.namelist()}
    doc = json.loads(members["document.json"])
    doc.pop("annot_style_set")
    members["document.json"] = json.dumps(doc).encode()
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


def _opened(path):
    scene = Scene()
    load_scene(scene, str(path))
    return scene


@pytest.mark.parametrize("units", ["in", "ft"])
def test_an_inch_drawing_letters_in_round_inches(units):
    scene = Scene()
    scene.units = units
    inches = {name: {key: round(size / INCH, 9) for key, size in
                     annotation_style(scene, name).items()}
              for name in ("Standard", "Small", "Heading")}
    assert inches == {
        "Standard": {"text_height": 0.125, "arrow_size": 0.09,
                     "dim_offset": 0.3},
        "Small": {"text_height": 0.09, "arrow_size": 0.06, "dim_offset": 0.2},
        "Heading": {"text_height": 0.25, "arrow_size": 0.09, "dim_offset": 0.3},
    }
    assert annotation_style(scene, "")["text_height"] == pytest.approx(
        0.125 * INCH)
    assert default_note_height(scene) == pytest.approx(0.15 * INCH)


@pytest.mark.parametrize("units", ["mm", "cm", "m"])
def test_a_metric_drawing_letters_in_millimetres_as_before(units):
    scene = Scene()
    scene.units = units
    assert annotation_style(scene, "Standard") == {
        "text_height": 3.2, "arrow_size": 2.2, "dim_offset": 8.0}
    assert annotation_style(scene, "Small")["text_height"] == 2.2
    assert annotation_style(scene, "Heading")["text_height"] == 6.0
    assert default_note_height(scene) == 4.0


def test_an_inch_drawing_lettered_before_keeps_its_sizes(tmp_path):
    scene = Scene()
    scene.units = "in"
    _lettered(scene)
    _saved_by_an_older_release(scene, tmp_path / "old.serp")
    old = _opened(tmp_path / "old.serp")
    assert annotation_style(old, "")["text_height"] == 3.2
    assert annotation_style(old, "Heading")["text_height"] == 6.0
    assert default_note_height(old) == 4.0
    _saved_by_an_older_release(scene, tmp_path / "again.serp")
    save_scene(_opened(tmp_path / "again.serp"), str(tmp_path / "again.serp"))
    assert annotation_style(_opened(tmp_path / "again.serp"),
                            "")["text_height"] == 3.2, (
        "saved again, it must still say what it was lettered in")


def test_an_inch_drawing_with_nothing_lettered_yet_takes_inch_styles(tmp_path):
    scene = Scene()
    scene.units = "in"
    _sheet(scene)
    _saved_by_an_older_release(scene, tmp_path / "old.serp")
    assert annotation_style(_opened(tmp_path / "old.serp"),
                            "")["text_height"] == pytest.approx(0.125 * INCH)


def test_a_new_inch_drawing_keeps_its_inch_lettering_through_a_save(tmp_path):
    scene = Scene()
    scene.units = "in"
    _lettered(scene)
    save_scene(scene, str(tmp_path / "new.serp"))
    assert annotation_style(_opened(tmp_path / "new.serp"),
                            "")["text_height"] == pytest.approx(0.125 * INCH)


def test_changing_units_leaves_what_is_lettered_alone(env):
    scene, _sel, _hist, _ctx, proc = env
    _lettered(scene)
    proc.run("units")
    proc.provide_text("in")
    assert scene.units == "in"
    assert annotation_style(scene, "")["text_height"] == 3.2
    assert default_note_height(scene) == 4.0


def test_a_drawing_with_nothing_lettered_takes_the_new_units_styles(env):
    scene, _sel, _hist, _ctx, proc = env
    _sheet(scene)
    proc.run("units")
    proc.provide_text("in")
    assert annotation_style(scene, "")["text_height"] == pytest.approx(
        0.125 * INCH)


def test_the_text_command_takes_its_height_in_the_sheets_units(env):
    scene, _sel, _hist, ctx, proc = env
    scene.units = "in"
    lay = _sheet(scene)
    ctx.viewport = StubViewport(lay.id)
    for answer in ("0.25", "5mm", ""):
        proc.run("text")
        proc.provide_text("2,2")
        proc.provide_text("NOTE")
        assert proc.prompt_text() == "Text height (in) <0.15>"
        proc.provide_text(answer)
        assert not proc.busy
    assert [note.height for note in lay.notes] == pytest.approx(
        [0.25 * INCH, 5.0, 0.15 * INCH])


def test_a_style_is_set_in_the_sheets_units(env):
    scene, _sel, _hist, _ctx, proc = env
    scene.units = "in"
    proc.run("dimstyle")
    proc.provide_text("Big")
    assert proc.prompt_text() == "Text height (in) <0.125>"
    proc.provide_text("0.2")
    assert proc.prompt_text() == "Arrow size (in) <0.09>"
    proc.provide_text('1/8"')
    assert not proc.busy
    assert scene.annot_styles["Big"] == pytest.approx({
        "text_height": 0.2 * INCH, "arrow_size": 0.125 * INCH,
        "dim_offset": 0.3 * INCH})


def test_accepting_a_size_keeps_it_exactly(env):
    """3.2 mm reads 0.126", and Enter must not make it 0.126" of text."""
    scene, _sel, _hist, _ctx, proc = env
    _lettered(scene)
    proc.run("units")
    proc.provide_text("in")
    proc.run("dimstyle")
    proc.provide_text("Standard")
    assert proc.prompt_text() == "Text height (in) <0.126>"
    proc.provide_text("")
    assert proc.prompt_text() == "Arrow size (in) <0.0866>"
    proc.provide_text("")
    assert scene.annot_styles["Standard"] == {
        "text_height": 3.2, "arrow_size": 2.2, "dim_offset": 8.0}


def test_a_metric_sheet_still_asks_in_millimetres(env):
    scene, _sel, _hist, ctx, proc = env
    lay = _sheet(scene)
    ctx.viewport = StubViewport(lay.id)
    proc.run("text")
    proc.provide_text("50,50")
    proc.provide_text("NOTE")
    assert proc.prompt_text() == "Text height (mm) <4.0>"
    proc.provide_text("3.5")
    assert lay.notes[-1].height == 3.5
    proc.run("dimstyle")
    proc.provide_text("Big")
    assert proc.prompt_text() == "Text height (mm) <3.2>"
    proc.cancel()


@pytest.mark.parametrize("units,typed,kept", [("in", "0.001", 0.001),
                                              ("cm", "1mm", 0.1)])
def test_a_length_in_the_model_is_typed_in_its_units_from_a_sheet(
        env, units, typed, kept):
    """The tolerance measures the model, so asked from a sheet it is still
    typed in the document's units, not the sheet's."""
    from serpentine3d.core.tolerance import set_tolerance, tol
    scene, _sel, _hist, ctx, proc = env
    scene.units = units
    ctx.viewport = StubViewport(_sheet(scene).id)
    before = tol()
    try:
        proc.run("tolerance")
        proc.provide_text(typed)
        assert tol() == pytest.approx(kept)
    finally:
        set_tolerance(before)


@pytest.mark.parametrize("units,height", [("in", 0.125 * INCH), ("mm", 3.2)])
def test_the_sheet_index_is_lettered_in_standard_text(env, units, height):
    scene, _sel, _hist, ctx, proc = env
    scene.units = units
    lay = _sheet(scene)
    ctx.viewport = StubViewport(lay.id)
    proc.run("sheetindex")
    proc.provide_text("1,1")
    assert lay.notes[-1].height == pytest.approx(height)


@pytest.fixture
def window():
    made = []

    def make(units):
        """A document in `units` with a sheet open."""
        w = MainWindow()
        w.resize(1200, 800)
        w.scene.units = units
        lay = Layout(name="Sheet1")
        w.scene.layouts.append(lay)
        w.switch_space(lay.id)
        made.append(w)
        return w, lay

    yield make
    for w in made:
        w.mark_saved()
        w.close()


def _pick(w, note):
    """`note` alone picked on its sheet; Properties' cap height box."""
    w.viewport.layout_view.selected = [("note", note)]
    w.viewport.layoutSelectionChanged.emit()
    return w.properties.findChild(QDoubleSpinBox, "text_height")


@pytest.mark.parametrize("units,height,shown,suffix", [
    ("in", 0.25 * INCH, 0.25, " in"),
    ("ft", 0.25 * INCH, 0.25, " in"),
    ("mm", 4.0, 4.0, " mm"),
])
def test_properties_reads_a_notes_cap_height_in_the_sheets_units(
        window, units, height, shown, suffix):
    w, lay = window(units)
    note = TextNote(x=50.0, y=50.0, text="NOTE", height=height)
    lay.notes.append(note)
    w.scene.notify("layouts")
    box = _pick(w, note)
    assert (box.value(), box.suffix()) == (pytest.approx(shown), suffix)
    box.setValue(shown * 2)
    assert note.height == pytest.approx(height * 2)


def test_reformatting_a_note_keeps_its_height_exactly(window):
    """A cap height of 3.2 mm reads 0.126" in the box, and changing the
    alignment must not write 0.126" back."""
    w, lay = window("in")
    plain = TextNote(x=50.0, y=50.0, text="PLAIN", height=3.2)
    styled = TextNote(x=50.0, y=90.0, text="TITLE", style="Heading")
    lay.notes += [plain, styled]
    w.scene.notify("layouts")
    heading = annotation_style(w.scene, "Heading")["text_height"]
    for note in (plain, styled):
        _pick(w, note)
        alignment = w.properties.findChild(QComboBox, "text_alignment")
        alignment.setCurrentIndex(alignment.findData("center"))
    assert (plain.height, plain.alignment) == (3.2, "center")
    assert (styled.height, styled.style, styled.alignment) == (
        heading, "", "center")
