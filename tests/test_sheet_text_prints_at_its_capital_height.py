"""Text on a sheet prints at the height it is given.

Drafting standards and CAD give a text height as the height of the capital
letters, and a note made in the on-screen editor was scaled to that. The
sheet's painter gave the rest of its lettering's height to Qt as the font's
size, its em, which also has room for ascenders, descenders and accents, so
dimension and leader text and a note placed at the `text` prompt printed
capitals about 0.71 as tall as asked: 1/8" text came out 0.09". All of it
now prints its capitals at its height. A drawing saved before prints as it
always did, and the sheet's own fixed text (the title block, scale bar and
revision table) keeps its size in either.
"""

from __future__ import annotations

import json
import math
import zipfile

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetricsF, QImage, QPainter, QPen

from serpentine3d.core.layout import (
    AngularDim, Layout, Leader, LinearDim, RadialDim, TextNote, annotation_at)
from serpentine3d.core.scene import Scene
from serpentine3d.fileio.native import load_scene, save_scene
from serpentine3d.ui import annot_paint

K = 40.0                    # pixels to a paper millimetre
W, H = 2400, 1600           # 60 x 40 mm of paper

TURN = math.radians(17.1)   # an angle whose label has no round figures

# kind: (a new one, the paper window only its text falls in, its text, the
# height it is lettered at, and where the sheet started its baseline before,
# in what ink, how many pixels left). A dimension is in Standard, 3.2 mm in a
# metric drawing; radial and angular ones are lettered at a fixed 3.2 mm.
LETTERED = {
    "note": (
        lambda: TextNote(x=5.0, y=5.0, text="HEH", height=6.0),
        (0.0, 0.0, 60.0, 40.0), "HEH", 6.0, (5.0, 5.0, "INK", 0)),
    "leader": (
        lambda: Leader(points=[[5.0, 5.0], [20.0, 20.0]], text="HEH",
                       height=5.0),
        (21.0, 19.0, 60.0, 40.0), "HEH", 5.0, (21.5, 20.0, "INK", 0)),
    "dimension": (
        lambda: LinearDim(x1=5.0, y1=5.0, x2=55.0, y2=5.0, offset=8.0,
                          text="HEH"),
        (8.0, 14.0, 52.0, 40.0), "HEH", 3.2,
        (30.0, 15.2, "DIM_INK", 3 * int(K))),
    "radial dimension": (
        lambda: RadialDim(cx=5.0, cy=5.0, px=25.0, py=5.0, text="HEH"),
        (29.5, 4.0, 60.0, 40.0), "HEH", 3.2, (30.0, 5.0, "DIM_INK", 0)),
    "angular dimension": (
        lambda: AngularDim(vx=5.0, vy=5.0, x1=25.0, y1=5.0,
                           x2=5.0 + 20.0 * math.cos(TURN),
                           y2=5.0 + 20.0 * math.sin(TURN), radius=15.0),
        (22.6, 7.0, 60.0, 40.0), "17.1°", 3.2,
        (5.0 + 18.0 * math.cos(TURN / 2), 5.0 + 18.0 * math.sin(TURN / 2),
         "DIM_INK", 0)),
}
POOLS = {"note": "notes", "leader": "leaders", "dimension": "dims",
         "radial dimension": "rdims", "angular dimension": "adims"}
PAINTERS = {"note": "draw_note", "leader": "draw_leader",
            "dimension": "draw_lin_dim", "radial dimension": "draw_radial_dim",
            "angular dimension": "draw_angular_dim"}


def _metrics():
    font = QFont("sans")
    font.setPixelSize(2048)
    return QFontMetricsF(font)


def _cap_ratio() -> float:
    """The sheet font's capital height for each unit of its size."""
    return _metrics().capHeight() / 2048


def _in_capitals(text: str) -> float:
    """How tall `text`'s ink is in the sheet's font, in capital heights."""
    metrics = _metrics()
    return metrics.tightBoundingRect(text).height() / metrics.capHeight()


def _render(draw, k=K, size=(W, H)):
    # Qt edges a big glyph a few levels of grey differently the first time
    # it draws it, so everything is drawn twice and the second kept
    for _ in range(2):
        image = QImage(size[0], size[1], QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.white)
        painter = QPainter(image)
        try:
            draw(painter, lambda x, y: (x * k, size[1] - y * k), k)
        finally:
            painter.end()
    return image


