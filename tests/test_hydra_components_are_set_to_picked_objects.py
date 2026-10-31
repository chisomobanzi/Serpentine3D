"""Hydra in the real window: a geometry component is set to objects picked
in the model, shows them in the preview, and follows them when they change."""

from __future__ import annotations

import numpy as np
import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFont, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QWidget

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as geo
from serpentine3d.core import hydra
from serpentine3d.core.hydra import Graph
from serpentine3d.core.mesh import mesh_from_brep


@pytest.fixture
def win(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    win = MainWindow()
    win.resize(1400, 900)
    yield win
    win.processor.cancel()
    win.mark_saved()
    win.close()
    QApplication.processEvents()


def _lines(port):
    """A port's tooltip, line by line."""
    return port.toolTip().splitlines()


def _set_to(win, editor, node, objs):
    """Set Crv... (or the like) from the component's menu, then click
    and press Enter."""
    menu = editor.node_menu(editor.canvas.node_items[node.id])
    [action] = [a for a in menu.actions()
                if a.text() == node.component.sets + "..."]
    action.trigger()
    assert win.processor.busy
    for obj in objs:
        win.processor.click_object(obj.id)
    win.processor.finish_selection()


def test_the_command_opens_hydra_floating_and_the_menu_names_it(win):
    win.run_command("hydra")
    assert win.hydra is not None
    assert win._hydra_dock.isFloating() and win._hydra_dock.isVisible()
    labels = [a.text() for m in win.menuBar().actions() if m.menu()
              for a in m.menu().actions()]
    assert "Hydra" in labels


def test_the_add_menu_offers_the_geometries_with_their_icons(win):
    editor = win.show_hydra()
    actions = [a for a in editor.component_menu(None).actions()
               if not a.isSeparator()]
    assert [a.text() for a in actions] == [
        "Point", "Curve", "Brep", "Mesh", "Boolean Toggle",
        "Geometry Pipeline", "Panel", "Number Slider", "Addition",
        "Subtraction", "Multiplication", "Division", "Series", "Range",
        "Random", "Round", "List Item", "Remove Item", "Concatenate",
        "Text Tag", "Construct Point", "Vector", "Unit X", "Unit Y", "Unit Z",
        "Deconstruct Point", "Contour", "Point On Curve", "Move", "Rotate",
        "Group", "Ungroup", "Delaunay Mesh"]
    assert all(not a.icon().isNull() for a in actions)


def test_set_to_takes_the_picked_curves_and_previews_them(win):
    editor = win.show_hydra()
    line = win.scene.add(geo.make_line((0, 0, 0), (10, 0, 0)))
    circle = win.scene.add(geo.make_circle((0, 0, 0), 3))
    node = editor.add_component("curve", (0, 0))
    editor.solve()
    assert editor.results[node.id].status == "warning"
    _set_to(win, editor, node, [line, circle])
    assert not win.processor.busy
    assert node.params["refs"] == [line.id, circle.id]
    assert editor.results[node.id].status == "ok"
    assert editor.canvas.node_items[node.id].summary() == "2 curves"
    assert len(win.scene.hydra_preview[1])
    assert len(win.scene.all()) == 2           # picking adds nothing


def test_set_to_only_takes_objects_of_the_components_kind(win):
    editor = win.show_hydra()
    box = win.scene.add(geo.make_box((0, 0, 0), 1, 1, 1))
    line = win.scene.add(geo.make_line((0, 0, 0), (10, 0, 0)))
    node = editor.add_component("curve", (0, 0))
    _set_to(win, editor, node, [box, line])
    assert node.params["refs"] == [line.id]


def test_a_brep_takes_surfaces_and_solids_and_a_mesh_only_meshes(win):
    editor = win.show_hydra()
    face = win.scene.add(geo.planar_face(
        geo.make_rectangle((0, 0, 0), (2, 2, 0))))
    box = win.scene.add(geo.make_box((5, 0, 0), 1, 1, 1))
    mesh = win.scene.add(mesh_from_brep(geo.make_box((9, 0, 0), 1, 1, 1)))
    brep = editor.add_component("brep", (0, 0))
    meshes = editor.add_component("mesh", (0, 120))
    _set_to(win, editor, brep, [face, box, mesh])
    _set_to(win, editor, meshes, [face, box, mesh])
    assert brep.params["refs"] == [face.id, box.id]
    assert meshes.params["refs"] == [mesh.id]
    assert editor.canvas.node_items[meshes.id].summary() == "1 mesh"
    assert win.scene.hydra_preview is not None


def _choose_set_to(editor, node):
    menu = editor.node_menu(editor.canvas.node_items[node.id])
    [a for a in menu.actions() if a.text() == "Set Crv..."][0].trigger()


def test_set_to_takes_what_is_already_selected_straight_away(win):
    editor = win.show_hydra()
    line = win.scene.add(geo.make_line((0, 0, 0), (10, 0, 0)))
    circle = win.scene.add(geo.make_circle((0, 0, 0), 3))
    node = editor.add_component("curve", (0, 0))
    win.selection.set([line.id, circle.id])
    _choose_set_to(editor, node)
    assert not win.processor.busy
    assert node.params["refs"] == [line.id, circle.id]


def test_set_to_takes_only_the_selected_objects_of_its_kind(win):
    editor = win.show_hydra()
    line = win.scene.add(geo.make_line((0, 0, 0), (10, 0, 0)))
    box = win.scene.add(geo.make_box((0, 0, 0), 1, 1, 1))
    node = editor.add_component("curve", (0, 0))
    win.selection.set([line.id, box.id])
    _choose_set_to(editor, node)
    assert not win.processor.busy
    assert node.params["refs"] == [line.id]


def test_with_nothing_of_its_kind_selected_set_to_waits_for_a_pick(win):
    editor = win.show_hydra()
    box = win.scene.add(geo.make_box((0, 0, 0), 1, 1, 1))
    line = win.scene.add(geo.make_line((0, 0, 0), (10, 0, 0)))
    node = editor.add_component("curve", (0, 0))
    win.selection.set([box.id])
    _choose_set_to(editor, node)
    assert win.processor.busy
    win.processor.click_object(line.id)
    win.processor.finish_selection()
    assert node.params["refs"] == [line.id]


def test_escape_leaves_the_component_as_it_was(win):
    editor = win.show_hydra()
    line = win.scene.add(geo.make_line((0, 0, 0), (10, 0, 0)))
    node = editor.add_component("curve", (0, 0))
    _set_to(win, editor, node, [line])
    menu = editor.node_menu(editor.canvas.node_items[node.id])
    [a for a in menu.actions() if a.text() == "Set Crv..."][0].trigger()
    win.processor.cancel()
    assert node.params["refs"] == [line.id]


def test_the_component_follows_its_objects_when_they_move_or_go(win):
    editor = win.show_hydra()
    line = win.scene.add(geo.make_line((0, 0, 0), (10, 0, 0)))
    node = editor.add_component("curve", (0, 0))
    _set_to(win, editor, node, [line])
    line.shape = geo.translate(line.shape, (0, 5, 0))
    win.scene.notify("objects")
    editor.solve()
    assert win.scene.hydra_preview[1][:, 1].min() == pytest.approx(5.0)
    win.scene.remove(line.id)
    editor.solve()
    assert editor.results[node.id].status == "warning"
    assert win.scene.hydra_preview is None


def test_closing_hydra_takes_its_preview_away_and_reopening_brings_it_back(win):
    win.show()
    editor = win.show_hydra()
    box = win.scene.add(geo.make_box((0, 0, 0), 1, 1, 1))
    editor.set_references(editor.add_component("brep", (0, 0)).id, [box.id])
    win._hydra_dock.close()
    QApplication.processEvents()
    assert win.scene.hydra_preview is None
    win.show_hydra()
    QApplication.processEvents()
    assert win.scene.hydra_preview is not None


def test_delete_removes_the_selected_component_not_the_models_selection(win):
    win.show()
    editor = win.show_hydra()
    obj = win.scene.add(geo.make_box((0, 0, 0), 1, 1, 1))
    win.selection.set([obj.id])
    node = editor.add_component("brep", (0, 0))
    editor.canvas.node_items[node.id].setSelected(True)
    editor.canvas.setFocus()
    QApplication.processEvents()
    QTest.keyClick(editor.canvas, Qt.Key.Key_Delete)
    assert node.id not in editor.graph.nodes
    assert win.scene.get(obj.id) is not None


def _right(view, kind, at, held):
    event = QMouseEvent(kind, QPointF(at), QPointF(view.mapToGlobal(at)),
                        Qt.MouseButton.RightButton
                        if kind != QEvent.Type.MouseMove
                        else Qt.MouseButton.NoButton,
                        Qt.MouseButton.RightButton if held
                        else Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(view.viewport(), event)


@pytest.fixture
def menus(win, monkeypatch):
    shown = []
    editor = win.show_hydra()
    monkeypatch.setattr(editor, "show_menu",
                        lambda scene_pos, screen_pos: shown.append(scene_pos))
    win.show()
    QApplication.processEvents()
    return editor, shown


def test_dragging_with_the_right_button_pans_and_opens_no_menu(menus):
    editor, shown = menus
    view = editor.canvas
    before = view.mapToScene(view.viewport().rect().center())
    start = view.viewport().rect().center()
    _right(view, QEvent.Type.MouseButtonPress, start, True)
    for step in range(1, 6):
        _right(view, QEvent.Type.MouseMove, start + QPoint(20 * step, 0), True)
    _right(view, QEvent.Type.MouseButtonRelease, start + QPoint(100, 0), False)
    after = view.mapToScene(view.viewport().rect().center())
    assert after.x() == pytest.approx(before.x() - 100, abs=2)
    assert shown == []


def test_a_right_click_without_dragging_opens_the_menu(menus):
    editor, shown = menus
    view = editor.canvas
    at = view.viewport().rect().center()
    _right(view, QEvent.Type.MouseButtonPress, at, True)
    _right(view, QEvent.Type.MouseMove, at + QPoint(1, 1), True)
    _right(view, QEvent.Type.MouseButtonRelease, at + QPoint(1, 1), False)
    assert len(shown) == 1


# -- the number slider ------------------------------------------------------

def _menu_texts(menu):
    # the name field at the top is a widget, not an entry with text
    return [a.text() for a in menu.actions()
            if not a.isSeparator() and a.text()]


def test_a_sliders_menu_offers_change_range_with_decimal_places_below(win):
    editor = win.show_hydra()
    node = editor.add_component("slider", (0, 0))
    menu = editor.node_menu(editor.canvas.node_items[node.id])
    texts = _menu_texts(menu)
    assert texts[:2] == ["Change Range...", "Decimal Places"]
    places = [a for a in menu.actions() if a.text() == "Decimal Places"][0]
    choices = places.menu().actions()
    assert [a.text() for a in choices] == [str(n) for n in range(7)]
    assert [a.isChecked() for a in choices].index(True) == 2


def test_choosing_decimal_places_changes_what_the_slider_shows(win):
    editor = win.show_hydra()
    node = editor.add_component("slider", (0, 0))
    item = editor.canvas.node_items[node.id]
    menu = editor.node_menu(item)
    places = [a for a in menu.actions() if a.text() == "Decimal Places"][0]
    places.menu().actions()[0].trigger()
    assert node.params["decimals"] == 0
    assert item.value_text() == "5"
    editor.set_decimals(item, 3)
    assert item.value_text() == "5.000"


def test_change_range_takes_a_typed_range_with_its_decimals(win, monkeypatch):
    from serpentine3d.ui.hydra import fields
    editor = win.show_hydra()
    node = editor.add_component("slider", (0, 0))
    item = editor.canvas.node_items[node.id]

    def typed(dialog):
        dialog.low.setText("0,125")
        dialog.high.setText("2,5")
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(fields.RangeDialog, "exec", typed)
    editor.change_range(item)
    assert (node.params["min"], node.params["max"]) == (0.125, 2.5)
    assert node.params["decimals"] == 3
    assert node.params["value"] == 2.5
    assert item.value_text() == "2.500"


def test_the_range_dialog_will_not_take_a_range_that_is_not_one(win):
    from PySide6.QtWidgets import QDialogButtonBox
    from serpentine3d.ui.hydra.fields import RangeDialog
    editor = win.show_hydra()
    node = editor.add_component("slider", (0, 0))
    dialog = RangeDialog(node.params, editor)
    ok = dialog.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert dialog.low.text() == "0.00" and dialog.high.text() == "10.00"
    assert ok.isEnabled()
    dialog.high.setText("-1")
    assert not ok.isEnabled() and "below" in dialog.hint.text()
    dialog.high.setText("zehn")
    assert not ok.isEnabled()
    dialog.high.setText("12,75")
    assert ok.isEnabled()


def test_dragging_the_knob_sets_the_value_to_the_sliders_decimals(win):
    win.show()
    editor = win.show_hydra()
    node = editor.add_component("slider", (0, 0))
    item = editor.canvas.node_items[node.id]
    view = editor.canvas
    view.centerOn(item)
    QApplication.processEvents()
    x0, x1 = item._rail()
    y = item.boundingRect().center().y()
    start = view.mapFromScene(item.mapToScene(QPointF(x0, y)))
    end = view.mapFromScene(item.mapToScene(QPointF(x0 + (x1 - x0) * 0.3, y)))
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=start)
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=end)
    assert node.params["value"] == pytest.approx(3.0, abs=0.1)
    assert node.params["value"] == round(node.params["value"], 2)
    assert (node.x, node.y) == (0, 0)          # the knob moved, not the node
    editor.solve()
    assert editor.results[node.id].outputs["Number"] == [node.params["value"]]


def _double_click_slider(win, editor, node):
    win.show()
    # as after a click into it: the Hydra window is the active one
    win._hydra_dock.activateWindow()
    item = editor.canvas.node_items[node.id]
    view = editor.canvas
    view.centerOn(item)
    QApplication.processEvents()
    at = view.mapFromScene(item.mapToScene(item.value_rect().center()))
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=at)
    QApplication.processEvents()
    assert editor.value_field is not None and editor.value_field.isVisible()
    assert editor.value_field.hasFocus()
    return item, editor.value_field


def test_double_clicking_a_slider_types_a_value_into_it(win):
    editor = win.show_hydra()
    node = editor.add_component("slider", (0, 0))
    item, field = _double_click_slider(win, editor, node)
    assert field.text() == "5.00"
    field.setText("7,25")
    QTest.keyClick(field, Qt.Key.Key_Return)
    QApplication.processEvents()
    assert editor.value_field is None
    assert node.params == {"value": 7.25, "min": 0.0, "max": 10.0,
                           "decimals": 2}
    assert item.value_text() == "7.25"


def test_typing_a_range_into_a_slider_sets_its_range_and_decimals(win):
    editor = win.show_hydra()
    node = editor.add_component("slider", (0, 0))
    item, field = _double_click_slider(win, editor, node)
    field.setText("0.0-12")
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert (node.params["min"], node.params["max"]) == (0.0, 12.0)
    assert node.params["decimals"] == 1
    assert item.value_text() == "5.0"


def test_escape_leaves_the_slider_as_it_was(win):
    editor = win.show_hydra()
    node = editor.add_component("slider", (0, 0))
    _item, field = _double_click_slider(win, editor, node)
    field.setText("9")
    QTest.keyClick(field, Qt.Key.Key_Escape)
    QApplication.processEvents()
    assert editor.value_field is None
    assert node.params["value"] == 5.0


def test_something_that_is_no_number_keeps_the_field_open_to_fix_it(win):
    editor = win.show_hydra()
    node = editor.add_component("slider", (0, 0))
    _item, field = _double_click_slider(win, editor, node)
    field.setText("zwölf")
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert editor.value_field is field
    assert "0.0-12" in editor.status.text()
    field.setText("3")
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert node.params["value"] == 3.0


def test_clicking_elsewhere_keeps_what_was_typed(win):
    editor = win.show_hydra()
    node = editor.add_component("slider", (0, 0))
    _item, field = _double_click_slider(win, editor, node)
    field.setText("2")
    editor.canvas.setFocus()
    QApplication.processEvents()
    assert editor.value_field is None
    assert node.params["value"] == 2.0


def test_dragging_a_wire_from_an_output_draws_no_selection_box(win):
    win.show()
    editor = win.show_hydra()
    node = editor.add_component("slider", (0, 0))
    view = editor.canvas
    view.centerOn(editor.canvas.node_items[node.id])
    QApplication.processEvents()
    port = view.node_items[node.id].port("Number", True)
    start = view.mapFromScene(port.scenePos())

    def send(kind, at, button, held):
        QApplication.sendEvent(view.viewport(), QMouseEvent(
            kind, QPointF(at), QPointF(view.mapToGlobal(at)), button, held,
            Qt.KeyboardModifier.NoModifier))

    left = Qt.MouseButton.LeftButton
    send(QEvent.Type.MouseButtonPress, start, left, left)
    for step in range(1, 6):
        send(QEvent.Type.MouseMove, start + QPoint(25 * step, 15 * step),
             Qt.MouseButton.NoButton, left)
        assert view.rubberBandRect().isEmpty()
    end = start + QPoint(125, 75)
    send(QEvent.Type.MouseButtonRelease, end, left, Qt.MouseButton.NoButton)
    assert view.rubberBandRect().isEmpty()


# -- rotate -----------------------------------------------------------------

def _wire_by_mouse(editor, source, output, target, input):
    view = editor.canvas
    out = view.node_items[source.id].port(output, True)
    inp = view.node_items[target.id].port(input, False)
    a = view.mapFromScene(out.scenePos())
    b = view.mapFromScene(inp.scenePos())
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=a)
    QTest.mouseMove(view.viewport(), (a + b) / 2)
    QTest.mouseMove(view.viewport(), b)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, pos=b)


def test_a_rotate_has_a_port_and_a_name_for_each_input(win):
    editor = win.show_hydra()
    node = editor.add_component("rotate", (0, 0))
    item = editor.canvas.node_items[node.id]
    ys = [p.y() for p in item.inputs]
    assert [p.port.name for p in item.inputs] == ["Origin", "Geometry",
                                                   "Angle"]
    assert ys == sorted(ys) and min(b - a for a, b in zip(ys, ys[1:])) >= 16
    assert all(0 < y < item.height for y in ys)
    assert item.outputs[0].y() == pytest.approx(item.height / 2)


