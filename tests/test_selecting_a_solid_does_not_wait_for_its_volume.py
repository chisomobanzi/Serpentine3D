"""Picking something does not stop to measure it.

Clicking a solid took about half a second on a real drawing. Almost none
of that was drawing: the repaint is 6ms and the hit test under 1ms. It
was Properties working out the exact volume and surface area of whatever
you had just picked, on the interface thread, before the click could
finish. On the openNURBS clip model one solid costs 86 to 486ms, and it
was paid again every single time, even for an object measured a moment
earlier.

So the measurement waits until the selection settles, and what it found
is remembered until the drawing changes. Everything else about the
object still appears at once.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication

from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.properties import PropertiesPanel


@pytest.fixture
def panel(qapp_or_none):
    scene = Scene()
    selection = SelectionManager(scene)
    p = PropertiesPanel(scene, selection, History(scene))
    p.measure_delay_ms = 0          # fire on the next pass of the event loop
    try:
        yield p, scene, selection
    finally:
        # a panel left with a measurement armed would fire it inside the
        # next test and be counted there
        p._measure_timer.stop()
        p.deleteLater()
        QApplication.processEvents()


@pytest.fixture(scope="session")
def qapp_or_none():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def counted(monkeypatch):
    """Count the expensive calls, and keep them honest."""
    calls = []
    for name in ("volume", "surface_area"):
        real = getattr(g, name)

        def wrapped(shape, _real=real, _name=name):
            calls.append(_name)
            return _real(shape)

        monkeypatch.setattr(g, name, wrapped)
    return calls


def _boxes(scene, n=3):
    return [scene.add(g.make_box((i * 20, 0, 0), 10, 10, 10), name=f"Box {i}")
            for i in range(n)]


def _settle():
    QApplication.processEvents()
    QApplication.processEvents()


def test_the_click_itself_does_not_measure_anything(panel, counted):
    p, scene, sel = panel
    box = _boxes(scene, 1)[0]

    sel.set([box.id])

    assert counted == [], "measuring is what made the click slow"
    assert p.measure_label.text() != "", "the row cannot go blank meanwhile"


def test_everything_cheap_about_the_object_is_there_at_once(panel, counted):
    p, scene, sel = panel
    box = _boxes(scene, 1)[0]

    sel.set([box.id])

    assert p.header.text() == "Box 0"
    assert p.kind_label.text() == "Solid"
    assert counted == []


def test_the_measurement_lands_once_the_selection_settles(panel, counted):
    p, scene, sel = panel
    box = _boxes(scene, 1)[0]
    sel.set([box.id])

    _settle()

    assert counted, "a selection you rest on does get measured"
    text = p.measure_label.text()
    assert "Volume" in text and "1000.000" in text
    assert "Area" in text and "600.000" in text


def test_clicking_through_objects_measures_none_of_them(panel, counted):
    p, scene, sel = panel
    boxes = _boxes(scene, 3)

    for box in boxes:                       # no settling in between
        sel.set([box.id])

    assert counted == [], (
        "a selection that is already gone must not be measured")


def test_an_object_measured_once_is_not_measured_again(panel, counted):
    p, scene, sel = panel
    a, b = _boxes(scene, 2)
    sel.set([a.id]); _settle()
    first = len(counted)
    assert first

    sel.set([b.id]); _settle()
    sel.set([a.id]); _settle()

    assert len(counted) == first * 2, (
        "the second look at the first box should come from memory")
    assert "1000.000" in p.measure_label.text()


def test_changing_the_drawing_makes_it_measure_again(panel, counted):
    p, scene, sel = panel
    box = _boxes(scene, 1)[0]
    sel.set([box.id]); _settle()
    before = len(counted)

    scene.replace_shape(box.id, g.make_box((0, 0, 0), 20, 10, 10))
    sel.set([])
    sel.set([box.id]); _settle()

    assert len(counted) > before, "a changed shape is a different measurement"
    assert "2000.000" in p.measure_label.text()


def test_a_curve_still_reads_its_length_straight_away(panel, counted):
    p, scene, sel = panel
    line = scene.add(g.make_line((0, 0, 0), (10, 0, 0)), name="Line")

    sel.set([line.id])

    assert "Length" in p.measure_label.text(), (
        "a length is cheap, so there is nothing to wait for")
    assert counted == []


def test_selecting_nothing_leaves_no_measurement_pending(panel, counted):
    p, scene, sel = panel
    box = _boxes(scene, 1)[0]
    sel.set([box.id])
    sel.set([])

    _settle()

    assert counted == []
    assert p.measure_label.text() == "—"