def _pixels(image, window):
    """The pixels inside a paper window (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = window
    pixels = np.frombuffer(image.constBits(), np.uint8).reshape(H, W, 4)
    return pixels[round(H - y1 * K):round(H - y0 * K),
                  round(x0 * K):round(x1 * K), :3]


def _ink(image, window=(0.0, 0.0, W / K, H / K)):
    """Paper bbox (x0, y0, x1, y1) of the ink inside a paper window."""
    ys, xs = np.nonzero(np.any(_pixels(image, window) < 200, axis=2))
    assert len(xs), "nothing was drawn there"
    left, top = window[0], window[3]
    return (left + xs.min() / K, top - (ys.max() + 1) / K,
            left + (xs.max() + 1) / K, top - ys.min() / K)


def _drawing_with(kind):
    """A new drawing with one sheet, lettered with one `kind` of thing."""
    scene = Scene()
    lay = Layout(name="Sheet1")
    getattr(lay, POOLS[kind]).append(LETTERED[kind][0]())
    scene.layouts.append(lay)
    return scene


def _painted(kind, scene):
    """The sheet's `kind` of lettering, painted as `scene` letters it."""
    obj, = getattr(scene.layouts[0], POOLS[kind])
    paint = getattr(annot_paint, PAINTERS[kind])
    return _render(lambda p, to_dev, k: paint(p, to_dev, k, obj, scene))


def _text_height(kind, scene) -> float:
    x0, y0, x1, y1 = _ink(_painted(kind, scene), LETTERED[kind][1])
    return y1 - y0


def _saved_before(scene, path):
    """`scene` written as a release before capital heights wrote it: all of
    it, but no word on what its text heights measure."""
    save_scene(scene, str(path))
    with zipfile.ZipFile(path) as z:
        members = {name: z.read(name) for name in z.namelist()}
    doc = json.loads(members["document.json"])
    doc.pop("text_height_measures", None)
    members["document.json"] = json.dumps(doc).encode()
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


def _opened(path):
    scene = Scene()
    load_scene(scene, str(path))
    return scene


@pytest.mark.parametrize("kind", LETTERED)
def test_a_new_drawing_prints_capitals_as_tall_as_their_height(kind):
    _make, _window, text, height, _was = LETTERED[kind]
    assert _text_height(kind, _drawing_with(kind)) == pytest.approx(
        height * _in_capitals(text), abs=0.05), (
        f"a {kind} lettered {height} mm high must print its capitals that "
        f"tall, not the {height * _cap_ratio():.2f} mm a font that size "
        f"gives them")


@pytest.mark.parametrize("kind", LETTERED)
def test_a_drawing_saved_before_prints_its_lettering_as_it_did(kind, tmp_path):
    _make, window, text, height, (x, y, ink, shift) = LETTERED[kind]
    _saved_before(_drawing_with(kind), tmp_path / "old.serp")
    old = _opened(tmp_path / "old.serp")

    def as_it_was(painter, to_dev, k):
        font = QFont("sans")
        font.setPixelSize(max(int(height * k), 4))
        painter.setFont(font)
        painter.setPen(QPen(getattr(annot_paint, ink)))
        tx, ty = to_dev(x, y)
        painter.drawText(int(tx) - shift, int(ty), text)

    assert np.array_equal(_pixels(_painted(kind, old), window),
                          _pixels(_render(as_it_was), window)), (
        f"a {kind} in a drawing saved before must print as it always did")


def test_a_drawing_saved_now_opens_in_capital_heights(tmp_path):
    save_scene(_drawing_with("dimension"), str(tmp_path / "new.serp"))
    opened = _opened(tmp_path / "new.serp")
    assert _text_height("dimension", opened) == pytest.approx(3.2, abs=0.05)


def test_a_drawing_saved_before_prints_as_it_did_after_another_save(tmp_path):
    _saved_before(_drawing_with("dimension"), tmp_path / "old.serp")
    save_scene(_opened(tmp_path / "old.serp"), str(tmp_path / "again.serp"))
    again = _opened(tmp_path / "again.serp")
    assert _text_height("dimension", again) == pytest.approx(
        3.2 * _cap_ratio(), abs=0.05), (
        "saving a drawing from before must not change how it prints")


