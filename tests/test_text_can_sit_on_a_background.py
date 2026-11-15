"""Text can sit on a patch of the drawing's own colour that hides what lies
behind it, reaching a margin of cap heights past the lettering."""

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QDoubleSpinBox

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import Layout, TextNote, annotation_bounds
from serpentine3d.core.text import TextShape


@pytest.fixture
def window(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "cfg.json"))
    monkeypatch.setenv("SERP3D_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    w = MainWindow()
    w.resize(1200, 850)
    w.show()
    QApplication.processEvents()
    yield w
    w.processor.cancel()
    w._saved_revision = w.scene.revision
    w.close()


def _size(box):
    box = np.asarray(box)
    return (np.linalg.norm(box[1] - box[0]), np.linalg.norm(box[3] - box[0]))


def test_the_background_grows_the_frame_by_its_margin():
    plain = TextShape("Label", 10.)
    backed = plain.with_background(True, 0.5)
    (w0, h0), (w1, h1) = _size(plain.frame_box()), _size(backed.frame_box())
    assert w1 == pytest.approx(w0 + 10.) and h1 == pytest.approx(h0 + 10.)
    ends = [p for p, kind in backed.snap_points() if kind == "end"]
    np.testing.assert_allclose(backed.frame_box(), ends)


def test_a_margin_without_a_background_changes_nothing():
    plain = TextShape("Label", 10.)
    np.testing.assert_allclose(plain.with_background(False, 2.).frame_box(),
                               plain.frame_box())


def test_the_background_survives_moving_editing_and_saving():
    backed = TextShape("Label", 10.).with_background(True, 0.4)
    moved = g.apply_matrix(backed, np.diag([2., 2., 2., 1.]))
    for text in (moved, backed.edited(text="Other"),
                 TextShape.from_bytes(backed.to_bytes()), backed.copy()):
        assert (text.background, text.margin) == (True, 0.4)


def test_text_saved_before_backgrounds_has_none():
    import json
    import struct
    from serpentine3d.core.text_object import TEXT_TAG
    data = TextShape("Old", 5.).to_bytes()
    start = len(TEXT_TAG)
    size, = struct.unpack("<I", data[start:start + 4])
    header = json.loads(data[start + 4:start + 4 + size])
    header.pop("look")
    raw = json.dumps(header).encode()
    old = (TEXT_TAG + struct.pack("<I", len(raw)) + raw
           + data[start + 4 + size:])
    text = TextShape.from_bytes(old)
    assert text.background is False


def test_properties_switches_and_widens_the_background(window):
    obj = window.scene.add(TextShape("Label", 10.))
    window.selection.set([obj.id])
    QApplication.processEvents()
    toggle = window.properties.findChild(QCheckBox, "text_background")
    margin = window.properties.findChild(QDoubleSpinBox, "text_margin")
    assert toggle.isVisible() and not toggle.isChecked()
    assert not margin.isEnabled(), "a margin means nothing without one"

    toggle.setChecked(True)
    margin.setValue(0.6)
    shape = window.scene.get(obj.id).shape
    assert (shape.background, shape.margin) == (True, pytest.approx(0.6))
    assert margin.isEnabled()

    window.history.undo()
    assert window.scene.get(obj.id).shape.background is False, (
        "switching the background is one undo step")


def test_a_note_can_have_a_background_too(window):
    layout = Layout(name="Sheet")
    window.scene.layouts.append(layout)
    note = TextNote(x=50., y=70., text="Note", height=4.,
                    font_family="Arial")
    layout.notes.append(note)
    plain = annotation_bounds("note", note)
    note.background, note.margin = True, 0.5
    backed = annotation_bounds("note", note)
    assert backed[0] == pytest.approx(plain[0] - 2.)
    assert backed[3] == pytest.approx(plain[3] + 2.)


# -- the file -----------------------------------------------------------------

def _saved(scene, tmp_path):
    import json
    import zipfile

    from serpentine3d.fileio import native
    path = str(tmp_path / "masked.serp")
    native.save_scene(scene, path)
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("document.json")), path


def _note(**look):
    lay = Layout(name="Sheet")
    lay.notes.append(TextNote(text="NOTE", x=20, y=20, height=4, **look))
    return lay


@pytest.mark.parametrize("where", ["model", "sheet"])
def test_a_drawing_with_a_text_background_asks_for_the_release_that_keeps_it(
        tmp_path, monkeypatch, where):
    """0.12.5 opens such a drawing and drops the background without a word,
    so a save there loses it: the file asks for 0.13.0."""
    from serpentine3d.core.scene import Scene
    from serpentine3d.fileio import native
    scene = Scene()
    if where == "model":
        scene.add(TextShape("MASK", 5.0).with_background(True))
    else:
        scene.layouts.append(_note(background=True))
    doc, path = _saved(scene, tmp_path)
    assert (doc["version"], doc["requires"]) == (9, "0.13.0")
    monkeypatch.setattr(native, "FORMAT_VERSION", 8)
    with pytest.raises(ValueError, match=r"0\.13\.0"):
        native.load_scene(Scene(), path)


def test_text_without_a_background_is_written_as_before(tmp_path):
    from serpentine3d.core.scene import Scene
    scene = Scene()
    scene.add(TextShape("PLAIN", 5.0))
    scene.layouts.append(_note())
    doc, _path = _saved(scene, tmp_path)
    assert doc["version"] <= 8 and doc.get("requires") != "0.13.0"