def test_curves_wired_into_rotate_preview_turned(win):
    win.show()
    editor = win.show_hydra()
    line = win.scene.add(geo.make_line((1, 0, 0), (2, 0, 0)))
    curve = editor.add_component("curve", (-200, 0))
    rotate = editor.add_component("rotate", (40, -20))
    editor.set_references(curve.id, [line.id])
    curve_item = editor.canvas.node_items[curve.id]
    editor.set_preview(curve.id, False)
    editor.canvas.centerOn(0, 0)
    QApplication.processEvents()
    _wire_by_mouse(editor, curve, "Curve", rotate, "Geometry")
    assert [(w.source, w.input) for w in editor.graph.wires] == [
        (curve.id, "Geometry")]
    angle = editor.add_component("slider", (-200, 120))
    angle.params.update(value=90.0, max=360.0)
    editor.connect(angle.id, "Number", rotate.id, "Angle")
    editor.solve()
    assert editor.results[rotate.id].status == "ok"
    segs = win.scene.hydra_preview[1]
    assert segs[:, 0] == pytest.approx(0, abs=1e-6)
    assert sorted(segs[:, 1]) == pytest.approx([1, 2], abs=1e-6)
    assert curve_item.result.status == "ok"


def test_an_inputs_tooltip_shows_what_reaches_it_now(win):
    editor = win.show_hydra()
    slider = editor.add_component("slider", (-300, 0))
    rotate = editor.add_component("rotate", (40, -20))
    editor.solve()
    angle = editor.canvas.node_items[rotate.id].port("Angle", False)
    assert _lines(angle) == ["Number", "Default · 1 item", "", "[0] 0"]
    editor.connect(slider.id, "Number", rotate.id, "Angle")
    editor.solve()
    assert _lines(angle) == ["Number", "1 item", "", "[0] 5"]
    editor.canvas.node_items[slider.id].slide_to(10_000)
    editor.solve()
    assert _lines(angle) == ["Number", "1 item", "", "[0] 10"]
    geometry = editor.canvas.node_items[rotate.id].port("Geometry", False)
    assert _lines(geometry) == ["Geometry", "Nothing connected"]


def test_a_waiting_components_input_names_are_drawn_white(win):
    from serpentine3d.ui.hydra import style
    editor = win.show_hydra()
    rotate = editor.add_component("rotate", (0, 0))
    editor.solve()
    item = editor.canvas.node_items[rotate.id]
    assert item.result.status == "warning"
    pens = []

    class Spy:
        def __getattr__(self, name):
            return lambda *a, **k: None

        def setPen(self, pen):
            pens.append(pen)

        def font(self):
            return QFont()
    item._paint_labels(Spy())
    assert QColor(pens[0]) == style.TEXT


def test_a_slider_dropped_on_rotates_geometry_is_turned_away_and_says_why(win):
    win.show()
    editor = win.show_hydra()
    slider = editor.add_component("slider", (-300, 0))
    rotate = editor.add_component("rotate", (40, -20))
    editor.canvas.centerOn(-60, 0)
    QApplication.processEvents()
    _wire_by_mouse(editor, slider, "Number", rotate, "Geometry")
    assert editor.graph.wires == []
    assert "takes geometry" in editor.status.text()
    _wire_by_mouse(editor, slider, "Number", rotate, "Angle")
    assert [w.input for w in editor.graph.wires] == ["Angle"]


def test_the_graph_is_there_again_after_a_restart(win):
    editor = win.show_hydra()
    editor.add_component("curve", (0, 0))
    editor.add_component("mesh", (0, 120))
    win.mark_saved()
    win.close()
    again = MainWindow()
    try:
        editor = again.show_hydra()
        assert sorted(n.key for n in editor.graph.nodes.values()) == [
            "curve", "mesh"]
    finally:
        again.mark_saved()
        again.close()


def test_sliding_an_angle_turns_the_preview_without_meshing_it_again(
        win, monkeypatch):
    from serpentine3d.ui.hydra import preview
    meshed = []
    real = preview._mesh_arrays
    monkeypatch.setattr(preview, "_mesh_arrays",
                        lambda shape: meshed.append(shape) or real(shape))
    editor = win.show_hydra()
    box = win.scene.add(geo.make_box((1, 0, 0), 1, 1, 1))
    brep = editor.add_component("brep", (-200, 0))
    editor.set_references(brep.id, [box.id])
    slider = editor.add_component("slider", (-200, 80))
    slider.params.update(max=360.0)
    rotate = editor.add_component("rotate", (60, 0))
    editor.connect(brep.id, "Brep", rotate.id, "Geometry")
    editor.connect(slider.id, "Number", rotate.id, "Angle")
    editor.solve()
    first = len(meshed)
    item = editor.canvas.node_items[slider.id]
    before = win.scene.hydra_preview[0].copy()
    for x in range(60, 200, 20):
        item.slide_to(x)
        editor.solve()
    assert len(meshed) == first
    assert not np.allclose(win.scene.hydra_preview[0], before)


# -- a graph saved and opened again ------------------------------------------

def test_a_saved_graph_opens_with_its_links_to_a_reopened_model(
        win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from serpentine3d.fileio.native import save_scene
    editor = win.show_hydra()
    line = win.scene.add(geo.make_line((1, 0, 0), (2, 0, 0)))
    origin = win.scene.add(geo.make_point((1, 0, 0)))
    curve = editor.add_component("curve", (-200, 0))
    point = editor.add_component("point", (-200, -60))
    slider = editor.add_component("slider", (-200, 80))
    rotate = editor.add_component("rotate", (60, 0))
    editor.set_references(curve.id, [line.id])
    editor.set_references(point.id, [origin.id])
    slider.params.update(value=90.0, max=360.0)
    editor.connect(point.id, "Point", rotate.id, "Origin")
    editor.connect(curve.id, "Curve", rotate.id, "Geometry")
    editor.connect(slider.id, "Number", rotate.id, "Angle")
    model, graph = tmp_path / "model.serp", tmp_path / "graph.hydra"
    save_scene(win.scene, str(model))
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *a, **k: (str(graph), ""))
    editor.save_graph()
    win.mark_saved()
    win.close()

    again = MainWindow()
    try:
        again._open_path(str(model))
        editor = again.show_hydra()
        editor.new_graph()
        monkeypatch.setattr(QFileDialog, "getOpenFileName",
                            lambda *a, **k: (str(graph), ""))
        editor.open_graph()
        assert len(editor.graph.wires) == 3
        assert all(r.status == "ok" for r in editor.results.values())
        turned = editor.results[rotate.id].outputs["Geometry"][0]
        from serpentine3d.core.tessellate import tessellate
        pts = tessellate(turned).edge_segments.reshape(-1, 3)
        assert pts[:, 0] == pytest.approx([1, 1], abs=1e-6)
        assert sorted(pts[:, 1]) == pytest.approx([0, 1], abs=1e-6)
    finally:
        again.mark_saved()
        again.close()


def test_a_slider_dragged_without_a_pause_updates_while_it_moves(win):
    editor = win.show_hydra()
    solves = []
    real = editor.solve
    editor._timer.timeout.disconnect()
    editor._timer.timeout.connect(lambda: solves.append(1) or real())
    for _ in range(20):
        editor.changed()
        QTest.qWait(5)
    QTest.qWait(30)
    assert len(solves) >= 3


# -- save into the graph's own file -------------------------------------------

@pytest.fixture
def dialogs(monkeypatch, tmp_path):
    """Counts the file dialogs, answering each with `answer`."""
    from PySide6.QtWidgets import QFileDialog
    asked = {"save": 0, "open": 0, "answer": str(tmp_path / "graph.hydra")}

    def save(*a, **k):
        asked["save"] += 1
        return asked["answer"], ""

    def open_(*a, **k):
        asked["open"] += 1
        return asked["answer"], ""
    monkeypatch.setattr(QFileDialog, "getSaveFileName", save)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", open_)
    return asked


def _saved_keys(path):
    import json
    with open(path, encoding="utf-8") as fh:
        return sorted(n["key"] for n in json.load(fh)["nodes"])


def test_save_asks_where_only_the_first_time(win, dialogs):
    editor = win.show_hydra()
    editor.add_component("curve", (0, 0))
    editor.save_graph()
    assert dialogs["save"] == 1
    editor.add_component("slider", (0, 80))
    editor.save_graph()
    assert dialogs["save"] == 1
    assert _saved_keys(dialogs["answer"]) == ["curve", "slider"]
    assert win._hydra_dock.windowTitle() == "Hydra · graph.hydra"


def test_a_graph_opened_from_a_file_saves_back_into_it(win, dialogs, tmp_path):
    editor = win.show_hydra()
    editor.add_component("curve", (0, 0))
    editor.save_graph()
    editor.new_graph()
    assert win._hydra_dock.windowTitle() == "Hydra"
    editor.open_graph()
    editor.add_component("rotate", (100, 0))
    editor.save_graph()
    assert dialogs["save"] == 1
    assert _saved_keys(dialogs["answer"]) == ["curve", "rotate"]


def test_save_as_always_asks_and_saves_from_then_on_into_the_new_file(
        win, dialogs, tmp_path):
    editor = win.show_hydra()
    editor.add_component("curve", (0, 0))
    editor.save_graph()
    dialogs["answer"] = str(tmp_path / "copy.hydra")
    editor.save_graph_as()
    assert dialogs["save"] == 2
    editor.add_component("mesh", (0, 80))
    editor.save_graph()
    assert dialogs["save"] == 2
    assert _saved_keys(tmp_path / "copy.hydra") == ["curve", "mesh"]
    assert _saved_keys(tmp_path / "graph.hydra") == ["curve"]


def test_a_new_graph_or_a_file_gone_missing_asks_again(win, dialogs):
    import os
    editor = win.show_hydra()
    editor.save_graph()
    editor.new_graph()
    editor.save_graph()
    assert dialogs["save"] == 2
    os.remove(dialogs["answer"])
    editor.save_graph()
    assert dialogs["save"] == 3


def test_the_graphs_file_is_still_its_file_after_a_restart(win, dialogs):
    editor = win.show_hydra()
    editor.save_graph()
    win.mark_saved()
    win.close()
    again = MainWindow()
    try:
        editor = again.show_hydra()
        assert again._hydra_dock.windowTitle() == "Hydra · graph.hydra"
        editor.add_component("curve", (0, 0))
        editor.save_graph()
        assert dialogs["save"] == 1
        assert _saved_keys(dialogs["answer"]) == ["curve"]
    finally:
        again.mark_saved()
        again.close()


# -- vector -----------------------------------------------------------------

def _set_vector(win, editor, node, a, b):
    menu = editor.node_menu(editor.canvas.node_items[node.id])
    [action] = [x for x in menu.actions() if x.text() == "Set Vector..."]
    action.trigger()
    assert win.processor.busy
    win.processor.provide_text(",".join(str(c) for c in a))
    ghost = win.processor.request.preview_fn(b)
    win.processor.provide_text(",".join(str(c) for c in b))
    return ghost


def test_set_vector_takes_two_points_picked_in_the_model(win):
    editor = win.show_hydra()
    node = editor.add_component("vector", (0, 0))
    editor.solve()
    assert editor.results[node.id].status == "warning"
    ghost = _set_vector(win, editor, node, (1, 0, 0), (1, 3, 0))
    assert not win.processor.busy
    assert geo.shape_kind(ghost) == "curve"          # the arrow, while picking
    assert node.params["set"] == {"A": [1.0, 0.0, 0.0], "B": [1.0, 3.0, 0.0]}
    assert editor.results[node.id].status == "ok"
    [v] = editor.results[node.id].outputs["Vector"]
    assert v.components == (0, 3, 0)
    item = editor.canvas.node_items[node.id]
    assert _lines(item.port("B", False)) == [
        "Point", "Set in the model · 1 item", "", "[0] Point 1, 3, 0"]
    assert item.summary() == "1 vector"
    segs = win.scene.hydra_preview[1]
    assert segs[:, 1].max() == pytest.approx(3.0)
    assert len(win.scene.all()) == 0                  # setting adds nothing


def test_escape_while_setting_a_vector_keeps_the_one_it_had(win):
    editor = win.show_hydra()
    node = editor.add_component("vector", (0, 0))
    _set_vector(win, editor, node, (0, 0, 0), (2, 0, 0))
    menu = editor.node_menu(editor.canvas.node_items[node.id])
    [x for x in menu.actions() if x.text() == "Set Vector..."][0].trigger()
    win.processor.provide_text("5,5,5")
    win.processor.cancel()
    assert node.params["set"]["B"] == [2.0, 0.0, 0.0]


def test_only_a_vector_offers_set_vector(win):
    editor = win.show_hydra()
    for key in ("construct_point", "rotate", "slider", "curve"):
        node = editor.add_component(key, (0, 0))
        texts = [a.text() for a in
                 editor.node_menu(editor.canvas.node_items[node.id]).actions()]
        assert "Set Vector..." not in texts


def test_construct_point_has_x_y_z_inputs_that_default_to_zero(win):
    editor = win.show_hydra()
    node = editor.add_component("construct_point", (0, 0))
    editor.solve()
    item = editor.canvas.node_items[node.id]
    assert [_lines(p) for p in item.inputs] == [
        ["Number", "Default · 1 item", "", "[0] 0"]] * 3
    assert editor.results[node.id].status == "ok"
    assert len(win.scene.hydra_preview[2]) == 1        # one point shown


# -- the logo ----------------------------------------------------------------

def test_hydra_sits_at_the_foot_of_the_tool_strip_with_its_logo(win):
    from PySide6.QtWidgets import QToolButton
    win.resize(1400, 700)                  # shorter than the tools need
    win.show()
    QApplication.processEvents()
    bar = win._tools_toolbar
    host = bar.findChild(QWidget, "hydraButton")
    button = host.findChild(QToolButton)
    assert not button.icon().isNull()
    assert "Hydra" in button.toolTip()
    bottom = host.mapTo(bar, QPoint(0, host.height())).y()
    assert bar.height() - bottom <= 8
    strip = bar.findChild(QWidget, "toolStrip")
    assert strip.mapTo(bar, QPoint(0, 0)).y() < host.mapTo(bar, QPoint(0, 0)).y()
    button.click()
    assert win._hydra_dock is not None and win._hydra_dock.isVisible()


def test_the_logo_is_hydras_window_icon(win):
    win.show_hydra()
    assert not win._hydra_dock.windowIcon().isNull()


def test_a_hydra_file_handed_to_the_app_opens_in_hydra(win, tmp_path):
    import json
    from serpentine3d.app import _open_launch_args
    path = tmp_path / "launched.hydra"
    graph = {"nodes": [{"id": "a", "key": "curve"}], "wires": []}
    path.write_text(json.dumps(graph), encoding="utf-8")
    box = win.scene.add(geo.make_box((0, 0, 0), 1, 1, 1))
    _open_launch_args(win, [str(path)])
    assert win._hydra_dock.isVisible()
    assert list(win.hydra.graph.nodes) == ["a"]
    assert win.hydra.path == str(path)
    assert [o.id for o in win.scene.all()] == [box.id]    # model untouched


def test_opening_a_hydra_file_as_a_document_opens_it_in_hydra(win, tmp_path):
    import json
    path = tmp_path / "graph.hydra"
    path.write_text(json.dumps({"nodes": [{"id": "b", "key": "mesh"}]}),
                    encoding="utf-8")
    box = win.scene.add(geo.make_box((0, 0, 0), 1, 1, 1))
    win._open_path(str(path))
    assert list(win.hydra.graph.nodes) == ["b"]
    assert win.scene.get(box.id) is not None


# -- copy, paste and Alt-drag -------------------------------------------------

def _shown(win):
    win.show()
    editor = win.show_hydra()
    win._hydra_dock.activateWindow()
    QApplication.processEvents()
    return editor


def test_ctrl_c_and_ctrl_v_copy_the_selected_components(win):
    editor = _shown(win)
    curve = editor.add_component("curve", (0, 0))
    rotate = editor.add_component("rotate", (200, 0))
    editor.connect(curve.id, "Curve", rotate.id, "Geometry")
    box = win.scene.add(geo.make_box((0, 0, 0), 1, 1, 1))
    win.selection.set([box.id])
    editor.canvas.scene().clearSelection()
    for nid in (curve.id, rotate.id):
        editor.canvas.node_items[nid].setSelected(True)
    editor.canvas.setFocus()
    QTest.keyClick(editor.canvas, Qt.Key.Key_C,
                   Qt.KeyboardModifier.ControlModifier)
    QTest.keyClick(editor.canvas, Qt.Key.Key_V,
                   Qt.KeyboardModifier.ControlModifier)
    assert sorted(n.key for n in editor.graph.nodes.values()) == [
        "curve", "curve", "rotate", "rotate"]
    assert len(editor.graph.wires) == 2
    pasted = set(editor.selected_ids())
    assert len(pasted) == 2 and not pasted & {curve.id, rotate.id}
    # the model was left alone by the keys
    assert len(win.scene.all()) == 1 and win.selection.ids == [box.id]


def test_pasting_twice_makes_two_copies(win):
    editor = _shown(win)
    node = editor.add_component("slider", (0, 0))
    editor.canvas.node_items[node.id].setSelected(True)
    editor.copy_selected()
    editor.paste()
    editor.paste()
    assert [n.key for n in editor.graph.nodes.values()] == ["slider"] * 3


def test_alt_dragging_a_component_pulls_a_copy_off_it(win):
    editor = _shown(win)
    curve = editor.add_component("curve", (0, 0))
    rotate = editor.add_component("rotate", (220, 0))
    editor.connect(curve.id, "Curve", rotate.id, "Geometry")
    view = editor.canvas
    view.centerOn(100, 0)
    QApplication.processEvents()
    item = view.node_items[rotate.id]
    start = view.mapFromScene(item.mapToScene(
        QPointF(item.width * 0.6, item.height / 2)))
    end = start + QPoint(0, 120)
    alt = Qt.KeyboardModifier.AltModifier
    QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, alt, start)
    QTest.mouseMove(view.viewport(), start + QPoint(0, 60))
    QTest.mouseMove(view.viewport(), end)
    QTest.mouseRelease(view.viewport(), Qt.MouseButton.LeftButton, alt, end)
    assert (rotate.x, rotate.y) == (220, 0)          # the original stayed
    [copy] = [n for n in editor.graph.nodes.values()
              if n.key == "rotate" and n.id != rotate.id]
    assert copy.x == pytest.approx(220, abs=2)
    assert copy.y == pytest.approx(120 / view.transform().m11(), abs=3)
    # the wire from outside stays with the original
    assert [w.target for w in editor.graph.wires] == [rotate.id]


