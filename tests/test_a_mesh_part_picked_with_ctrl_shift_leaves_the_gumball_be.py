"""Ctrl+Shift and a click on a mesh picks one of its faces or edges. The
gumball, which turns into a push/pull handle for a Brep's face or edge,
has nothing to take hold of on a mesh, and leaves it be: the click used to
end in an error out of the mouse press, which took the app down."""

from __future__ import annotations

import sys

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.mesh import MeshShape


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    win = MainWindow()
    win.resize(1200, 800)
    win.show()
    QApplication.processEvents()
    yield win
    win.processor.cancel()
    win.mark_saved()
    win.close()
    QApplication.processEvents()


def _hill():
    # a square with its middle raised: four triangles round a peak
    points = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0],
                       [5, 5, 4]], float)
    return MeshShape(points, [[0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4]])


def test_a_mesh_has_no_brep_faces_or_edges_to_give():
    for shape in (_hill(), MeshShape(np.zeros((0, 3)), np.zeros((0, 3)))):
        assert g.faces_of(shape) == [] and g.edges_of(shape) == []
    box = g.make_box((0, 0, 0), 1, 1, 1)
    assert len(g.faces_of(box)) == 6 and len(g.edges_of(box)) == 12


def test_ctrl_shift_and_a_click_on_a_mesh_picks_a_part_without_an_error(
        win, monkeypatch):
    errors = []
    monkeypatch.setattr(sys, "excepthook",
                        lambda kind, value, tb: errors.append(value))
    win.scene.add(_hill())
    QApplication.processEvents()
    vp = win.viewports[0] if hasattr(win, "viewports") else win.viewport
    w, h = vp.width(), vp.height()
    held = (Qt.KeyboardModifier.ControlModifier
            | Qt.KeyboardModifier.ShiftModifier)
    x, y, _depth = vp._eye().project(np.array([(5, 2.5, 2)], float), w, h)[0]
    QTest.mouseClick(vp, Qt.MouseButton.LeftButton, held,
                     QPoint(int(x), int(y)))
    QApplication.processEvents()
    assert errors == []
    [(_oid, kind, _index)] = vp.selection.subobjects    # picked
    assert kind == "face"
    assert vp.gumball._pushpull_target() is None   # nothing to push or pull