def test_a_drawing_saved_before_with_nothing_lettered_so_letters_capitals(
        tmp_path):
    """A note from the on-screen editor was at capital height already, so a
    drawing with only those has nothing to keep."""
    scene = Scene()
    lay = Layout(name="Sheet1")
    lay.notes.append(TextNote(x=5.0, y=30.0, text="HEH", height=6.0,
                              font_family="sans"))
    scene.layouts.append(lay)
    _saved_before(scene, tmp_path / "old.serp")
    old = _opened(tmp_path / "old.serp")
    old.layouts[0].dims.append(LETTERED["dimension"][0]())
    assert _text_height("dimension", old) == pytest.approx(3.2, abs=0.05)


def test_undo_and_a_new_drawing_keep_track_of_how_text_is_sized(tmp_path):
    _saved_before(_drawing_with("dimension"), tmp_path / "old.serp")
    scene = _opened(tmp_path / "old.serp")
    before = scene.snapshot()
    scene.clear()
    scene.layouts.append(Layout(name="Sheet1"))
    scene.layouts[0].dims.append(LETTERED["dimension"][0]())
    assert _text_height("dimension", scene) == pytest.approx(3.2, abs=0.05), (
        "a new drawing letters in capital heights")
    scene.restore(before)
    assert _text_height("dimension", scene) == pytest.approx(
        3.2 * _cap_ratio(), abs=0.05), (
        "undoing back into the drawing from before prints it as it did")


def test_dimension_text_is_centred_on_its_dimension():
    scene = Scene()
    lay = Layout(name="Sheet1")
    lay.dims.append(LinearDim(x1=5.0, y1=5.0, x2=55.0, y2=5.0, offset=8.0))
    scene.layouts.append(lay)
    x0, y0, x1, y1 = _ink(_painted("dimension", scene),
                          LETTERED["dimension"][1])
    assert (x0 + x1) / 2 == pytest.approx(30.0, abs=0.15)


def test_the_sheets_own_text_keeps_its_size_either_way(tmp_path):
    def furniture(scene):
        lay = scene.layouts[0]
        lay.paper_w, lay.paper_h, lay.margin = 120.0, 80.0, 5.0
        lay.title_block = {"fields": {"project": "Bracket", "title": "Arm",
                                      "date": "2026-10-25"}}
        lay.revisions = [["A", "2026-10-25", "First issue"]]

        def draw(painter, to_dev, k):
            annot_paint.draw_title_block(painter, to_dev, k, lay, 1, 1, scene)
            annot_paint.draw_revision_table(painter, to_dev, k, lay)
            annot_paint.draw_scale_bar(painter, to_dev, k, 5.0, 60.0, 1.0,
                                       scene)
        return _render(draw, k=20.0)

    _saved_before(_drawing_with("dimension"), tmp_path / "old.serp")
    assert furniture(_drawing_with("dimension")) == furniture(
        _opened(tmp_path / "old.serp")), (
        "the title block, revisions and scale bar print at the sizes they "
        "always did, in a new drawing too")


def test_a_note_is_picked_all_over_its_letters():
    scene = Scene()
    lay = Layout(name="Sheet1")
    note = TextNote(x=5.0, y=5.0, text="QUARTER", height=6.0)
    lay.notes.append(note)
    scene.layouts.append(lay)
    x0, y0, x1, y1 = _ink(_painted("note", scene))
    for x, y in ((x0, y0), (x1, y0), (x0, y1), (x1, y1),
                 ((x0 + x1) / 2, (y0 + y1) / 2)):
        assert annotation_at(lay, x, y, scene=scene) == ("note", note), (
            f"a click on the note's ink at ({x:.1f}, {y:.1f}) must pick it")


def test_a_note_of_two_lines_is_picked_on_its_second_line():
    scene = Scene()
    lay = Layout(name="Sheet1")
    note = TextNote(x=5.0, y=20.0, text="AB\nCD", height=5.0)
    lay.notes.append(note)
    scene.layouts.append(lay)
    x0, y0, x1, y1 = _ink(_painted("note", scene))
    # the second line is 1.6 heights below the first, the lowest ink
    assert annotation_at(lay, x0 + 1.0, y0 + 1.0, tol=0.5,
                         scene=scene) == ("note", note)