def _drag_wire(view, start_scene, end_scene, check=None):
    a = view.mapFromScene(start_scene)
    b = view.mapFromScene(end_scene)
    left = Qt.MouseButton.LeftButton

    def send(kind, at, button, held):
        QApplication.sendEvent(view.viewport(), QMouseEvent(
            kind, QPointF(at), QPointF(view.mapToGlobal(at)), button, held,
            Qt.KeyboardModifier.NoModifier))
    send(QEvent.Type.MouseButtonPress, a, left, left)
    send(QEvent.Type.MouseMove, (a + b) / 2, Qt.MouseButton.NoButton, left)
    send(QEvent.Type.MouseMove, b, Qt.MouseButton.NoButton, left)
    if check is not None:
        check()
    send(QEvent.Type.MouseButtonRelease, b, left, Qt.MouseButton.NoButton)


def test_a_wire_docks_on_an_input_it_ends_near_and_lights_it_first(win):
    editor = _shown(win)
    slider = editor.add_component("slider", (-300, 0))
    rotate = editor.add_component("rotate", (40, -20))
    view = editor.canvas
    view.centerOn(-60, 0)
    QApplication.processEvents()
    out = view.node_items[slider.id].port("Number", True)
    angle = view.node_items[rotate.id].port("Angle", False)
    near = angle.scenePos() + QPointF(-14, 7)        # beside it, not on it
    seen = []
    _drag_wire(view, out.scenePos(), near,
               lambda: seen.append(angle._hover))
    assert seen == [True]
    assert not angle._hover                          # put out once docked
    assert [(w.source, w.input) for w in editor.graph.wires] == [
        (slider.id, "Angle")]


def test_a_wire_let_go_on_a_component_docks_on_the_input_that_takes_it(win):
    editor = _shown(win)
    curve = editor.add_component("curve", (-300, 0))
    slider = editor.add_component("slider", (-300, 120))
    rotate = editor.add_component("rotate", (40, -20))
    view = editor.canvas
    view.centerOn(-60, 40)
    QApplication.processEvents()
    item = view.node_items[rotate.id]
    middle = item.mapToScene(QPointF(item.width * 0.7, 4))   # top of the body
    _drag_wire(view, view.node_items[curve.id].port("Curve", True).scenePos(),
               middle)
    _drag_wire(view, view.node_items[slider.id].port("Number", True).scenePos(),
               middle)
    assert sorted((editor.graph.nodes[w.source].key, w.input)
                  for w in editor.graph.wires) == [
        ("curve", "Geometry"), ("slider", "Angle")]


def test_a_port_can_be_caught_a_little_way_off_its_dot(win):
    editor = _shown(win)
    slider = editor.add_component("slider", (0, 0))
    view = editor.canvas
    view.centerOn(100, 0)
    QApplication.processEvents()
    out = view.node_items[slider.id].port("Number", True)
    found = view.scene()._port_at(out.scenePos() + QPointF(8, 6))
    assert found is out


# -- the search on the canvas -------------------------------------------------

def _listed(search):
    return [search.list.item(i).text() for i in range(search.list.count())]


def test_double_clicking_the_canvas_opens_a_search_to_type_into(win):
    editor = _shown(win)
    view = editor.canvas
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton,
                      pos=view.viewport().rect().center())
    QApplication.processEvents()
    search = editor.search
    assert search is not None and search.isVisible()
    assert search.field.hasFocus()
    assert _listed(search) == ["Point", "Curve", "Brep", "Mesh",
                               "Number Slider"]
    search.close()


def test_a_right_click_on_the_canvas_opens_the_same_search(win):
    from serpentine3d.ui.hydra.fields import ComponentSearch
    editor = _shown(win)
    editor.show_menu(QPointF(0, 0), QPoint(200, 200))
    assert isinstance(editor.search, ComponentSearch)
    assert editor.search.isVisible()
    editor.search.close()


def test_typing_hides_the_components_that_do_not_fit(win):
    editor = _shown(win)
    search = editor.find_component(QPointF(0, 0), QPoint(200, 200))
    QTest.keyClicks(search.field, "rot")
    assert _listed(search) == ["Rotate"]
    search.field.clear()
    QTest.keyClicks(search.field, "point")
    assert _listed(search) == ["Point", "Point On Curve", "Construct Point",
                               "Deconstruct Point"]
    search.field.clear()
    QTest.keyClicks(search.field, "crv")
    assert _listed(search) == ["Curve"]
    search.close()


def test_enter_adds_the_chosen_component_where_the_canvas_was_clicked(win):
    editor = _shown(win)
    search = editor.find_component(QPointF(120, 80), QPoint(200, 200))
    QTest.keyClicks(search.field, "point")
    QTest.keyClick(search.field, Qt.Key.Key_Down)
    QTest.keyClick(search.field, Qt.Key.Key_Return)
    [node] = editor.graph.nodes.values()
    assert node.key == "point_on_curve"
    assert (node.x, node.y) == (120, 80)
    assert not search.isVisible()


def test_a_click_on_a_listed_component_adds_it(win):
    editor = _shown(win)
    search = editor.find_component(QPointF(0, 0), QPoint(200, 200))
    item = search.list.item(1)
    rect = search.list.visualItemRect(item)
    QTest.mouseClick(search.list.viewport(), Qt.MouseButton.LeftButton,
                     pos=rect.center())
    assert [n.key for n in editor.graph.nodes.values()] == ["curve"]


def test_escape_closes_the_search_and_adds_nothing(win):
    editor = _shown(win)
    search = editor.find_component(QPointF(0, 0), QPoint(200, 200))
    QTest.keyClicks(search.field, "rot")
    QTest.keyClick(search.field, Qt.Key.Key_Escape)
    assert not search.isVisible()
    assert editor.graph.nodes == {}


def test_the_toolbar_still_lists_every_component(win):
    editor = win.show_hydra()
    titles = [a.text() for a in editor.component_menu(None).actions()
              if not a.isSeparator()]
    assert "Rotate" in titles and "Vector" in titles


# -- where Hydra opens ------------------------------------------------------

def test_hydra_opens_where_it_was_docked_last_time(win):
    win.show()
    win.show_hydra()
    dock = win._hydra_dock
    dock.setFloating(False)
    win.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
    QApplication.processEvents()
    win.mark_saved()
    win.close()
    for opens in (False, True):           # a session without Hydra between
        again = MainWindow()
        try:
            again.show()
            QApplication.processEvents()
            if opens:
                again.show_hydra()
                QApplication.processEvents()
                assert not again._hydra_dock.isFloating()
                assert again.dockWidgetArea(again._hydra_dock) == (
                    Qt.DockWidgetArea.LeftDockWidgetArea)
        finally:
            again.mark_saved()
            again.close()


def test_hydra_floats_where_it_floated_last_time(win):
    win.show()
    win.show_hydra()
    dock = win._hydra_dock
    dock.setFloating(True)
    dock.setGeometry(140, 160, 720, 430)
    QApplication.processEvents()
    size = dock.size()
    win.mark_saved()
    win.close()
    again = MainWindow()
    try:
        again.show()
        again.show_hydra()
        QApplication.processEvents()
        assert again._hydra_dock.isFloating()
        assert again._hydra_dock.size() == size
    finally:
        again.mark_saved()
        again.close()


def test_the_first_time_hydra_opens_floating(win):
    win.show()
    win.show_hydra()
    assert win._hydra_dock.isFloating()


def test_a_vector_wired_into_move_moves_the_preview(win):
    editor = win.show_hydra()
    line = win.scene.add(geo.make_line((0, 0, 0), (1, 0, 0)))
    curve = editor.add_component("curve", (-300, 0))
    editor.set_references(curve.id, [line.id])
    editor.set_preview(curve.id, False)
    vector = editor.add_component("vector", (-300, 100))
    editor.set_inputs(vector.id, {"A": (0, 0, 0), "B": (0, 3, 0)})
    editor.set_preview(vector.id, False)
    move = editor.add_component("move", (0, 0))
    editor.connect(curve.id, "Curve", move.id, "G")
    editor.connect(vector.id, "Vector", move.id, "V")
    editor.solve()
    segs = win.scene.hydra_preview[1]
    assert segs[:, 1] == pytest.approx(3.0)
    item = editor.canvas.node_items[move.id]
    assert [p.port.name for p in item.inputs] == ["G", "V"]
    assert _lines(item.port("V", False)) == [
        "Vector", "1 item", "", "[0] Vector 0, 3, 0"]


# -- cast ---------------------------------------------------------------------

def _menu_action(editor, node, text):
    menu = editor.node_menu(editor.canvas.node_items[node.id])
    found = [a for a in menu.actions() if a.text() == text]
    return found[0] if found else None


def _rotated_lines(win, editor, count=2):
    lines = [win.scene.add(geo.make_line((1 + i, 0, 0), (2 + i, 0, 0)))
             for i in range(count)]
    curve = editor.add_component("curve", (-300, 0))
    editor.set_references(curve.id, [l.id for l in lines])
    angle = editor.add_component("slider", (-300, 100))
    angle.params.update(value=90.0, max=360.0)
    rotate = editor.add_component("rotate", (0, 0))
    editor.connect(curve.id, "Curve", rotate.id, "Geometry")
    editor.connect(angle.id, "Number", rotate.id, "Angle")
    editor.solve()
    return lines, curve, angle, rotate


def _answer_cast(monkeypatch, layer=None, group=None, seen=None):
    from serpentine3d.ui.hydra import fields

    def answer(dialog):
        if seen is not None:
            seen.append(dialog)
        if layer is not None:
            dialog.layers.setCurrentIndex(dialog.layers.findData(layer))
        if group is not None:
            dialog.group.setChecked(group)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(fields.CastDialog, "exec", answer)


def test_cast_is_in_the_menu_of_components_that_make_geometry(win):
    editor = win.show_hydra()
    lines, curve, angle, rotate = _rotated_lines(win, editor)
    for node in (curve, rotate):
        assert _menu_action(editor, node, "Cast...") is not None
    for key in ("slider", "vector"):
        node = editor.add_component(key, (0, 200))
        assert _menu_action(editor, node, "Cast...") is None


def test_cast_is_greyed_out_while_a_component_makes_nothing(win):
    editor = win.show_hydra()
    rotate = editor.add_component("rotate", (0, 0))
    editor.solve()
    assert not _menu_action(editor, rotate, "Cast...").isEnabled()


def test_cast_adds_what_the_component_makes_onto_the_chosen_layer(
        win, monkeypatch):
    editor = win.show_hydra()
    lines, curve, angle, rotate = _rotated_lines(win, editor)
    layer_id = win.scene.layers.create("Hydra output").id
    assert layer_id != win.scene.layers.current_id
    _answer_cast(monkeypatch, layer=layer_id, group=False)
    _menu_action(editor, rotate, "Cast...").trigger()
    new = [o for o in win.scene.all() if o.id not in {l.id for l in lines}]
    assert len(new) == 2
    assert {o.layer_id for o in new} == {layer_id}
    assert {o.kind for o in new} == {"curve"}
    assert all(o.group_id is None for o in new)
    assert sorted(win.selection.ids) == sorted(o.id for o in new)
    # turned as the preview showed them, and the model's own lines untouched
    from serpentine3d.core.tessellate import tessellate
    for obj in new:
        pts = tessellate(obj.shape).edge_segments.reshape(-1, 3)
        assert pts[:, 0] == pytest.approx(0, abs=1e-6)
    for line in lines:
        pts = tessellate(line.shape).edge_segments.reshape(-1, 3)
        assert pts[:, 1] == pytest.approx(0, abs=1e-6)


def test_cast_can_group_its_objects(win, monkeypatch):
    editor = win.show_hydra()
    lines, curve, angle, rotate = _rotated_lines(win, editor, count=3)
    _answer_cast(monkeypatch, group=True)
    objects = editor.cast(rotate.id)
    assert len(objects) == 3
    groups = {win.scene.get(o.id).group_id for o in objects}
    assert len(groups) == 1 and None not in groups


def test_the_group_box_only_shows_for_more_than_one_object(win, monkeypatch):
    editor = win.show_hydra()
    seen = []
    _answer_cast(monkeypatch, seen=seen)
    lines, curve, angle, rotate = _rotated_lines(win, editor, count=1)
    editor.cast(rotate.id)
    assert not seen[-1].group.isVisibleTo(seen[-1])
    more, curve2, angle2, rotate2 = _rotated_lines(win, editor, count=2)
    editor.cast(rotate2.id)
    assert seen[-1].group.isVisibleTo(seen[-1])
    assert "2 objects" in seen[-1].group.text()


def test_the_dialog_offers_every_layer_and_starts_on_the_current_one(win):
    from serpentine3d.ui.hydra.fields import CastDialog
    editor = win.show_hydra()
    layers = win.scene.layers
    dialog = CastDialog(layers, 2, False, editor)
    offered = [dialog.layers.itemData(i) for i in range(dialog.layers.count())]
    assert offered == [layer.id for layer in layers.all()]
    assert dialog.layer_id() == layers.current_id


def test_a_cast_is_one_undo_step(win, monkeypatch):
    editor = win.show_hydra()
    lines, curve, angle, rotate = _rotated_lines(win, editor, count=3)
    _answer_cast(monkeypatch, group=True)
    editor.cast(rotate.id)
    assert len(win.scene.all()) == 6
    win.history.undo()
    assert sorted(o.id for o in win.scene.all()) == sorted(l.id for l in lines)


def test_cancelling_the_dialog_casts_nothing(win, monkeypatch):
    from serpentine3d.ui.hydra import fields
    editor = win.show_hydra()
    lines, curve, angle, rotate = _rotated_lines(win, editor)
    monkeypatch.setattr(fields.CastDialog, "exec",
                        lambda dialog: QDialog.DialogCode.Rejected)
    assert editor.cast(rotate.id) == []
    assert len(win.scene.all()) == 2


def test_cast_objects_stay_put_when_the_graph_changes(win, monkeypatch):
    editor = win.show_hydra()
    lines, curve, angle, rotate = _rotated_lines(win, editor, count=1)
    _answer_cast(monkeypatch)
    [cast] = editor.cast(rotate.id)
    before = cast.shape
    editor.canvas.node_items[angle.id].slide_to(10)
    editor.solve()
    assert win.scene.get(cast.id).shape is before


def test_casting_with_several_components_selected_casts_them_all(
        win, monkeypatch):
    editor = win.show_hydra()
    lines, curve, angle, rotate = _rotated_lines(win, editor, count=1)
    move = editor.add_component("move", (0, 150))
    editor.connect(rotate.id, "Geometry", move.id, "G")
    editor.solve()
    for node in (rotate, move):
        editor.canvas.node_items[node.id].setSelected(True)
    _answer_cast(monkeypatch)
    assert len(editor.cast(move.id)) == 2


def test_cast_remembers_whether_to_group(win, monkeypatch):
    editor = win.show_hydra()
    seen = []
    lines, curve, angle, rotate = _rotated_lines(win, editor, count=2)
    _answer_cast(monkeypatch, group=True, seen=seen)
    editor.cast(rotate.id)
    _answer_cast(monkeypatch, seen=seen)
    editor.cast(rotate.id)
    assert seen[-1].group.isChecked()


@pytest.mark.parametrize("key, label", [
    ("point", "Set Pt..."), ("curve", "Set Crv..."), ("brep", "Set Brep..."),
    ("mesh", "Set Mesh..."), ("vector", "Set Vector..."),
])
def test_each_component_names_what_it_is_set_to(win, key, label):
    editor = win.show_hydra()
    node = editor.add_component(key, (0, 0))
    texts = [a.text() for a in
             editor.node_menu(editor.canvas.node_items[node.id]).actions()]
    assert label in texts and "Set to..." not in texts


# -- hide ---------------------------------------------------------------------

def _two_breps(win, editor):
    boxes = [win.scene.add(geo.make_box((3 * i, 0, 0), 1, 1, 1))
             for i in range(2)]
    nodes = []
    for i, box in enumerate(boxes):
        node = editor.add_component("brep", (0, 80 * i))
        editor.set_references(node.id, [box.id])
        nodes.append(node)
    editor.solve()
    return boxes, nodes


def test_hide_in_the_menu_takes_a_component_out_of_the_viewports(win):
    editor = win.show_hydra()
    boxes, (a, b) = _two_breps(win, editor)
    full = len(win.scene.hydra_preview[0])
    _menu_action(editor, a, "Hide").trigger()
    editor.solve()
    assert not a.preview and b.preview
    assert 0 < len(win.scene.hydra_preview[0]) < full
    assert editor.canvas.node_items[a.id].is_hidden()
    # and the menu offers to show it again
    _menu_action(editor, a, "Show").trigger()
    editor.solve()
    assert a.preview and len(win.scene.hydra_preview[0]) == full


def test_ctrl_h_hides_the_selection_and_ctrl_shift_h_shows_it(win):
    editor = _shown(win)
    boxes, (a, b) = _two_breps(win, editor)
    for node in (a, b):
        editor.canvas.node_items[node.id].setSelected(True)
    editor.canvas.setFocus()
    ctrl = Qt.KeyboardModifier.ControlModifier
    shift = Qt.KeyboardModifier.ShiftModifier
    QTest.keyClick(editor.canvas, Qt.Key.Key_H, ctrl)
    editor.solve()
    assert not a.preview and not b.preview
    assert win.scene.hydra_preview is None
    # a second Ctrl+H hides, it does not show
    QTest.keyClick(editor.canvas, Qt.Key.Key_H, ctrl)
    assert not a.preview and not b.preview
    QTest.keyClick(editor.canvas, Qt.Key.Key_H, ctrl | shift)
    editor.solve()
    assert a.preview and b.preview
    # the model kept its own objects visible: the keys were Hydra's here
    assert all(win.scene.get(box.id).visible for box in boxes)


def test_ctrl_shift_h_with_nothing_selected_shows_every_hidden_one(win):
    editor = _shown(win)
    boxes, (a, b) = _two_breps(win, editor)
    editor.hide([a.id, b.id])
    editor.canvas.scene().clearSelection()
    editor.canvas.setFocus()
    QTest.keyClick(editor.canvas, Qt.Key.Key_H,
                   Qt.KeyboardModifier.ControlModifier
                   | Qt.KeyboardModifier.ShiftModifier)
    assert a.preview and b.preview


def test_ctrl_shift_h_shows_only_the_selected_when_some_are(win):
    editor = win.show_hydra()
    boxes, (a, b) = _two_breps(win, editor)
    editor.hide([a.id, b.id])
    editor.canvas.node_items[a.id].setSelected(True)
    editor.show_hidden()
    assert a.preview and not b.preview


def test_ctrl_h_on_a_mixed_selection_hides_them_all(win):
    editor = win.show_hydra()
    boxes, (a, b) = _two_breps(win, editor)
    editor.set_preview(a.id, False)
    for node in (a, b):
        editor.canvas.node_items[node.id].setSelected(True)
    editor.hide()
    assert not a.preview and not b.preview


