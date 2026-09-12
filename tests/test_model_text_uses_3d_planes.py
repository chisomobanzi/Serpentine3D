"""Model lettering can sit naturally on planes throughout a 3D model."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QPlainTextEdit, QPushButton

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as g
from serpentine3d.core.cplane import CPlane
from serpentine3d.core.text import TextShape
from serpentine3d.script_runtime import fingerprint


@pytest.fixture
def window():
    w = MainWindow()
    w.resize(1200, 850)
    w.show()
    QApplication.processEvents()
    yield w
    w.processor.cancel()
    w.hide()


def _placement_control(window):
    combo = window.findChild(QComboBox, "text_placement_plane")
    assert combo is not None and combo.isVisible() and combo.isEnabled(), (
        "Creating or editing model text must expose its placement plane")
    offered = {combo.itemText(i).replace("&", "").strip().lower()
               for i in range(combo.count())}
    assert offered == {"cplane", "selected face", "view plane"}
    return combo


def _choose(combo, label):
    index = next((i for i in range(combo.count())
                  if combo.itemText(i).replace("&", "").strip().lower()
                  == label.lower()), -1)
    assert index >= 0
    combo.setCurrentIndex(index)
    QApplication.processEvents()


def _write_text_at(window, anchor, text="Room label"):
    window.processor.provide(anchor)
    QApplication.processEvents()
    editor = window.viewport.findChild(QPlainTextEdit, "model_text_content")
    assert editor is not None and editor.isVisible(), (
        "Picking the anchor must begin direct editing in the viewport")
    editor.setPlainText(text)
    QApplication.processEvents()
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    QApplication.processEvents()
    obj, = [o for o in window.scene.all() if isinstance(o.shape, TextShape)]
    return obj


def _text_frame(obj):
    frame = np.asarray(obj.shape._frame, dtype=float)
    assert frame.shape == (4, 4)
    return frame


@pytest.mark.parametrize("placement", ["CPlane", "View plane"])
def test_new_model_text_uses_the_plane_chosen_in_the_contextual_ui(
        window, placement):
    cplane = CPlane(origin=(3., 5., 7.), normal=(0., -1., 0.),
                    xdir=(1., 0., 0.))
    window.viewport.cplane = cplane
    camera = window.viewport.camera
    camera.azimuth = np.radians(38.)
    camera.elevation = np.radians(24.)
    camera.target = np.asarray((8., 9., 10.))
    camera.distance = 140.

    window.processor.run("textobject")
    combo = _placement_control(window)
    _choose(combo, placement)
    if placement == "CPlane":
        anchor = (20., 5., 30.)
        expected = np.column_stack((cplane.xdir, cplane.ydir, cplane.normal))
    else:
        anchor = (20., 30., 40.)
        right, up = camera.right_up()
        normal = camera.position - camera.target
        normal /= np.linalg.norm(normal)
        expected = np.column_stack((right, up, normal))

    obj = _write_text_at(window, anchor)
    frame = _text_frame(obj)
    np.testing.assert_allclose(frame[:3, 3], anchor, atol=1e-7)
    np.testing.assert_allclose(frame[:3, :3], expected, atol=1e-7)


def test_selected_face_placement_uses_a_held_planar_face_and_asks_when_missing(
        window):
    window.processor.run("textobject")
    combo = _placement_control(window)
    _choose(combo, "Selected face")
    assert "face" in window.processor.request.prompt.lower(), (
        "With no held face, Selected face must ask the user to pick one")
    window.processor.cancel()

    box = window.scene.add(g.make_box((0., 0., 0.), 20., 15., 10.))
    faces = g.faces_of(box.shape)
    face_index = next(i for i, face in enumerate(faces)
                      if np.dot(g.face_normal(face), (0., 0., 1.)) > .999)
    face_normal = g.face_normal(faces[face_index])
    window.selection.set([box.id])
    window.selection.toggle_subobject(box.id, "face", face_index)

    window.processor.run("textobject")
    combo = _placement_control(window)
    _choose(combo, "Selected face")
    anchor = (4., 6., 10.)
    obj = _write_text_at(window, anchor, "On the face")
    frame = _text_frame(obj)
    np.testing.assert_allclose(frame[:3, 3], anchor, atol=1e-7)
    assert np.dot(frame[:3, 2], face_normal) > .999999, (
        "The text front must be the selected planar face's front")


def test_look_at_text_is_a_reversible_camera_only_action(window):
    normal = np.asarray((1., 2., 3.), dtype=float)
    normal /= np.linalg.norm(normal)
    xdir = np.cross((0., 0., 1.), normal)
    xdir /= np.linalg.norm(xdir)
    plane = CPlane(origin=(12., 18., 24.), normal=normal, xdir=xdir)
    shape = g.apply_matrix(TextShape("Angled label", 6.),
                           plane.basis_matrix())
    obj = window.scene.add(shape, name="Angled label")

    camera = window.viewport.camera
    camera.set_standard_view("front")
    camera.target = np.asarray((-10., 4., 2.))
    camera.distance = 175.
    before_camera = camera.state()
    before_shape = obj.shape.to_bytes()
    before_scene = fingerprint(window.scene.snapshot())
    before_history = list(window.history._undo)

    window.selection.set([obj.id])
    QApplication.processEvents()
    _placement_control(window)
    button = window.findChild(QPushButton, "look_at_text")
    assert button is not None and button.isVisible() and button.isEnabled(), (
        "Selecting angled editable text must expose Look at text")

    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert camera.state() != before_camera
    text_origin = _text_frame(obj)[:3, 3]
    toward_camera = camera.position - text_origin
    toward_camera /= np.linalg.norm(toward_camera)
    assert np.dot(toward_camera, normal) > .999999, (
        "Look at text must put the camera squarely in front of its plane")
    assert window.scene.get(obj.id).shape.to_bytes() == before_shape
    assert fingerprint(window.scene.snapshot()) == before_scene
    assert window.history._undo == before_history

    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    QApplication.processEvents()
    assert camera.state() == before_camera, (
        "The same contextual action must restore the previous view")
    assert window.scene.get(obj.id).shape.to_bytes() == before_shape
    assert fingerprint(window.scene.snapshot()) == before_scene
    assert window.history._undo == before_history