def test_the_menu_names_the_keys_for_hide_and_show(win):
    editor = win.show_hydra()
    boxes, (a, b) = _two_breps(win, editor)
    hide = _menu_action(editor, a, "Hide")
    assert hide.shortcut().toString() == "Ctrl+H"
    editor.hide([a.id])
    show = _menu_action(editor, a, "Show")
    assert show.shortcut().toString() == "Ctrl+Shift+H"


def test_hide_from_the_menu_takes_the_whole_selection(win):
    editor = win.show_hydra()
    boxes, (a, b) = _two_breps(win, editor)
    for node in (a, b):
        editor.canvas.node_items[node.id].setSelected(True)
    _menu_action(editor, b, "Hide").trigger()
    assert not a.preview and not b.preview


def test_what_shows_nothing_in_the_viewports_has_nothing_to_hide(win):
    editor = win.show_hydra()
    slider = editor.add_component("slider", (0, 0))
    assert _menu_action(editor, slider, "Hide") is None
    item = editor.canvas.node_items[slider.id]
    slider.preview = False
    assert not item.is_hidden()
    for key in ("vector", "move", "construct_point"):
        node = editor.add_component(key, (0, 100))
        assert _menu_action(editor, node, "Hide") is not None


def test_a_hidden_component_is_drawn_darker_than_a_shown_one(win):
    from PySide6.QtGui import QImage, QPainter
    editor = win.show_hydra()
    boxes, (a, b) = _two_breps(win, editor)
    editor.set_preview(a.id, False)

    def brightness(node):
        item = editor.canvas.node_items[node.id]
        image = QImage(int(item.width), int(item.height),
                       QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        item.paint(painter, None)
        painter.end()
        pixels = [image.pixelColor(x, y).lightness()
                  for x in range(4, image.width() - 4, 3)
                  for y in range(4, image.height() - 4, 3)]
        return sum(pixels) / len(pixels)
    assert brightness(a) < brightness(b) * 0.8


def test_a_hidden_component_stays_hidden_in_a_saved_graph(win):
    editor = win.show_hydra()
    boxes, (a, b) = _two_breps(win, editor)
    editor.hide([a.id])
    again = Graph.from_dict(editor.graph.to_dict())
    assert not again.nodes[a.id].preview and again.nodes[b.id].preview


# -- the start page -------------------------------------------------------------

def _save_graphs(win, dialogs, tmp_path, names):
    """Save one small graph under each name, through Save As."""
    editor = win.show_hydra()
    for i, name in enumerate(names):
        editor.new_graph()
        for k in range(i + 1):
            editor.add_component("curve", (0, 60 * k))
        dialogs["answer"] = str(tmp_path / f"{name}.hydra")
        editor.save_graph_as()
    return editor


def _reopen(win):
    """Hydra closed and opened again, then on its start page, as File >
    Start Page shows it."""
    win._hydra_dock.close()
    QApplication.processEvents()
    editor = win.show_hydra()
    [start] = [a for a in _menu(editor, "File").actions()
               if a.text().startswith("Start Page")]
    start.trigger()
    return editor


def test_opening_hydra_shows_the_recent_graphs_as_cards(
        win, dialogs, tmp_path):
    _save_graphs(win, dialogs, tmp_path, ["first", "second"])
    editor = _reopen(win)
    assert editor.starting()
    titles = [card.title for card in editor.start.cards]
    # the last graph is its file as saved: its own card, no Continue
    assert titles == ["New Graph", "second", "first"]


def test_double_clicking_a_card_opens_that_graph(win, dialogs, tmp_path):
    _save_graphs(win, dialogs, tmp_path, ["one", "two"])
    editor = _reopen(win)
    [one] = [c for c in editor.start.cards if c.title == "one"]
    QTest.mouseDClick(one, Qt.MouseButton.LeftButton)
    assert not editor.starting()
    assert editor.path == str(tmp_path / "one.hydra")
    assert [n.key for n in editor.graph.nodes.values()] == ["curve"]


def test_continue_goes_back_to_the_graph_being_worked_on(
        win, dialogs, tmp_path):
    editor = _save_graphs(win, dialogs, tmp_path, ["saved"])
    editor.add_component("rotate", (300, 0))          # not saved yet
    editor = _reopen(win)
    QTest.mouseDClick(editor.start.cards[1], Qt.MouseButton.LeftButton)
    assert not editor.starting()
    assert "rotate" in [n.key for n in editor.graph.nodes.values()]


def test_escape_on_the_start_page_continues(win, dialogs, tmp_path):
    _save_graphs(win, dialogs, tmp_path, ["saved"])
    editor = _reopen(win)
    QTest.keyClick(editor.start, Qt.Key.Key_Escape)
    assert not editor.starting()


def test_without_saved_graphs_hydra_opens_on_the_canvas(win):
    editor = win.show_hydra()
    assert not editor.starting()


def test_raising_hydra_while_it_is_open_keeps_the_canvas(
        win, dialogs, tmp_path):
    editor = _save_graphs(win, dialogs, tmp_path, ["saved"])
    editor.show_canvas()
    win.show_hydra()
    assert not editor.starting()


def test_a_graph_gone_from_disk_has_no_card(win, dialogs, tmp_path):
    import os
    _save_graphs(win, dialogs, tmp_path, ["kept", "gone"])
    os.remove(tmp_path / "gone.hydra")
    editor = _reopen(win)
    assert [c.title for c in editor.start.cards] == [
        "New Graph", "Continue", "kept"]


def test_adding_a_component_leaves_the_start_page(win, dialogs, tmp_path):
    _save_graphs(win, dialogs, tmp_path, ["saved"])
    editor = _reopen(win)
    editor.add_component("mesh", (0, 0))
    assert not editor.starting()


def test_an_opened_graph_is_a_recent_one_too(win, dialogs, tmp_path):
    import json
    path = tmp_path / "from_outside.hydra"
    path.write_text(json.dumps({"nodes": [{"id": "a", "key": "brep"}]}),
                    encoding="utf-8")
    editor = win.show_hydra()
    editor.open_path(str(path))
    assert editor.recent()[0] == str(path)


def test_a_cards_picture_shows_the_graph(win):
    from serpentine3d.ui.hydra.start import graph_preview
    graph = Graph()
    a = graph.add_node("curve", 0, 0)
    b = graph.add_node("rotate", 300, 40)
    graph.connect(a.id, "Curve", b.id, "Geometry")
    drawn = graph_preview(graph.to_dict(), 210, 118).toImage()
    empty = graph_preview({}, 210, 118).toImage()
    background = drawn.pixelColor(2, 2)
    painted = sum(drawn.pixelColor(x, y) != background
                  for x in range(0, 210, 3) for y in range(0, 118, 3))
    assert painted > 100
    assert drawn != empty


# -- what comes back from the session before -----------------------------------

def _restart(win):
    win.mark_saved()
    win.close()
    again = MainWindow()
    again.show()
    return again


def test_a_graph_whose_file_was_deleted_does_not_come_back(
        win, dialogs, tmp_path):
    import os
    editor = win.show_hydra()
    editor.add_component("rotate", (0, 0))
    editor.save_graph()
    os.remove(dialogs["answer"])
    again = _restart(win)
    try:
        editor = again.show_hydra()
        assert editor.graph.nodes == {}
        assert editor.path is None
        assert again._hydra_dock.windowTitle() == "Hydra"
        assert not editor.starting()          # nothing to offer: the canvas
    finally:
        again.mark_saved()
        again.close()


def test_unsaved_work_is_offered_to_continue_on_the_start_page(win):
    editor = win.show_hydra()
    editor.add_component("curve", (0, 0))     # never saved to a file
    again = _restart(win)
    try:
        editor = again.show_hydra()
        assert editor.starting()
        assert [c.title for c in editor.start.cards] == [
            "New Graph", "Continue"]
        QTest.mouseDClick(editor.start.cards[1], Qt.MouseButton.LeftButton)
        assert [n.key for n in editor.graph.nodes.values()] == ["curve"]
    finally:
        again.mark_saved()
        again.close()


def test_a_graph_whose_file_is_still_there_is_offered_with_it(
        win, dialogs, tmp_path):
    editor = win.show_hydra()
    editor.add_component("mesh", (0, 0))
    editor.save_graph()
    again = _restart(win)
    try:
        editor = again.show_hydra()
        assert editor.starting()
        assert [c.title for c in editor.start.cards] == [
            "New Graph", "graph"]
        assert editor.path == dialogs["answer"]
    finally:
        again.mark_saved()
        again.close()


def test_hydra_closed_with_its_x_comes_back_as_it_was_left(win):
    editor = win.show_hydra()
    editor.show_canvas()
    brep = editor.add_component("brep", (0, 0))
    editor.canvas.node_items[brep.id].setSelected(True)
    win._hydra_dock.titleBarWidget().close_btn.click()
    assert win._hydra_dock.isHidden()
    again = win.show_hydra()
    assert again is editor and not again.starting()
    assert list(again.graph.nodes) == [brep.id]
    assert again.selected_ids() == [brep.id]


def test_the_search_has_no_scroll_bar_and_shows_every_entry_whole(win):
    editor = _shown(win)
    search = editor.find_component(QPointF(0, 0), QPoint(200, 200))
    QApplication.processEvents()
    for text in ("", "po", "rot"):
        search.field.setText(text)
        QApplication.processEvents()
        lst = search.list
        assert not lst.verticalScrollBar().isVisible()
        assert not lst.horizontalScrollBar().isVisible()
        last = lst.visualItemRect(lst.item(lst.count() - 1))
        assert lst.viewport().rect().contains(last)
    search.close()


# -- Shift adds a wire, Ctrl takes one away -------------------------------------

_SHIFT = Qt.KeyboardModifier.ShiftModifier
_CTRL = Qt.KeyboardModifier.ControlModifier


def _drag_with(view, start_scene, end_scene, modifiers, check=None):
    a = view.mapFromScene(start_scene)
    b = view.mapFromScene(end_scene)
    left = Qt.MouseButton.LeftButton

    def send(kind, at, button, held):
        QApplication.sendEvent(view.viewport(), QMouseEvent(
            kind, QPointF(at), QPointF(view.mapToGlobal(at)), button, held,
            modifiers))
    send(QEvent.Type.MouseButtonPress, a, left, left)
    send(QEvent.Type.MouseMove, (a + b) / 2, Qt.MouseButton.NoButton, left)
    send(QEvent.Type.MouseMove, b, Qt.MouseButton.NoButton, left)
    if check is not None:
        check()
    send(QEvent.Type.MouseButtonRelease, b, left, Qt.MouseButton.NoButton)


def _breps_and_move(win, editor):
    boxes = [win.scene.add(geo.make_box((4 * i, 0, 0), 1, 1, 1))
             for i in range(2)]
    upper = editor.add_component("brep", (-320, -80))
    lower = editor.add_component("brep", (-320, 0))
    editor.set_references(upper.id, [boxes[0].id])
    editor.set_references(lower.id, [boxes[1].id])
    move = editor.add_component("move", (40, -20))
    editor.connect(lower.id, "Brep", move.id, "G")
    view = editor.canvas
    view.centerOn(-120, -30)
    QApplication.processEvents()
    return upper, lower, move


def _ports(editor, source, target, input="G"):
    view = editor.canvas
    return (view.node_items[source.id].port("Brep", True).scenePos(),
            view.node_items[target.id].port(input, False))


def test_shift_dragging_a_second_wire_into_g_moves_both_breps(win):
    editor = _shown(win)
    upper, lower, move = _breps_and_move(win, editor)
    start, g = _ports(editor, upper, move)
    seen = []
    _drag_with(editor.canvas, start, g.scenePos(), _SHIFT,
               lambda: seen.append((g._hover, g.hint())))
    assert seen == [(True, "add")]
    assert sorted(w.source for w in editor.graph.wires) == sorted(
        [upper.id, lower.id])
    editor.solve()
    assert len(editor.results[move.id].outputs["G"]) == 2
    assert _lines(g)[:2] == ["Geometry", "2 items"]


def test_a_plain_drag_still_replaces_the_wire_there(win):
    editor = _shown(win)
    upper, lower, move = _breps_and_move(win, editor)
    start, g = _ports(editor, upper, move)
    _drag_with(editor.canvas, start, g.scenePos(),
               Qt.KeyboardModifier.NoModifier)
    assert [w.source for w in editor.graph.wires] == [upper.id]


def test_ctrl_dragging_over_a_wire_takes_it_away(win):
    editor = _shown(win)
    upper, lower, move = _breps_and_move(win, editor)
    start, g = _ports(editor, lower, move)
    seen = []
    _drag_with(editor.canvas, start, g.scenePos(), _CTRL,
               lambda: seen.append(g.hint()))
    assert seen == ["remove"]
    assert editor.graph.wires == []
    assert "taken away" in editor.status.text()


def test_ctrl_dragging_where_no_wire_runs_takes_nothing(win):
    editor = _shown(win)
    upper, lower, move = _breps_and_move(win, editor)
    start, g = _ports(editor, upper, move)
    _drag_with(editor.canvas, start, g.scenePos(), _CTRL)
    assert [w.source for w in editor.graph.wires] == [lower.id]
    assert "No wire" in editor.status.text()


def test_ctrl_takes_away_only_the_wire_retraced_of_two(win):
    editor = _shown(win)
    upper, lower, move = _breps_and_move(win, editor)
    editor.connect(upper.id, "Brep", move.id, "G", add=True)
    start, g = _ports(editor, upper, move)
    _drag_with(editor.canvas, start, g.scenePos(), _CTRL)
    assert [w.source for w in editor.graph.wires] == [lower.id]


def test_ctrl_dragged_from_the_input_back_to_its_output_also_takes_it(win):
    editor = _shown(win)
    upper, lower, move = _breps_and_move(win, editor)
    out, g = _ports(editor, lower, move)
    _drag_with(editor.canvas, g.scenePos(), out, _CTRL)
    assert editor.graph.wires == []


def test_a_hovered_port_hints_what_shift_and_ctrl_would_do(win):
    editor = _shown(win)
    upper, lower, move = _breps_and_move(win, editor)
    _start, g = _ports(editor, upper, move)
    assert g.hint(Qt.KeyboardModifier.NoModifier) is None
    assert g.hint(_SHIFT) == "add"
    assert g.hint(_CTRL) == "remove"
    assert g.hint(_SHIFT | _CTRL) is None


def test_the_hint_is_drawn_green_for_add_and_red_for_remove(win):
    from PySide6.QtGui import QImage, QPainter
    from serpentine3d.ui.hydra import style
    editor = _shown(win)
    upper, lower, move = _breps_and_move(win, editor)
    _start, g = _ports(editor, upper, move)

    def drawn(mode):
        g.set_highlight(True, mode)
        rect = g.boundingRect()
        image = QImage(int(rect.width()), int(rect.height()),
                       QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        painter.translate(-rect.topLeft())
        g.paint(painter, None)
        painter.end()
        return {image.pixelColor(x, y).name()
                for x in range(image.width()) for y in range(image.height())
                if image.pixelColor(x, y).alpha() == 255}
    assert style.HINT["add"].name() in drawn("add")
    assert style.HINT["remove"].name() in drawn("remove")
    g.set_highlight(False)


def test_pressing_shift_while_dragging_turns_the_wire_green_at_once(win):
    editor = _shown(win)
    upper, lower, move = _breps_and_move(win, editor)
    start, g = _ports(editor, upper, move)
    scene = editor.canvas.scene()

    def press_shift_midway():
        scene.modifiers_changed(_SHIFT)
        assert scene._drag[1].mode == "add"
        assert g.hint() == "add"
    _drag_with(editor.canvas, start, g.scenePos(),
               Qt.KeyboardModifier.NoModifier, press_shift_midway)


def _key(widget, kind, key, modifiers):
    from PySide6.QtGui import QKeyEvent
    QApplication.sendEvent(widget, QKeyEvent(kind, key, modifiers))


def test_the_hint_comes_with_the_key_and_goes_when_it_is_let_go(win):
    editor = _shown(win)
    upper, lower, move = _breps_and_move(win, editor)
    _start, g = _ports(editor, upper, move)
    g.set_highlight(True)                      # the cursor is over it
    # the keys land on the main window: hovering gave Hydra no focus
    press, release = QEvent.Type.KeyPress, QEvent.Type.KeyRelease
    _key(win, press, Qt.Key.Key_Shift, _SHIFT)
    assert g.hint() == "add"
    _key(win, release, Qt.Key.Key_Shift, Qt.KeyboardModifier.NoModifier)
    assert g.hint() is None
    _key(win, press, Qt.Key.Key_Control, _CTRL)
    assert g.hint() == "remove"
    _key(win, release, Qt.Key.Key_Control, Qt.KeyboardModifier.NoModifier)
    assert g.hint() is None


def test_a_key_let_go_reads_as_let_go_whatever_the_platform_reports(win):
    editor = _shown(win)
    upper, lower, move = _breps_and_move(win, editor)
    _start, g = _ports(editor, upper, move)
    g.set_highlight(True)
    _key(win, QEvent.Type.KeyPress, Qt.Key.Key_Shift,
         Qt.KeyboardModifier.NoModifier)       # flag not in yet on press
    assert g.hint() == "add"
    _key(win, QEvent.Type.KeyRelease, Qt.Key.Key_Shift, _SHIFT)
    assert g.hint() is None                    # flag still in on release


def test_leaving_the_app_with_a_key_held_puts_the_hint_out(win):
    editor = _shown(win)
    upper, lower, move = _breps_and_move(win, editor)
    _start, g = _ports(editor, upper, move)
    g.set_highlight(True)
    _key(win, QEvent.Type.KeyPress, Qt.Key.Key_Shift, _SHIFT)
    QApplication.sendEvent(QApplication.instance(),
                           QEvent(QEvent.Type.ApplicationDeactivate))
    assert g.hint() is None


def test_a_closed_window_no_longer_listens_for_the_keys(win):
    editor = win.show_hydra()
    win.mark_saved()
    win.close()
    _key(QApplication.instance(), QEvent.Type.KeyPress, Qt.Key.Key_Shift,
         _SHIFT)                               # must not reach a dead scene


# -- Graft and Flatten on a port, and wires drawn by what they carry -----------

def _boxes_vectors_move(win, editor):
    boxes = [win.scene.add(geo.make_box((4 * i, 0, 0), 1, 1, 1))
             for i in range(2)]
    brep = editor.add_component("brep", (-320, -40))
    editor.set_references(brep.id, [b.id for b in boxes])
    move = editor.add_component("move", (40, -20))
    editor.connect(brep.id, "Brep", move.id, "G")
    for i, z in enumerate((2, 5)):
        v = editor.add_component("vector", (-320, 60 + 60 * i))
        editor.set_inputs(v.id, {"A": (0, 0, 0), "B": (0, 0, z)})
        editor.connect(v.id, "Vector", move.id, "V", add=True)
    editor.solve()
    return brep, move


def test_right_clicking_a_port_offers_graft_and_flatten(win):
    editor = win.show_hydra()
    brep, move = _boxes_vectors_move(win, editor)
    g = editor.canvas.node_items[move.id].port("G", False)
    menu = editor.port_menu(g)
    assert [a.text() for a in menu.actions() if not a.isSeparator()] == [
        "Graft", "Flatten", "Reverse", "Internalize"]
    assert not any(a.isChecked() for a in menu.actions())


def test_grafting_an_input_from_its_menu_crosses_the_lists(win):
    editor = win.show_hydra()
    brep, move = _boxes_vectors_move(win, editor)
    assert len(editor.results[move.id].outputs["G"]) == 2
    g = editor.canvas.node_items[move.id].port("G", False)
    [graft] = [a for a in editor.port_menu(g).actions() if a.text() == "Graft"]
    graft.trigger()
    assert move.params["flags"] == {"in:G": "graft"}
    assert len(editor.results[move.id].outputs["G"]) == 4
    assert g.flag() == "graft"
    assert _lines(g)[:2] == ["Geometry", "2 items"]
    # and the menu shows it ticked; ticking it off again takes it away
    [graft] = [a for a in editor.port_menu(g).actions() if a.text() == "Graft"]
    assert graft.isChecked()
    graft.trigger()
    assert "flags" not in move.params
    assert len(editor.results[move.id].outputs["G"]) == 2


def test_graft_and_flatten_rule_each_other_out_on_a_port(win):
    editor = win.show_hydra()
    brep, move = _boxes_vectors_move(win, editor)
    out = editor.canvas.node_items[move.id].port("G", True)
    editor.set_flag(out, "graft")
    editor.set_flag(out, "flatten")
    assert move.params["flags"] == {"out:G": "flatten"}


def test_a_right_click_on_a_port_opens_its_menu_not_the_components(
        win, monkeypatch):
    editor = _shown(win)
    brep, move = _boxes_vectors_move(win, editor)
    g = editor.canvas.node_items[move.id].port("G", False)
    opened = []

    class Menu:
        def __init__(self, kind):
            self.kind = kind

        def exec(self, *args):
            opened.append(self.kind)
    monkeypatch.setattr(editor, "port_menu", lambda port: Menu(port))
    monkeypatch.setattr(editor, "node_menu", lambda item: Menu("node"))
    editor.show_menu(g.scenePos(), QPoint(0, 0))
    assert opened == [g]


def test_wires_are_drawn_by_what_they_carry(win):
    editor = win.show_hydra()
    brep, move = _boxes_vectors_move(win, editor)
    carried = {(w.wire.source, w.wire.input): w.carries
               for w in editor.canvas.wire_items}
    assert carried[(brep.id, "G")] == "list"          # two boxes
    vectors = [n for n in editor.graph.nodes.values() if n.key == "vector"]
    assert all(carried[(v.id, "V")] == "item" for v in vectors)
    editor.set_flag(editor.canvas.node_items[brep.id].port("Brep", True),
                    "graft")
    carried = {(w.wire.source, w.wire.input): w.carries
               for w in editor.canvas.wire_items}
    assert carried[(brep.id, "G")] == "tree"


def test_a_list_wire_is_drawn_as_two_lines_and_a_tree_wire_dashed(win):
    from PySide6.QtGui import QImage, QPainter
    from serpentine3d.ui.hydra.items import WireItem
    from serpentine3d.core.hydra import Wire

    def lines_across(carries):
        item = WireItem(Wire("a", "o", "b", "i"))
        item.carries = carries
        item.set_ends(QPointF(0, 20), QPointF(200, 20))
        image = QImage(200, 40, QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        item.paint(painter, None)
        painter.end()
        alpha = [image.pixelColor(100, y).alpha() for y in range(40)]
        column = [a > 120 for a in alpha]
        runs = sum(1 for a, b in zip([False] + column, column) if b and not a)
        # along the top line, at the row it is drawn strongest in
        top = max(range(20), key=lambda y: alpha[y])
        row = [image.pixelColor(x, top).alpha() > 60 for x in range(20, 180)]
        gaps = sum(1 for a, b in zip(row, row[1:]) if a and not b)
        return runs, gaps
    assert lines_across("item")[0] == 1
    assert lines_across("list")[0] == 2
    list_gaps = lines_across("list")[1]
    assert lines_across("tree")[1] > list_gaps + 3


def test_a_flag_is_marked_inside_the_component_beside_its_port(win):
    from PySide6.QtGui import QImage, QPainter
    editor = win.show_hydra()
    brep, move = _boxes_vectors_move(win, editor)
    item = editor.canvas.node_items[move.id]
    g = item.port("G", False)

    def beside_g():
        image = QImage(int(item.width), int(item.height),
                       QImage.Format.Format_ARGB32)
        image.fill(0)
        painter = QPainter(image)
        item.paint(painter, None)
        painter.end()
        y = int(g.y())
        return [image.pixelColor(x, yy).name()
                for x in range(4, 15) for yy in range(y - 4, y + 5)]
    plain = beside_g()
    editor.set_flag(g, "graft")
    assert beside_g() != plain
    assert "#e4e5e7" in beside_g()


def test_a_port_flag_survives_copy_and_paste(win):
    editor = win.show_hydra()
    brep, move = _boxes_vectors_move(win, editor)
    editor.set_flag(editor.canvas.node_items[move.id].port("G", False),
                    "graft")
    [copy] = editor.duplicate([move.id])
    assert editor.graph.nodes[copy].params["flags"] == {"in:G": "graft"}
    editor.graph.nodes[copy].params["flags"]["in:G"] = "flatten"
    assert move.params["flags"] == {"in:G": "graft"}


# -- where the marks and names go, Reverse, and a right-click on a name ----------

def test_one_flagged_input_moves_every_input_name_so_they_stand_in_line(win):
    editor = win.show_hydra()
    brep, move = _boxes_vectors_move(win, editor)
    item = editor.canvas.node_items[move.id]
    plain_names, plain_width = item.names_at(), item.width
    editor.set_flag(item.port("G", False), "graft")
    assert item.names_at() > plain_names       # past the mark, for G and V
    assert item.width > plain_width            # the room comes from the node
    editor.set_flag(item.port("G", False), None)
    assert (item.names_at(), item.width) == (plain_names, plain_width)


def test_a_mark_stands_clear_of_the_ports_dot(win):
    from serpentine3d.ui.hydra.style import MARK_FROM, PORT_RADIUS
    assert MARK_FROM - 3.5 > PORT_RADIUS + 2


def test_an_outputs_mark_has_room_of_its_own_beside_the_title(win):
    editor = win.show_hydra()
    brep, move = _boxes_vectors_move(win, editor)
    item = editor.canvas.node_items[move.id]
    plain = item.width
    editor.set_flag(item.port("G", True), "flatten")
    assert item.width > plain
    assert item.port("G", True).x() == item.width   # the dot moved out too


def test_reverse_is_in_the_menu_and_goes_with_graft(win):
    editor = win.show_hydra()
    brep, move = _boxes_vectors_move(win, editor)
    g = editor.canvas.node_items[move.id].port("G", False)
    editor.set_flag(g, "graft")
    [reverse] = [a for a in editor.port_menu(g).actions()
                 if a.text() == "Reverse"]
    reverse.trigger()
    assert g.flags() == ["reverse", "graft"]
    assert move.params["flags"]["in:G"] == ["reverse", "graft"]
    assert _lines(g)[1] == "2 items"
    # Flatten in Graft's place keeps the Reverse
    editor.set_flag(g, "flatten")
    assert g.flags() == ["reverse", "flatten"]
    editor.set_reverse(g, False)
    assert move.params["flags"] == {"in:G": "flatten"}


def test_two_marks_on_a_port_make_room_for_two(win):
    editor = win.show_hydra()
    brep, move = _boxes_vectors_move(win, editor)
    item = editor.canvas.node_items[move.id]
    g = item.port("G", False)
    editor.set_flag(g, "graft")
    one = item.names_at()
    editor.set_reverse(g, True)
    assert item.names_at() > one


def test_a_right_click_on_an_inputs_name_opens_that_inputs_menu(
        win, monkeypatch):
    editor = _shown(win)
    brep, move = _boxes_vectors_move(win, editor)
    item = editor.canvas.node_items[move.id]
    opened = []

    class Menu:
        def __init__(self, what):
            self.what = what

        def exec(self, *args):
            opened.append(self.what)
    monkeypatch.setattr(editor, "port_menu", lambda port: Menu(port))
    monkeypatch.setattr(editor, "node_menu", lambda node: Menu("node"))
    for name in ("G", "V"):
        port = item.port(name, False)
        on_name = item.mapToScene(QPointF(item.names_at() + 3, port.y()))
        editor.show_menu(on_name, QPoint(0, 0))
    middle = item.mapToScene(QPointF(item.width / 2, item.height / 2))
    editor.show_menu(middle, QPoint(0, 0))
    assert opened == [item.port("G", False), item.port("V", False), "node"]


def test_a_saved_card_preview_makes_room_for_marks_too(win):
    from serpentine3d.ui.hydra.start import graph_preview
    graph = Graph()
    graph.add_node("move", params={"flags": {"in:G": "graft"}})
    assert not graph_preview(graph.to_dict(), 210, 118).isNull()


@pytest.mark.parametrize("output", [False, True])
def test_reverse_is_marked_right_of_graft_or_flatten(win, monkeypatch, output):
    from serpentine3d.ui.hydra import items
    editor = win.show_hydra()
    brep, move = _boxes_vectors_move(win, editor)
    item = editor.canvas.node_items[move.id]
    port = item.port("G", output)
    editor.set_flag(port, "graft")
    editor.set_reverse(port, True)
    drawn = []
    monkeypatch.setattr(items, "_paint_flag",
                        lambda painter, flag, at: drawn.append((flag, at.x())))
    item._paint_flags(None)
    xs = dict(drawn)
    assert xs["reverse"] > xs["graft"]


# -- Ctrl+S in Hydra -----------------------------------------------------------

def test_ctrl_s_in_hydra_saves_the_graph_not_the_model(win, dialogs):
    editor = _shown(win)
    editor.add_component("curve", (0, 0))
    editor.canvas.setFocus()
    saved_model = []
    win._file_save = lambda *a, **k: saved_model.append(1)
    QTest.keyClick(editor.canvas, Qt.Key.Key_S,
                   Qt.KeyboardModifier.ControlModifier)
    assert dialogs["save"] == 1                  # a new graph asks where
    assert _saved_keys(dialogs["answer"]) == ["curve"]
    editor.add_component("mesh", (0, 80))
    QTest.keyClick(editor.canvas, Qt.Key.Key_S,
                   Qt.KeyboardModifier.ControlModifier)
    assert dialogs["save"] == 1                  # then saves without asking
    assert _saved_keys(dialogs["answer"]) == ["curve", "mesh"]
    assert saved_model == []


def test_ctrl_shift_s_in_hydra_saves_the_graph_as(win, dialogs, tmp_path):
    editor = _shown(win)
    editor.add_component("curve", (0, 0))
    editor.save_graph()
    dialogs["answer"] = str(tmp_path / "other.hydra")
    editor.canvas.setFocus()
    QTest.keyClick(editor.canvas, Qt.Key.Key_S,
                   Qt.KeyboardModifier.ControlModifier
                   | Qt.KeyboardModifier.ShiftModifier)
    assert dialogs["save"] == 2
    assert editor.path == str(tmp_path / "other.hydra")


def test_ctrl_s_outside_hydra_is_still_the_models(win, dialogs):
    from PySide6.QtGui import QKeyEvent
    editor = _shown(win)
    event = QKeyEvent(QEvent.Type.ShortcutOverride, Qt.Key.Key_S,
                      Qt.KeyboardModifier.ControlModifier)
    assert not editor.eventFilter(win.viewport, event)
    assert dialogs["save"] == 0


# -- Internalize in the menus -----------------------------------------------------

def test_a_geometry_components_menu_offers_internalize(win):
    editor = win.show_hydra()
    box = win.scene.add(geo.make_box((0, 0, 0), 1, 1, 1))
    brep = editor.add_component("brep", (0, 0))
    assert not _menu_action(editor, brep, "Internalize").isEnabled()
    editor.set_references(brep.id, [box.id])
    _menu_action(editor, brep, "Internalize").trigger()
    win.scene.remove(box.id)
    editor.solve()
    item = editor.canvas.node_items[brep.id]
    assert item.result.status == "ok"
    assert item.summary() == "1 brep (internalized)"
    assert len(win.scene.hydra_preview[0])            # still shown


def test_setting_a_geometry_component_again_lets_its_copy_go(win):
    editor = win.show_hydra()
    a = win.scene.add(geo.make_box((0, 0, 0), 1, 1, 1))
    b = win.scene.add(geo.make_box((5, 0, 0), 1, 1, 1))
    brep = editor.add_component("brep", (0, 0))
    editor.set_references(brep.id, [a.id])
    editor.internalize(brep.id)
    editor.set_references(brep.id, [b.id])
    assert "internal" not in brep.params
    assert editor.canvas.node_items[brep.id].summary() == "1 brep"


def test_an_inputs_menu_offers_internalize_and_outputs_do_not(win):
    editor = win.show_hydra()
    brep, move = _boxes_vectors_move(win, editor)
    item = editor.canvas.node_items[move.id]
    texts = [a.text() for a in editor.port_menu(item.port("G", True)).actions()]
    assert "Internalize" not in texts
    [keep] = [a for a in editor.port_menu(item.port("V", False)).actions()
              if a.text() == "Internalize"]
    assert keep.isEnabled()
    keep.trigger()
    assert [w.input for w in editor.graph.wires if w.target == move.id] == [
        "G"]
    assert len(editor.canvas.wire_items) == 1
    assert _lines(item.port("V", False))[:2] == [
        "Vector", "Internalized · 2 items"]
    assert len(editor.results[move.id].outputs["G"]) == 2


def test_internalize_is_greyed_out_on_an_input_with_no_wire(win):
    editor = win.show_hydra()
    move = editor.add_component("move", (0, 0))
    editor.solve()
    g = editor.canvas.node_items[move.id].port("G", False)
    [keep] = [a for a in editor.port_menu(g).actions()
              if a.text() == "Internalize"]
    assert not keep.isEnabled()


def test_set_vector_replaces_what_a_vectors_input_had_internalized(win):
    editor = win.show_hydra()
    a = editor.add_component("construct_point", (-300, 0))
    v = editor.add_component("vector", (0, 0))
    editor.connect(a.id, "Point", v.id, "A")
    editor.solve()
    editor.internalize_input(editor.canvas.node_items[v.id].port("A", False))
    assert "A" in v.params["internal"]
    editor.set_inputs(v.id, {"A": (0, 0, 0), "B": (1, 0, 0)})
    assert "internal" not in v.params


def test_an_internalized_graph_saves_and_opens_whole(win, dialogs):
    editor = win.show_hydra()
    box = win.scene.add(geo.make_box((0, 0, 0), 1, 1, 1))
    brep = editor.add_component("brep", (0, 0))
    editor.set_references(brep.id, [box.id])
    editor.internalize(brep.id)
    editor.save_graph()
    editor.new_graph()
    win.scene.remove(box.id)
    editor.open_path(dialogs["answer"])
    assert editor.results[brep.id].status == "ok"
    assert len(editor.results[brep.id].outputs["Brep"]) == 1


# -- Ctrl+Z and Ctrl+Y in Hydra ----------------------------------------------------

_Z = (Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
_Y = (Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)


def test_ctrl_z_takes_back_the_last_change_and_ctrl_y_brings_it_again(win):
    editor = _shown(win)
    editor.add_component("curve", (0, 0))
    rotate = editor.add_component("rotate", (200, 0))
    editor.canvas.setFocus()
    QTest.keyClick(editor.canvas, *_Z)
    assert [n.key for n in editor.graph.nodes.values()] == ["curve"]
    QTest.keyClick(editor.canvas, *_Z)
    assert editor.graph.nodes == {}
    QTest.keyClick(editor.canvas, *_Y)
    QTest.keyClick(editor.canvas, *_Y)
    assert sorted(n.key for n in editor.graph.nodes.values()) == [
        "curve", "rotate"]
    assert rotate.id in editor.canvas.node_items


def test_a_wire_a_flag_and_a_delete_are_each_a_step(win):
    editor = win.show_hydra()
    curve = editor.add_component("curve", (0, 0))
    move = editor.add_component("move", (200, 0))
    editor.connect(curve.id, "Curve", move.id, "G")
    editor.set_flag(editor.canvas.node_items[move.id].port("G", False),
                    "graft")
    editor.remove_nodes([curve.id])
    editor.undo()
    assert len(editor.graph.wires) == 1
    editor.undo()
    assert "flags" not in editor.graph.nodes[move.id].params
    editor.undo()
    assert editor.graph.wires == []


def test_a_slider_drag_is_one_step_not_one_for_every_tick(win):
    editor = win.show_hydra()
    slider = editor.add_component("slider", (0, 0))
    item = editor.canvas.node_items[slider.id]
    item.mid_drag = True
    for x in range(60, 200, 10):
        item.slide_to(x)
        editor.solve()
    item.mid_drag = False
    editor.record()
    moved = slider.params["value"]
    editor.undo()
    assert editor.graph.nodes[slider.id].params["value"] == 5.0
    editor.redo()
    assert editor.graph.nodes[slider.id].params["value"] == moved


def test_a_component_moved_is_put_back_by_undo(win):
    editor = _shown(win)
    curve = editor.add_component("curve", (0, 0))
    item = editor.canvas.node_items[curve.id]
    item.setPos(150, 90)
    editor.record()
    editor.undo()
    assert (editor.graph.nodes[curve.id].x,
            editor.graph.nodes[curve.id].y) == (0, 0)
    assert editor.canvas.node_items[curve.id].pos() == QPointF(0, 0)


def test_ctrl_z_in_hydra_leaves_the_model_alone(win):
    editor = _shown(win)
    box = win.scene.add(geo.make_box((0, 0, 0), 1, 1, 1))
    editor.add_component("curve", (0, 0))
    editor.canvas.setFocus()
    QTest.keyClick(editor.canvas, *_Z)
    assert win.scene.get(box.id) is not None
    assert editor.graph.nodes == {}


def test_a_new_change_after_undo_clears_what_redo_would_bring(win):
    editor = win.show_hydra()
    editor.add_component("curve", (0, 0))
    editor.undo()
    editor.add_component("mesh", (0, 0))
    assert not editor.redo()
    assert [n.key for n in editor.graph.nodes.values()] == ["mesh"]


def test_opening_a_graph_starts_a_history_of_its_own(win, dialogs):
    editor = win.show_hydra()
    editor.add_component("curve", (0, 0))
    editor.save_graph()
    editor.add_component("mesh", (0, 0))
    editor.open_path(dialogs["answer"])
    assert not editor.undo()
    assert [n.key for n in editor.graph.nodes.values()] == ["curve"]


def test_ctrl_z_in_a_text_field_undoes_the_typing_not_the_graph(win):
    editor = _shown(win)
    slider = editor.add_component("slider", (0, 0))
    field = editor.type_value(editor.canvas.node_items[slider.id])
    field.setFocus()
    QApplication.processEvents()
    QTest.keyClicks(field, "12")
    QTest.keyClick(field, *_Z)
    assert slider.id in editor.graph.nodes


# -- what is selected in Hydra shows in the model ---------------------------------

def _two_box_nodes(win, editor):
    a = win.scene.add(geo.make_box((0, 0, 0), 1, 1, 1))
    b = win.scene.add(geo.make_box((5, 0, 0), 1, 1, 1))
    first = editor.add_component("brep", (0, 0))
    second = editor.add_component("brep", (0, 80))
    editor.set_references(first.id, [a.id])
    editor.set_references(second.id, [b.id])
    editor.solve()
    return first, second


def test_selecting_a_component_shows_what_it_makes_in_green(win):
    editor = win.show_hydra()
    first, second = _two_box_nodes(win, editor)
    both = len(win.scene.hydra_preview[0])
    assert win.scene.hydra_selected is None
    editor.canvas.node_items[first.id].setSelected(True)
    green = win.scene.hydra_selected
    assert green is not None and len(green[0]) == both // 2
    assert len(win.scene.hydra_preview[0]) == both // 2  # not drawn twice
    assert green[0][:, 0].max() < 2                      # the first box
    editor.canvas.scene().clearSelection()
    assert win.scene.hydra_selected is None
    assert len(win.scene.hydra_preview[0]) == both


def test_several_selected_components_all_show_in_green(win):
    editor = win.show_hydra()
    first, second = _two_box_nodes(win, editor)
    for node in (first, second):
        editor.canvas.node_items[node.id].setSelected(True)
    assert win.scene.hydra_preview is None
    assert win.scene.hydra_selected[0][:, 0].max() > 5


def test_a_hidden_component_still_shows_when_it_is_selected(win):
    editor = win.show_hydra()
    first, second = _two_box_nodes(win, editor)
    editor.hide([first.id])
    editor.canvas.node_items[first.id].setSelected(True)
    assert win.scene.hydra_selected is not None
    editor.canvas.scene().clearSelection()
    assert win.scene.hydra_selected is None


def test_a_selected_vector_shows_its_arrow_in_green(win):
    editor = win.show_hydra()
    v = editor.add_component("vector", (0, 0))
    editor.set_inputs(v.id, {"A": (0, 0, 0), "B": (0, 4, 0)})
    editor.canvas.node_items[v.id].setSelected(True)
    assert win.scene.hydra_selected[1][:, 1].max() == pytest.approx(4)


def test_closing_hydra_takes_the_green_away_too(win):
    win.show()
    editor = win.show_hydra()
    first, second = _two_box_nodes(win, editor)
    editor.canvas.node_items[first.id].setSelected(True)
    win._hydra_dock.close()
    QApplication.processEvents()
    assert win.scene.hydra_selected is None


# -- the menu bar -------------------------------------------------------------------

def _menu(editor, title):
    [menu] = [a.menu() for a in editor.menus.actions() if a.text() == title]
    return menu


def _entries(menu):
    return [a.text().split("\t")[0] for a in menu.actions()
            if not a.isSeparator()]


def test_the_menu_bar_holds_file_and_edit(win):
    editor = win.show_hydra()
    assert [a.text() for a in editor.menus.actions()] == ["File", "Edit"]


def test_the_node_bar_shows_every_component_by_category(win):
    editor = win.show_hydra()
    bar = editor.nodes_bar
    assert bar.groups == {
        "Geometry": ["point", "curve", "brep", "mesh"],
        "Input": ["toggle", "pipeline", "panel", "slider"],
        "Math": ["addition", "subtraction", "multiplication", "division",
                 "series", "range", "random", "round"],
        "List": ["list_item", "remove_item"],
        "Text": ["concatenate", "text_tag"],
        "Vector": ["construct_point", "vector", "unit_x", "unit_y",
                   "unit_z", "deconstruct_point"],
        "Curve": ["contour", "point_on_curve"],
        "Transform": ["move", "rotate", "group", "ungroup"],
        "Mesh": ["delaunay"]}
    for key, button in bar.buttons.items():
        assert button.text() == hydra.COMPONENTS[key].title
        assert not button.icon().isNull()
        assert button.toolButtonStyle() == (
            Qt.ToolButtonStyle.ToolButtonTextBesideIcon)


def test_the_node_bar_has_a_tab_for_each_category(win):
    editor = win.show_hydra()
    tabs = editor.nodes_bar.tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Geometry", "Input", "Math", "List", "Text", "Vector", "Curve",
        "Transform", "Mesh"]


def test_a_tab_shows_its_own_components_and_only_those(win):
    win.show()
    editor = win.show_hydra()
    bar = editor.nodes_bar
    bar.show_category("Transform")
    QApplication.processEvents()
    shown = {key for key, button in bar.buttons.items()
             if button.isVisibleTo(bar)}
    assert shown == {"move", "rotate", "group", "ungroup"}
    bar.show_category("List")
    QApplication.processEvents()
    shown = {key for key, button in bar.buttons.items()
             if button.isVisibleTo(bar)}
    assert shown == {"list_item", "remove_item"}


def test_the_node_bar_opens_on_the_tab_last_chosen(win):
    editor = win.show_hydra()
    editor.nodes_bar.show_category("Vector")
    win.mark_saved()
    win.close()
    again = MainWindow()
    try:
        assert again.show_hydra().nodes_bar.category() == "Vector"
    finally:
        again.mark_saved()
        again.close()


def test_clicking_a_component_in_the_node_bar_waits_for_a_click(win):
    editor = _shown(win)
    editor.nodes_bar.show_category("List")
    editor.nodes_bar.buttons["list_item"].click()
    assert editor.graph.nodes == {}               # nothing put down yet
    assert editor.placing == "list_item"
    assert "List Item" in editor.status.text()
    viewport = editor.canvas.viewport()
    assert viewport.cursor().shape() == Qt.CursorShape.BitmapCursor


def test_a_component_dragged_from_the_node_bar_lands_where_it_is_let_go(win):
    from PySide6.QtCore import QMimeData
    from PySide6.QtGui import QDropEvent
    from serpentine3d.ui.hydra.special import node_size
    from serpentine3d.ui.hydra.style import COMPONENT_MIME
    editor = _shown(win)
    view = editor.canvas
    data = QMimeData()
    data.setData(COMPONENT_MIME, b"rotate")
    at = view.viewport().rect().center() + QPoint(40, 30)
    drop = QDropEvent(QPointF(at), Qt.DropAction.CopyAction, data,
                      Qt.MouseButton.LeftButton,
                      Qt.KeyboardModifier.NoModifier)
    view.dropEvent(drop)
    [node] = editor.graph.nodes.values()
    assert node.key == "rotate"
    _labels, width, height = node_size(hydra.COMPONENTS["rotate"])
    middle = view.mapToScene(at)
    assert node.x == pytest.approx(middle.x() - width / 2, abs=1)
    assert node.y == pytest.approx(middle.y() - height / 2, abs=1)


def test_the_node_bar_keeps_its_height_whichever_tab_is_shown(win):
    win.show()
    editor = win.show_hydra()
    bar = editor.nodes_bar
    heights = set()
    for category in ("Geometry", "Input", "List"):
        bar.show_category(category)
        QApplication.processEvents()
        heights.add(bar.height())
    assert len(heights) == 1


def test_file_and_edit_hold_the_commands_with_their_keys_shown(win):
    editor = win.show_hydra()
    assert _entries(_menu(editor, "File")) == [
        "New", "Open…", "Start Page", "Save", "Save As…"]
    assert _entries(_menu(editor, "Edit")) == [
        "Undo", "Redo", "Copy", "Paste", "Delete", "Group", "Ungroup", "Hide",
        "Show"]
    save = [a for a in _menu(editor, "File").actions()
            if a.text().startswith("Save\t")][0]
    assert save.text() == "Save\tCtrl+S"
    # shown, not taken: the keys stay Hydra's own, clear of the main window
    every = [a for t in ("File", "Edit") for a in _menu(editor, t).actions()]
    assert all(a.shortcut().isEmpty() for a in every)


def test_edit_undo_in_the_menu_undoes(win):
    editor = win.show_hydra()
    editor.add_component("curve", (0, 0))
    [undo] = [a for a in _menu(editor, "Edit").actions()
              if a.text().startswith("Undo")]
    undo.trigger()
    assert editor.graph.nodes == {}


def test_file_new_in_the_menu_starts_an_empty_graph(win):
    editor = win.show_hydra()
    editor.add_component("curve", (0, 0))
    [new] = [a for a in _menu(editor, "File").actions() if a.text() == "New"]
    new.trigger()
    assert editor.graph.nodes == {}


# -- tooltips that show the data ---------------------------------------------------

def _list_item_from_three(win, editor, flags=None):
    shapes = [geo.make_box((0, 0, 0), 1, 1, 1),
              geo.make_box((3, 0, 0), 1, 1, 1),
              geo.make_line((0, 5, 0), (1, 5, 0))]
    brep = editor.add_component("brep", (-300, -60))
    editor.set_references(brep.id, [win.scene.add(s).id for s in shapes[:2]])
    curve = editor.add_component("curve", (-300, 40))
    editor.set_references(curve.id, [win.scene.add(shapes[2]).id])
    item = editor.add_component("list_item", (0, 0))
    editor.connect(brep.id, "Brep", item.id, "L")
    editor.connect(curve.id, "Curve", item.id, "L", add=True)
    if flags:
        item.params["flags"] = flags
    editor.solve()
    return editor.canvas.node_items[item.id]


def test_a_tooltip_says_what_the_input_takes_then_lists_its_items(win):
    editor = win.show_hydra()
    item = _list_item_from_three(win, editor)
    assert _lines(item.port("L", False)) == [
        "List", "3 items", "", "[0] Brep", "[1] Brep", "[2] Curve"]


def test_numbers_points_and_vectors_are_listed_with_their_values(win):
    editor = win.show_hydra()
    v = editor.add_component("vector", (0, 0))
    editor.set_inputs(v.id, {"A": (0, 0, 0), "B": (0, 2, 5)})
    item = editor.canvas.node_items[v.id]
    assert _lines(item.port("B", False))[-1] == "[0] Point 0, 2, 5"
    assert _lines(item.port("Vector", True))[-1] == "[0] Vector 0, 2, 5"
    angle = editor.add_component("rotate", (0, 100))
    editor.solve()
    port = editor.canvas.node_items[angle.id].port("Angle", False)
    assert _lines(port) == ["Number", "Default · 1 item", "", "[0] 0"]


def test_a_tree_is_listed_branch_by_branch(win):
    editor = win.show_hydra()
    item = _list_item_from_three(win, editor, {"in:L": "graft"})
    assert _lines(item.port("L", False)) == [
        "List", "3 items", "",
        "Branch {0;0} · 1 item", "  [0] Brep",
        "Branch {0;1} · 1 item", "  [0] Brep",
        "Branch {0;2} · 1 item", "  [0] Curve"]


def test_a_long_list_shows_its_first_items_and_counts_the_rest():
    from serpentine3d.core.hydra import Tree, list_tree
    lines = list_tree(Tree.of(list(range(40))))
    assert lines[0] == "[ 0] 0" and lines[11] == "[11] 11"
    assert lines[-1] == "… 28 more" and len(lines) == 13


def test_an_input_with_nothing_says_so_and_lists_nothing(win):
    editor = win.show_hydra()
    move = editor.add_component("move", (0, 0))
    editor.solve()
    port = editor.canvas.node_items[move.id].port("G", False)
    assert _lines(port) == ["Geometry", "Nothing connected"]


def test_every_port_of_every_component_says_what_it_is_for():
    for comp in hydra.COMPONENTS.values():
        for port in comp.inputs + comp.outputs:
            assert port.description, (comp.key, port.name)


def test_over_an_inputs_letter_the_inputs_tooltip_shows(win):
    from PySide6.QtWidgets import QGraphicsSceneHoverEvent
    editor = win.show_hydra()
    item = _list_item_from_three(win, editor)
    port = item.port("L", False)

    def hover(x, y):
        event = QGraphicsSceneHoverEvent(QEvent.Type.GraphicsSceneHoverMove)
        event.setPos(QPointF(x, y))
        item.hoverMoveEvent(event)
        return item.toolTip()
    assert hover(item.names_at() + 2, port.y()) == port.toolTip()
    assert hover(item.width / 2, item.height / 2).startswith(
        "The item at index i")


# -- a component clicked in the node bar, placed with the next click ---------------

def _click_canvas(editor, at, button=Qt.MouseButton.LeftButton):
    view = editor.canvas
    QTest.mouseClick(view.viewport(), button, pos=view.mapFromScene(at))


def test_the_next_click_on_the_canvas_puts_the_component_there(win):
    from serpentine3d.ui.hydra.special import node_size
    editor = _shown(win)
    editor.nodes_bar.show_category("Transform")
    editor.nodes_bar.buttons["rotate"].click()
    at = QPointF(120, 80)
    _click_canvas(editor, at)
    [node] = editor.graph.nodes.values()
    _labels, width, height = node_size(hydra.COMPONENTS["rotate"])
    assert node.key == "rotate"
    assert node.x == pytest.approx(at.x() - width / 2, abs=1)
    assert node.y == pytest.approx(at.y() - height / 2, abs=1)
    assert editor.placing is None
    assert editor.canvas.viewport().cursor().shape() != (
        Qt.CursorShape.BitmapCursor)


def test_one_click_puts_one_down(win):
    editor = _shown(win)
    editor.nodes_bar.buttons["curve"].click()
    _click_canvas(editor, QPointF(0, 0))
    _click_canvas(editor, QPointF(200, 0))
    assert [n.key for n in editor.graph.nodes.values()] == ["curve"]


def test_escape_or_the_right_button_puts_nothing_down(win):
    editor = _shown(win)
    editor.nodes_bar.buttons["curve"].click()
    QTest.keyClick(editor.nodes_bar.buttons["curve"], Qt.Key.Key_Escape)
    assert editor.placing is None
    editor.nodes_bar.buttons["curve"].click()
    _click_canvas(editor, QPointF(0, 0), Qt.MouseButton.RightButton)
    assert editor.placing is None and editor.graph.nodes == {}


def test_clicking_another_component_in_the_bar_waits_with_that_one(win):
    editor = _shown(win)
    editor.nodes_bar.buttons["curve"].click()
    editor.nodes_bar.buttons["mesh"].click()
    _click_canvas(editor, QPointF(0, 0))
    assert [n.key for n in editor.graph.nodes.values()] == ["mesh"]


def test_the_cursor_it_waits_on_shows_its_icon_and_a_plus(win):
    from serpentine3d.ui.hydra.bar import placing_cursor
    cursor = placing_cursor(hydra.COMPONENTS["rotate"])
    image = cursor.pixmap().toImage()
    assert not cursor.pixmap().isNull()
    assert image.width() > 1.5 * image.height()             # a node, wide
    right, bottom = image.width() - 9, image.height() - 9
    assert image.pixelColor(right - 3, bottom - 3).name() == "#d9a441"
    assert image.pixelColor(right, bottom).name() == "#1b1c1f"   # the plus
    hot = cursor.hotSpot()
    assert abs(hot.x() - (6 + right) / 2) <= 1
    assert abs(hot.y() - (4 + bottom) / 2) <= 1


def test_a_listing_shows_each_branch_with_its_count_and_empty_ones_too():
    from serpentine3d.core.hydra import Tree, list_tree
    lines = list_tree(Tree({(0,): [1.5, 2.0], (1,): [], (2,): [7.0]}))
    assert lines == ["Branch {0} · 2 items", "  [0] 1.5", "  [1] 2",
                     "Branch {1} · empty",
                     "Branch {2} · 1 item", "  [0] 7"]


def test_a_plain_list_is_listed_without_branch_headings():
    from serpentine3d.core.hydra import Tree, list_tree
    assert list_tree(Tree.of([3.0, 4.0])) == ["[0] 3", "[1] 4"]


# -- a number or a range typed into the search ----------------------------------

@pytest.mark.parametrize("text, settings", [
    ("0-15", (0.0, 15.0, 5.0, 0)),
    ("0.0-2.5", (0.0, 2.5, 2.5, 1)),
    ("-10 - -2", (-10.0, -2.0, -2.0, 0)),
    ("7,25", (0.0, 10.0, 7.25, 2)),
    ("40", (0.0, 40.0, 40.0, 0)),
])
def test_typing_a_number_or_a_range_and_enter_makes_that_slider(
        win, text, settings):
    editor = _shown(win)
    search = editor.find_component(QPointF(30, 40), QPoint(200, 200))
    QTest.keyClicks(search.field, text)
    assert search.list.item(0).text().startswith("Number Slider  ")
    QTest.keyClick(search.field, Qt.Key.Key_Return)
    [node] = editor.graph.nodes.values()
    assert node.key == "slider" and (node.x, node.y) == (30, 40)
    p = node.params
    assert (p["min"], p["max"], p["value"], p["decimals"]) == settings


def test_a_typed_slider_says_its_range_in_the_list(win):
    editor = _shown(win)
    search = editor.find_component(QPointF(0, 0), QPoint(200, 200))
    QTest.keyClicks(search.field, "0.0-12")
    assert search.list.item(0).text() == "Number Slider  0.0 to 12.0, at 5.0"
    search.close()


def test_a_name_typed_offers_no_slider(win):
    editor = _shown(win)
    search = editor.find_component(QPointF(0, 0), QPoint(200, 200))
    QTest.keyClicks(search.field, "rot")
    assert [search.list.item(i).text()
            for i in range(search.list.count())] == ["Rotate"]
    search.close()


def test_a_typed_slider_is_one_step_to_undo(win):
    editor = _shown(win)
    search = editor.find_component(QPointF(0, 0), QPoint(200, 200))
    QTest.keyClicks(search.field, "0-15")
    QTest.keyClick(search.field, Qt.Key.Key_Return)
    editor.undo()
    assert editor.graph.nodes == {}


def test_the_new_graph_card_comes_first_and_starts_an_empty_graph(
        win, dialogs, tmp_path):
    _save_graphs(win, dialogs, tmp_path, ["saved"])
    editor = _reopen(win)
    new = editor.start.cards[0]
    assert new.title == "New Graph"
    QTest.mouseDClick(new, Qt.MouseButton.LeftButton)
    assert not editor.starting()
    assert editor.graph.nodes == {} and editor.path is None


# -- the panel in the editor ------------------------------------------------------

def test_double_clicking_a_panel_opens_a_field_to_type_into(win):
    editor = _shown(win)
    panel = editor.add_component("panel", (0, 0))
    item = editor.canvas.node_items[panel.id]
    assert item.panel_lines() == (["Double-click to type"], False)
    field = editor.type_panel(item)
    assert field is not None and field.isVisible()
    field.setPlainText("one\ntwo")
    QTest.keyClick(field, Qt.Key.Key_Return,
                   Qt.KeyboardModifier.ControlModifier)
    assert editor.panel_field is None
    assert panel.params["text"] == "one\ntwo"
    editor.solve()
    assert editor.results[panel.id].outputs["Out"] == ["one", "two"]
    assert item.panel_lines() == (["one", "two"], True)


def test_enter_alone_starts_a_new_line_and_escape_keeps_the_old_text(win):
    editor = _shown(win)
    panel = editor.add_component("panel", (0, 0), {"text": "kept"})
    field = editor.type_panel(editor.canvas.node_items[panel.id])
    QTest.keyClicks(field, "x")
    QTest.keyClick(field, Qt.Key.Key_Return)
    assert editor.panel_field is field             # still typing
    QTest.keyClick(field, Qt.Key.Key_Escape)
    assert editor.panel_field is None
    assert panel.params["text"] == "kept"


def test_a_panel_with_a_wire_shows_what_comes_in_and_cannot_be_typed_into(
        win):
    editor = _shown(win)
    boxes = [win.scene.add(geo.make_box((3 * k, 0, 0), 1, 1, 1))
             for k in range(2)]
    brep = editor.add_component("brep", (-300, 0))
    editor.set_references(brep.id, [b.id for b in boxes])
    panel = editor.add_component("panel", (0, 0))
    editor.connect(brep.id, "Brep", panel.id, "In")
    editor.solve()
    item = editor.canvas.node_items[panel.id]
    assert item.panel_lines() == (["[0] Brep", "[1] Brep"], True)
    assert editor.type_panel(item) is None
    assert "take the wire away" in editor.status.text()


def test_typing_a_quotation_mark_and_text_into_the_search_makes_that_panel(
        win):
    editor = _shown(win)
    search = editor.find_component(QPointF(20, 30), QPoint(200, 200))
    QTest.keyClicks(search.field, '"Hallo Welt')
    assert search.list.item(0).text() == "Panel  “Hallo Welt”"
    QTest.keyClick(search.field, Qt.Key.Key_Return)
    [node] = editor.graph.nodes.values()
    assert node.key == "panel" and node.params["text"] == "Hallo Welt"
    assert (node.x, node.y) == (20, 30)


def test_a_typed_number_after_a_quotation_mark_is_a_panel_not_a_slider(win):
    editor = _shown(win)
    search = editor.find_component(QPointF(0, 0), QPoint(200, 200))
    QTest.keyClicks(search.field, '"12')
    assert search.list.item(0).text() == "Panel  “12”"
    QTest.keyClick(search.field, Qt.Key.Key_Return)
    [node] = editor.graph.nodes.values()
    assert node.key == "panel" and node.params["text"] == "12"


@pytest.mark.parametrize("output", [False, True])
def test_a_panels_flags_are_marked_beside_its_ports(win, monkeypatch, output):
    from serpentine3d.ui.hydra import items
    editor = win.show_hydra()
    panel = editor.add_component("panel", (0, 0), {"text": "a\nb"})
    item = editor.canvas.node_items[panel.id]
    plain = item.panel_area()
    port = item.port("Out" if output else "In", output)
    editor.set_flag(port, "graft")
    editor.set_reverse(port, True)
    drawn = []
    monkeypatch.setattr(items, "_paint_flag",
                        lambda painter, flag, at: drawn.append((flag, at)))
    from PySide6.QtGui import QImage, QPainter
    image = QImage(int(item.width), int(item.height),
                   QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    item.paint(painter, None)
    painter.end()
    assert sorted(f for f, _at in drawn) == ["graft", "reverse"]
    area = item.panel_area()
    # the text keeps its width, and no mark lies on it
    assert area.width() == pytest.approx(plain.width())
    assert all(not area.contains(at) for _f, at in drawn)
    assert all(at.y() == pytest.approx(port.y()) for _f, at in drawn)


def test_continue_is_offered_only_for_what_the_file_does_not_hold(
        win, dialogs):
    editor = win.show_hydra()
    editor.add_component("curve", (0, 0))
    editor.save_graph()
    assert not editor.unsaved()
    editor = _reopen(win)
    assert [c.title for c in editor.start.cards] == ["New Graph", "graph"]
    editor.show_canvas()
    editor.add_component("mesh", (0, 120))       # changed after saving
    assert editor.unsaved()
    editor = _reopen(win)
    assert [c.title for c in editor.start.cards] == [
        "New Graph", "Continue", "graph"]


# -- a mesh in the preview shows all its triangles --------------------------------

def _delaunay_preview(win, editor, coords):
    points = editor.add_component("point", (-300, 0))
    editor.set_references(points.id, [win.scene.add(geo.make_point(c)).id
                                      for c in coords])
    editor.set_preview(points.id, False)
    mesh = editor.add_component("delaunay", (0, 0))
    editor.connect(points.id, "Point", mesh.id, "P")
    editor.solve()
    return mesh


def test_a_flat_meshes_inner_edges_show_in_the_preview(win):
    editor = win.show_hydra()
    _delaunay_preview(win, editor, [(0, 0, 0), (4, 0, 0), (4, 4, 0),
                                    (0, 4, 0), (2, 2, 0)])
    segments = win.scene.hydra_preview[1].reshape(-1, 2, 3)
    # four triangles round the middle point: four rim edges, four inside
    assert len(segments) == 8
    inner = [s for s in segments
             if any(np.allclose(end[:2], (2, 2)) for end in s)]
    assert len(inner) == 4


def test_a_mesh_as_big_as_a_scan_shows_only_its_rim_and_creases():
    from serpentine3d.core.mesh import MeshShape
    from serpentine3d.ui.hydra import preview
    n = 230
    xs, ys = np.meshgrid(np.arange(n), np.arange(n))
    verts = np.column_stack([xs.ravel(), ys.ravel(), np.zeros(n * n)])
    quads = [(y * n + x, y * n + x + 1, (y + 1) * n + x)
             for y in range(n - 1) for x in range(n - 1)]
    quads += [(y * n + x + 1, (y + 1) * n + x + 1, (y + 1) * n + x)
              for y in range(n - 1) for x in range(n - 1)]
    big = MeshShape(verts, np.array(quads))
    assert len(big.triangles) > preview.MESH_WIRES_UP_TO
    assert preview._mesh_wires(big) is None


def test_an_empty_optional_input_says_it_is_optional(win):
    editor = win.show_hydra()
    mesh = editor.add_component("delaunay", (0, 0))
    editor.solve()
    outline = editor.canvas.node_items[mesh.id].port("Outline", False)
    assert _lines(outline) == ["Closed curve", "Optional · nothing connected"]


# -- renaming a component ---------------------------------------------------------

def _name_field(editor, node):
    return editor.node_menu(editor.canvas.node_items[node.id]).name_field


def test_the_menu_starts_with_the_components_name_to_type_over(win):
    editor = win.show_hydra()
    pipe = editor.add_component("pipeline", (0, 0))
    menu = editor.node_menu(editor.canvas.node_items[pipe.id])
    first = menu.actions()[0]
    assert first.defaultWidget() is menu.name_field
    assert menu.name_field.text() == "Geometry Pipeline"


def test_a_click_into_the_name_chooses_all_of_it(win):
    editor = _shown(win)
    pipe = editor.add_component("pipeline", (0, 0))
    field = _name_field(editor, pipe)
    field.show()
    QApplication.processEvents()
    QTest.mouseClick(field, Qt.MouseButton.LeftButton,
                     pos=field.rect().center())
    assert field.selectedText() == "Geometry Pipeline"


def test_a_name_typed_in_shows_beside_the_icon_and_sizes_the_node(win):
    editor = win.show_hydra()
    pipe = editor.add_component("pipeline", (0, 0))
    item = editor.canvas.node_items[pipe.id]
    before = item.width
    field = _name_field(editor, pipe)
    field.setText("Survey points of the north slope")
    field.editingFinished.emit()
    assert pipe.title == "Survey points of the north slope"
    assert pipe.params["name"] == "Survey points of the north slope"
    assert item.width > before
    assert item.outputs[0].x() == item.width


def test_an_empty_name_brings_the_components_own_back(win):
    editor = win.show_hydra()
    move = editor.add_component("move", (0, 0))
    editor.rename(move.id, "Lift")
    assert move.title == "Lift"
    editor.rename(move.id, "   ")
    assert move.title == "Move" and "name" not in move.params


def test_a_renaming_is_one_step_to_undo(win):
    editor = win.show_hydra()
    move = editor.add_component("move", (0, 0))
    editor.rename(move.id, "Lift")
    editor.undo()
    assert editor.graph.nodes[move.id].title == "Move"


def test_a_slider_and_a_toggle_show_a_name_they_are_given(win):
    editor = win.show_hydra()
    slider = editor.add_component("slider", (0, 0))
    item = editor.canvas.node_items[slider.id]
    rail = item._rail()[0]
    width = item.width
    editor.rename(slider.id, "Height")
    assert item._rail()[0] > rail and item.width > width
    toggle = editor.add_component("toggle", (0, 80))
    editor.rename(toggle.id, "Closed")
    assert editor.canvas.node_items[toggle.id]._given_name_room() > 0


def test_a_panel_shows_its_name_in_its_title_strip(win, monkeypatch):
    from PySide6.QtGui import QImage, QPainter
    editor = win.show_hydra()
    panel = editor.add_component("panel", (0, 0), {"text": "x"})
    editor.rename(panel.id, "Notes")
    item = editor.canvas.node_items[panel.id]
    written = []
    real = QPainter.drawText

    def spy(painter, *args):
        written.append(args[-1])
        return real(painter, *args)
    monkeypatch.setattr(QPainter, "drawText", spy)
    image = QImage(int(item.width), int(item.height),
                   QImage.Format.Format_ARGB32)
    painter = QPainter(image)
    item.paint(painter, None)
    painter.end()
    assert "Notes" in written and "Panel" not in written


def test_a_name_is_kept_in_the_file_and_in_a_copy(win):
    editor = win.show_hydra()
    move = editor.add_component("move", (0, 0))
    editor.rename(move.id, "Lift")
    [copy] = editor.duplicate([move.id])
    assert editor.graph.nodes[copy].title == "Lift"
    again = Graph.from_dict(editor.graph.to_dict())
    assert again.nodes[move.id].title == "Lift"


# -- a sign and a number typed into the search -------------------------------------

def _typed_into_search(editor, text):
    search = editor.find_component(QPointF(0, 0), QPoint(0, 0))
    search.field.setText(text)
    return search


def test_plus_two_typed_offers_an_addition_with_b_kept_at_two_first(win):
    editor = _shown(win)
    search = _typed_into_search(editor, "+2")
    first = search.list.item(0)
    assert first.text() == "Addition  A + 2"
    search._take(first)
    [node] = editor.graph.nodes.values()
    assert node.key == "addition"
    assert node.internal("B").branches[(0,)] == [2.0]
    editor.solve()
    assert editor.results[node.id].outputs["Result"].branches[(0,)] == [2.0]


def test_times_and_divided_by_are_typed_as_on_a_keyboard(win):
    editor = _shown(win)
    for text, said in (("*3", "Multiplication  A × 3"),
                       ("x3", "Multiplication  A × 3"),
                       ("/0,5", "Division  A ÷ 0.5"),
                       (":4", "Division  A ÷ 4")):
        search = _typed_into_search(editor, text)
        assert search.list.item(0).text() == said
        search.close()


def test_minus_two_is_first_a_slider_then_a_subtraction(win):
    editor = _shown(win)
    search = _typed_into_search(editor, "-2")
    assert search.list.item(0).data(Qt.ItemDataRole.UserRole) == "slider"
    assert search.list.item(1).text() == "Subtraction  A - 2"


# -- a panel dragged to another size by its corner ---------------------------------

def _drag_on_canvas(editor, a, b):
    view = editor.canvas
    a, b = view.mapFromScene(a), view.mapFromScene(b)
    left = Qt.MouseButton.LeftButton

    def send(kind, at, button, held):
        QApplication.sendEvent(view.viewport(), QMouseEvent(
            kind, QPointF(at), QPointF(view.mapToGlobal(at)), button, held,
            Qt.KeyboardModifier.NoModifier))
    send(QEvent.Type.MouseButtonPress, a, left, left)
    send(QEvent.Type.MouseMove, (a + b) / 2, Qt.MouseButton.NoButton, left)
    send(QEvent.Type.MouseMove, b, Qt.MouseButton.NoButton, left)
    send(QEvent.Type.MouseButtonRelease, b, left, Qt.MouseButton.NoButton)


def test_a_panel_dragged_by_its_corner_takes_the_new_size(win):
    editor = _shown(win)
    panel = editor.add_component("panel", (0, 0), {"text": "x"})
    item = editor.canvas.node_items[panel.id]
    width, height = item.width, item.height
    corner = item.mapToScene(QPointF(width - 4, height - 4))
    _drag_on_canvas(editor, corner, corner + QPointF(80, 60))
    assert item.width == pytest.approx(width + 80, abs=2)
    assert item.height == pytest.approx(height + 60, abs=2)
    assert (item.x(), item.y()) == (0, 0)              # it did not move
    assert item.outputs[0].x() == item.width
    assert item.outputs[0].y() == pytest.approx(item.height / 2)
    again = Graph.from_dict(editor.graph.to_dict())
    assert again.nodes[panel.id].params["size"] == panel.params["size"]


def test_a_panel_is_not_dragged_smaller_than_it_can_show(win):
    editor = _shown(win)
    panel = editor.add_component("panel", (0, 0))
    item = editor.canvas.node_items[panel.id]
    corner = item.mapToScene(QPointF(item.width - 4, item.height - 4))
    _drag_on_canvas(editor, corner, QPointF(-500, -500))
    assert panel.params["size"] == [120, 60]


def test_a_panels_new_size_is_one_step_to_undo(win):
    editor = _shown(win)
    panel = editor.add_component("panel", (0, 0))
    item = editor.canvas.node_items[panel.id]
    width = item.width
    corner = item.mapToScene(QPointF(item.width - 4, item.height - 4))
    _drag_on_canvas(editor, corner, corner + QPointF(100, 0))
    editor.undo()
    assert editor.canvas.node_items[panel.id].width == width


def test_a_double_click_on_the_corner_brings_the_first_size_back(win):
    editor = _shown(win)
    panel = editor.add_component("panel", (0, 0), {"size": [400, 300]})
    item = editor.canvas.node_items[panel.id]
    assert item.height == 300
    view = editor.canvas
    corner = view.mapFromScene(item.mapToScene(
        QPointF(item.width - 4, item.height - 4)))
    QTest.mouseDClick(view.viewport(), Qt.MouseButton.LeftButton, pos=corner)
    assert "size" not in panel.params
    assert item.height == 130


# -- components lined up with others while dragged ----------------------------------

def _drag_holding(editor, a, b, check=None):
    """A left drag on the canvas from scene point a to b; `check` is called
    before it is let go."""
    view = editor.canvas
    a, b = view.mapFromScene(a), view.mapFromScene(b)
    left = Qt.MouseButton.LeftButton

    def send(kind, at, button, held):
        QApplication.sendEvent(view.viewport(), QMouseEvent(
            kind, QPointF(at), QPointF(view.mapToGlobal(at)), button, held,
            Qt.KeyboardModifier.NoModifier))
    send(QEvent.Type.MouseButtonPress, a, left, left)
    send(QEvent.Type.MouseMove, (a + b) / 2, Qt.MouseButton.NoButton, left)
    send(QEvent.Type.MouseMove, b, Qt.MouseButton.NoButton, left)
    if check is not None:
        check()
    send(QEvent.Type.MouseButtonRelease, b, left, Qt.MouseButton.NoButton)


def _grab_point(item):
    # the middle of its title, clear of its ports
    return item.mapToScene(QPointF(item.width - 20, item.height / 2))


def test_a_component_dragged_near_another_lines_up_with_its_left_edge(win):
    editor = _shown(win)
    editor.add_component("move", (0, 0))
    moved = editor.add_component("rotate", (300, 300))
    item = editor.canvas.node_items[moved.id]
    start = _grab_point(item)
    shown = []
    # dropped 3 to the right of the other's left edge, far below it
    _drag_holding(editor, start, start + QPointF(-297, -100),
                  lambda: shown.append(list(editor.canvas.scene()._guides)))
    assert moved.x == 0 and moved.y == 200
    [guide] = shown[0]
    assert guide.x1() == guide.x2() == 0
    assert editor.canvas.scene()._guides == []        # gone once let go


def test_a_component_lines_up_by_its_bottom_too(win):
    editor = _shown(win)
    panel = editor.add_component("panel", (0, 0))
    other = editor.canvas.node_items[panel.id]
    moved = editor.add_component("curve", (400, 400))
    item = editor.canvas.node_items[moved.id]
    start = _grab_point(item)
    # its bottom 3 below the panel's, far to the right
    top = other.height - item.height + 3
    _drag_holding(editor, start, start + QPointF(-60, top - 400))
    assert moved.y + item.height == other.height


def test_a_component_far_from_any_other_goes_where_it_is_dragged(win):
    editor = _shown(win)
    editor.add_component("move", (0, 0))
    moved = editor.add_component("rotate", (300, 300))
    item = editor.canvas.node_items[moved.id]
    start = _grab_point(item)
    _drag_holding(editor, start, start + QPointF(77, 91))
    assert (moved.x, moved.y) == (377, 391)


def test_a_wired_component_lines_up_so_the_wire_runs_straight(win):
    editor = _shown(win)
    slider = editor.add_component("slider", (0, 0))
    rotate = editor.add_component("rotate", (400, 300))
    editor.connect(slider.id, "Number", rotate.id, "Angle")
    item = editor.canvas.node_items[rotate.id]
    out = editor.canvas.node_items[slider.id].port("Number", True)
    angle = item.port("Angle", False)
    start = _grab_point(item)
    gap = out.scenePos().y() - angle.scenePos().y()
    # dropped 4 below where the wire would run straight
    _drag_holding(editor, start, start + QPointF(0, gap + 4))
    assert angle.scenePos().y() == out.scenePos().y()


def test_dragging_a_slider_knob_lines_nothing_up(win):
    editor = _shown(win)
    editor.add_component("move", (0, 0))
    slider = editor.add_component("slider", (300, 3))
    item = editor.canvas.node_items[slider.id]
    x0, x1 = item._rail()
    a = item.mapToScene(QPointF(x0 + 5, NODE_MIDDLE))
    _drag_holding(editor, a, item.mapToScene(QPointF(x1 - 5, NODE_MIDDLE)))
    assert (slider.x, slider.y) == (300, 3)


NODE_MIDDLE = 14


def test_a_component_far_off_does_not_pull_a_dragged_one_into_line(win):
    editor = _shown(win)
    editor.add_component("move", (0, -3000))           # off the screen
    moved = editor.add_component("rotate", (300, 300))
    item = editor.canvas.node_items[moved.id]
    start = _grab_point(item)
    _drag_holding(editor, start, start + QPointF(-297, 0))
    assert moved.x == 3                    # not lined up with x 0 up there


# -- the align bar over two or more chosen components -------------------------------

def _three_chosen(editor):
    nodes = [editor.add_component("curve", (0, 0)),
             editor.add_component("move", (150, 40)),
             editor.add_component("point", (420, 15))]
    for node in nodes:
        editor.canvas.node_items[node.id].setSelected(True)
    return nodes


def test_the_align_bar_shows_only_while_two_or_more_are_chosen(win):
    editor = _shown(win)
    bar = editor.canvas.align_bar
    curve = editor.add_component("curve", (0, 0))
    move = editor.add_component("move", (200, 0))
    assert not bar.isVisible()
    editor.canvas.node_items[curve.id].setSelected(True)
    assert not bar.isVisible()
    editor.canvas.node_items[move.id].setSelected(True)
    assert bar.isVisible()
    # at the canvas's top right corner
    view = editor.canvas.viewport()
    assert bar.geometry().right() == view.width() - 8 - 1
    assert bar.geometry().top() == 8
    editor.canvas.scene().clearSelection()
    assert not bar.isVisible()


def test_spacing_evenly_needs_three(win):
    editor = _shown(win)
    bar = editor.canvas.align_bar
    a = editor.add_component("curve", (0, 0))
    b = editor.add_component("move", (200, 0))
    for node in (a, b):
        editor.canvas.node_items[node.id].setSelected(True)
    assert not bar.buttons["across"].isEnabled()
    c = editor.add_component("point", (400, 0))
    editor.canvas.node_items[c.id].setSelected(True)
    assert bar.buttons["across"].isEnabled()


def test_align_left_lines_the_chosen_up_on_the_leftmost_edge(win):
    editor = _shown(win)
    nodes = _three_chosen(editor)
    editor.canvas.align_bar.buttons["left"].click()
    assert [n.x for n in nodes] == [0, 0, 0]
    assert [n.y for n in nodes] == [0, 40, 15]


def test_align_middle_puts_them_side_by_side_on_one_line(win):
    editor = _shown(win)
    nodes = _three_chosen(editor)
    editor.align("middle")
    middles = {n.y + editor.canvas.node_items[n.id].height / 2
               for n in nodes}
    assert len(middles) == 1


def test_spacing_evenly_leaves_the_same_gap_between_each(win):
    editor = _shown(win)
    nodes = _three_chosen(editor)
    editor.align("across")
    items = sorted((editor.canvas.node_items[n.id] for n in nodes),
                   key=lambda i: i.x())
    gaps = [b.x() - (a.x() + a.width) for a, b in zip(items, items[1:])]
    assert gaps[0] == pytest.approx(gaps[1])
    assert items[0].x() == 0                     # the first stays
    assert items[-1].x() == 420                  # and the last


def test_an_alignment_is_one_step_to_undo(win):
    editor = _shown(win)
    nodes = _three_chosen(editor)
    editor.align("left")
    editor.undo()
    assert [editor.graph.nodes[n.id].x for n in nodes] == [0, 150, 420]


def test_arranging_boxes_aligns_their_edges_and_middles():
    from serpentine3d.ui.hydra.align import arranged
    boxes = [(0, 0, 10, 10), (20, 5, 30, 20)]
    assert arranged(boxes, "right") == [(40, 0), (20, 5)]
    assert arranged(boxes, "center") == [(20, 0), (10, 5)]
    assert arranged(boxes, "bottom") == [(0, 15), (20, 5)]


# -- choosing as in the model: Shift or Ctrl and a click, or a box ------------------

def _click_node(editor, node, modifiers=Qt.KeyboardModifier.NoModifier):
    item = editor.canvas.node_items[node.id]
    view = editor.canvas
    at = view.mapFromScene(_grab_point(item))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, modifiers,
                     at)


def _chosen(editor):
    return {i.node.id for i in editor.canvas.chosen_items()}


def test_shift_and_a_click_add_one_to_the_choice_and_take_it_out_again(win):
    editor = _shown(win)
    a = editor.add_component("curve", (0, 0))
    b = editor.add_component("move", (200, 0))
    shift = Qt.KeyboardModifier.ShiftModifier
    _click_node(editor, a)
    _click_node(editor, b, shift)
    assert _chosen(editor) == {a.id, b.id}
    _click_node(editor, b, shift)
    assert _chosen(editor) == {a.id}


def test_ctrl_and_a_click_do_the_same_as_in_the_model(win):
    editor = _shown(win)
    a = editor.add_component("curve", (0, 0))
    b = editor.add_component("move", (200, 0))
    ctrl = Qt.KeyboardModifier.ControlModifier
    _click_node(editor, a)
    _click_node(editor, b, ctrl)
    assert _chosen(editor) == {a.id, b.id}
    _click_node(editor, a, ctrl)
    assert _chosen(editor) == {b.id}


def test_a_plain_click_chooses_only_that_one(win):
    editor = _shown(win)
    a = editor.add_component("curve", (0, 0))
    b = editor.add_component("move", (200, 0))
    _click_node(editor, a)
    _click_node(editor, b)
    assert _chosen(editor) == {b.id}


def _box_on_canvas(editor, a, b, modifiers):
    view = editor.canvas
    a, b = view.mapFromScene(a), view.mapFromScene(b)
    left = Qt.MouseButton.LeftButton

    def send(kind, at, button, held):
        QApplication.sendEvent(view.viewport(), QMouseEvent(
            kind, QPointF(at), QPointF(view.mapToGlobal(at)), button, held,
            modifiers))
    send(QEvent.Type.MouseButtonPress, a, left, left)
    send(QEvent.Type.MouseMove, (a + b) / 2, Qt.MouseButton.NoButton, left)
    send(QEvent.Type.MouseMove, b, Qt.MouseButton.NoButton, left)
    send(QEvent.Type.MouseButtonRelease, b, left, Qt.MouseButton.NoButton)


def test_a_box_with_shift_adds_to_the_choice_and_with_ctrl_takes_from_it(win):
    editor = _shown(win)
    a = editor.add_component("curve", (0, 0))
    b = editor.add_component("curve", (300, 0))
    c = editor.add_component("curve", (300, 200))
    _click_node(editor, a)
    # round b alone
    _box_on_canvas(editor, QPointF(280, -30), QPointF(450, 60),
                   Qt.KeyboardModifier.ShiftModifier)
    assert _chosen(editor) == {a.id, b.id}
    # round b and c, with Ctrl: b goes, c was never in
    _box_on_canvas(editor, QPointF(280, -30), QPointF(450, 260),
                   Qt.KeyboardModifier.ControlModifier)
    assert _chosen(editor) == {a.id}


def test_a_click_on_nothing_with_shift_keeps_the_choice(win):
    editor = _shown(win)
    a = editor.add_component("curve", (0, 0))
    _click_node(editor, a)
    view = editor.canvas
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.ShiftModifier,
                     view.mapFromScene(QPointF(600, 600)))
    assert _chosen(editor) == {a.id}
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier,
                     view.mapFromScene(QPointF(600, 600)))
    assert _chosen(editor) == set()


def test_ctrl_a_chooses_every_component_not_the_models_objects(win):
    editor = _shown(win)
    box = win.scene.add(geo.make_box((0, 0, 0), 1, 1, 1))
    a = editor.add_component("curve", (0, 0))
    b = editor.add_component("move", (200, 0))
    editor.canvas.setFocus()
    QTest.keyClick(editor.canvas, Qt.Key.Key_A,
                   Qt.KeyboardModifier.ControlModifier)
    assert _chosen(editor) == {a.id, b.id}
    assert not win.selection.is_selected(box.id)


def test_ctrl_e_fits_every_component_into_view(win):
    editor = _shown(win)
    editor.add_component("curve", (-900, -700))
    editor.add_component("move", (900, 700))
    view = editor.canvas
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_E, Qt.KeyboardModifier.ControlModifier)
    shown = view.mapToScene(view.viewport().rect()).boundingRect()
    for item in view.node_items.values():
        assert shown.contains(item.sceneBoundingRect())


# -- groups: a background round components, moved and ended as one -----------------

def _grouped(editor):
    a = editor.add_component("curve", (0, 0))
    b = editor.add_component("move", (200, 60))
    for node in (a, b):
        editor.canvas.node_items[node.id].setSelected(True)
    view = editor.canvas
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_G, Qt.KeyboardModifier.ControlModifier)
    [group] = view.group_items.values()
    return a, b, group


def test_ctrl_g_puts_the_chosen_components_on_one_background(win):
    editor = _shown(win)
    a, b, group = _grouped(editor)
    assert set(editor.graph.groups[group.group_id]) == {a.id, b.id}
    rect = group.boundingRect()
    for node in (a, b):
        assert rect.contains(
            editor.canvas.node_items[node.id].sceneBoundingRect())
    assert group.zValue() < editor.canvas.node_items[a.id].zValue()


def test_a_component_moved_alone_takes_the_background_with_it(win):
    editor = _shown(win)
    a, b, group = _grouped(editor)
    item = editor.canvas.node_items[b.id]
    item.setPos(500, 300)
    assert group.boundingRect().contains(item.sceneBoundingRect())
    assert editor.graph.nodes[a.id].x == 0          # the other stays


def test_dragging_the_background_moves_the_whole_group(win):
    editor = _shown(win)
    a, b, group = _grouped(editor)
    corner = group.boundingRect().topLeft() + QPointF(5, 5)
    _drag_holding(editor, corner, corner + QPointF(100, 50))
    assert (a.x, a.y) == (100, 50)
    assert (b.x, b.y) == (300, 110)
    editor.undo()
    assert (editor.graph.nodes[a.id].x, editor.graph.nodes[b.id].x) == (0, 200)


def test_delete_on_the_background_ends_the_grouping_not_the_components(win):
    editor = _shown(win)
    a, b, group = _grouped(editor)
    corner = group.boundingRect().topLeft() + QPointF(5, 5)
    view = editor.canvas
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     pos=view.mapFromScene(corner))
    assert view.chosen_group is group and group.chosen
    assert view.chosen_items() == []
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert editor.graph.groups == {} and view.group_items == {}
    assert set(editor.graph.nodes) == {a.id, b.id}


def test_a_click_beside_the_group_lets_it_go(win):
    editor = _shown(win)
    _a, _b, group = _grouped(editor)
    view = editor.canvas
    corner = group.boundingRect().topLeft() + QPointF(5, 5)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     pos=view.mapFromScene(corner))
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton,
                     pos=view.mapFromScene(QPointF(900, 900)))
    assert view.chosen_group is None and not group.chosen


def test_ctrl_shift_g_ends_the_group_of_the_chosen_components(win):
    editor = _shown(win)
    a, _b, _group = _grouped(editor)
    view = editor.canvas
    view.scene().clearSelection()
    view.node_items[a.id].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_G, Qt.KeyboardModifier.ControlModifier
                   | Qt.KeyboardModifier.ShiftModifier)
    assert editor.graph.groups == {} and view.group_items == {}


def test_a_group_is_one_step_to_undo_and_comes_back_from_the_file(win):
    editor = _shown(win)
    _a, _b, group = _grouped(editor)
    gid = group.group_id
    editor.load(editor.graph.to_dict())
    assert set(editor.canvas.group_items) == {gid}
    editor.undo()
    assert editor.graph.groups == {} and editor.canvas.group_items == {}


def test_deleting_a_grouped_component_shrinks_its_group(win):
    editor = _shown(win)
    a, b, group = _grouped(editor)
    view = editor.canvas
    view.scene().clearSelection()
    view.node_items[b.id].setSelected(True)
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert editor.graph.groups == {group.group_id: [a.id]}
    assert group.boundingRect().width() < 200


def test_a_right_click_on_the_background_offers_an_empty_name_to_fill(win):
    editor = _shown(win)
    _a, _b, group = _grouped(editor)
    menu = editor.group_menu(group)
    assert menu.actions()[0].defaultWidget() is menu.name_field
    assert menu.name_field.text() == ""
    assert "Ungroup" in [a.text() for a in menu.actions()]
    menu.name_field.setText("Facade")
    menu.name_field.editingFinished.emit()
    assert group.name() == "Facade"
    # written over the group, above its background, in the middle
    assert group.boundingRect().top() < group._rect.top() - 10
    assert group._name_rect().center().x() == pytest.approx(
        group._rect.center().x())
    editor.undo()
    assert editor.graph.group_names == {}


def test_the_background_is_where_a_right_click_finds_the_group(win):
    editor = _shown(win)
    _a, _b, group = _grouped(editor)
    corner = group._rect.topLeft() + QPointF(5, 5)
    assert editor.canvas.group_at(corner) is group
    inside = editor.canvas.node_items[_a.id].sceneBoundingRect().center()
    assert editor.canvas.group_at(inside) is None   # a component is over it
    assert editor.canvas.group_at(QPointF(2000, 2000)) is None


def test_a_groups_background_lies_behind_its_wires(win):
    editor = _shown(win)
    slider = editor.add_component("slider", (0, 0))
    rotate = editor.add_component("rotate", (300, 0))
    editor.connect(slider.id, "Number", rotate.id, "Angle")
    for node in (slider, rotate):
        editor.canvas.node_items[node.id].setSelected(True)
    editor.group_selected()
    [group] = editor.canvas.group_items.values()
    [wire] = editor.canvas.wire_items
    assert group.zValue() < wire.zValue()


def test_hydras_title_shows_a_close_button_and_no_float_button(win):
    from serpentine3d.ui.dock_title import DockTitleBar
    win.show()
    editor = win.show_hydra()
    QApplication.processEvents()
    title = win._hydra_dock.titleBarWidget()
    assert isinstance(title, DockTitleBar)
    assert title.close_btn.isVisible() and not title.float_btn.isVisible()
    editor.set_path("C:/graphs/roof.hydra")
    assert title.title.text() == "Hydra · roof.hydra"
    title.close_btn.click()
    assert win._hydra_dock.isHidden()


def test_a_mesh_is_cast_faceted(win):
    from serpentine3d.core.delaunay import triangulate
    from serpentine3d.core.mesh import MeshShape
    editor = win.show_hydra()
    xy = np.array([[0, 0], [10, 0], [0, 10], [10, 10], [5, 5]], float)
    mesh = MeshShape(np.c_[xy, [0, 0, 0, 0, 4]], triangulate(xy))
    node = editor.add_component("panel", (0, 0))
    editor.solve()
    editor.results[node.id].outputs["Out"] = hydra.Tree.of([mesh])
    [obj] = editor.cast_into([node.id], win.scene.layers.current_id)
    assert obj.shape.faceted
    assert np.array_equal(obj.shape.triangles, mesh.triangles)



def test_a_component_with_several_outputs_names_them_down_its_right(win):
    editor = win.show_hydra()
    node = editor.add_component("deconstruct_point", (0, 0))
    item = editor.canvas.node_items[node.id]
    assert [p.port.name for p in item.outputs] == ["X", "Y", "Z"]
    assert item.out_labels > 0
    # each output found by its name as well as its dot
    for port in item.outputs:
        at = QPointF(item.width - 12, port.y())
        assert item.port_at(at) is port
    # and no names for a component with one output
    move = editor.canvas.node_items[editor.add_component("move", (0, 90)).id]
    assert move.out_labels == 0


def test_a_text_tag_is_cast_as_text_to_edit(win):
    from serpentine3d.core.hydra.components.text import _text_tag
    from serpentine3d.core.hydra.kinds import Vector
    from serpentine3d.core.text_object import TextShape
    editor = win.show_hydra()
    node = editor.add_component("text_tag", (0, 0))
    editor.solve()
    tag = _text_tag(geo.make_point((0, 0, 0)), "245 m", 2.0,
                    Vector((0, 0, 0), (1, 0, 0)))
    editor.results[node.id].outputs["Tag"] = hydra.Tree.of([tag])
    [obj] = editor.cast_into([node.id], win.scene.layers.current_id)
    assert isinstance(obj.shape, TextShape) and obj.shape.text == "245 m"



def test_the_groups_menu_adds_the_chosen_components_to_it(win):
    editor = _shown(win)
    _a, _b, group = _grouped(editor)
    c = editor.add_component("point", (500, 300))
    view = editor.canvas
    view.scene().clearSelection()
    menu = editor.group_menu(group)
    [add] = [a for a in menu.actions() if a.text() == "Add to Group"]
    assert not add.isEnabled()                   # nothing chosen to add
    view.node_items[c.id].setSelected(True)
    menu = editor.group_menu(group)
    [add] = [a for a in menu.actions() if a.text() == "Add to Group"]
    assert add.isEnabled()
    add.trigger()
    assert c.id in editor.graph.groups[group.group_id]
    assert group.boundingRect().contains(
        view.node_items[c.id].sceneBoundingRect())
    editor.undo()
    assert c.id not in editor.graph.groups[group.group_id]


def test_a_group_of_geometry_is_cast_as_one_of_the_models_groups(win):
    editor = win.show_hydra()
    node = editor.add_component("group", (0, 0))
    editor.solve()
    kept = hydra.GeometryGroup((geo.make_line((0, 0, 0), (1, 0, 0)),
                                geo.make_line((0, 1, 0), (1, 1, 0))))
    loose = geo.make_line((0, 5, 0), (1, 5, 0))
    editor.results[node.id].outputs["G"] = hydra.Tree.of([kept, loose])
    objects = editor.cast_into([node.id], win.scene.layers.current_id)
    assert len(objects) == 3
    groups = [win.scene.get(obj.id).group_id for obj in objects]
    assert groups[0] and groups[0] == groups[1] and not groups[2]
