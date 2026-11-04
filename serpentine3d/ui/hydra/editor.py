"""Hydra's canvas: components as boxes, wires from outputs to inputs, and a
preview of what the graph holds in every model viewport.

Double-click or right-click the canvas to find a component by typing its
name; right-click a component to set it to objects picked in the model, to
cast it or to hide it, or a slider to change its range and decimals. Ctrl+H
hides the selection in the viewports and Ctrl+Shift+H shows it again, as
for the model's own objects; Delete removes it, dragging with the right
button pans and the wheel zooms.
"""

from __future__ import annotations

import json
import os
import uuid

from PySide6.QtCore import QEvent, QMimeData, QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QActionGroup, QCursor, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QDialog, QDockWidget, QFileDialog, QHBoxLayout, QLabel,
    QLineEdit, QMenu, QMenuBar, QStackedWidget, QVBoxLayout, QWidget,
    QWidgetAction,
)

from ...core import hydra
from ...core.hydra import (
    CATEGORIES, COMPONENTS, GEOMETRY_KINDS, Graph, HydraError,
)
from .align import arranged
from .bar import NodeBar, placing_cursor
from .canvas import HydraCanvas
from .fields import (
    CastDialog, ComponentSearch, NameField, PanelField, RangeDialog,
    ValueField, add_command,
)
from .items import NodeItem, WireItem
from .keys import MODIFIER_OF, save_key, undo_key
from .preview import PreviewMeshes
from .special import node_size
from .start import HydraStart, read_graph
from .style import NODE_HEIGHT, VALUE_GAP, component_icon


PASTE_STEP = 30             # how far a paste lands from what it copied


UNDO_STEPS = 100            # how far back Ctrl+Z reaches


CLIPBOARD = "application/x-serpentine-hydra"


class HydraEditor(QWidget):
    """The graph, its canvas, and what it shows in the model."""

    def __init__(self, window):
        super().__init__()
        self.window = window
        self.graph = Graph()
        self.results: dict = {}
        self.shapes: list = []
        self.active = True
        self.picking = None        # the node a Set action picks for
        self.value_field = None    # typing into a slider, while it lasts
        self.panel_field = None    # typing into a panel, while it lasts
        self.placing = None        # a component waiting on the cursor
        self.meshes = PreviewMeshes()
        self.selected_meshes = PreviewMeshes()
        self.search = None         # the find-a-component field, while open
        self.canvas = HydraCanvas(self)
        self.canvas.scene().selectionChanged.connect(self._selection_changed)

        bar = QHBoxLayout()
        bar.setContentsMargins(0, 0, 6, 0)
        self.menus = self._menu_bar()
        bar.addWidget(self.menus)
        bar.addStretch(1)
        self.status = QLabel()
        self.status.setStyleSheet("color: #9a9b9e;")
        bar.addWidget(self.status)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addLayout(bar)
        self.nodes_bar = NodeBar(self)
        root.addWidget(self.nodes_bar)
        self.start = HydraStart(self)
        self.pages = QStackedWidget()
        self.pages.addWidget(self.canvas)
        self.pages.addWidget(self.start)
        root.addWidget(self.pages, 1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(15)
        self._timer.timeout.connect(self.solve)
        # picked objects that move or go away show so straight away
        window.scene.add_listener(self.changed, kinds=("objects",))
        # Shift and Ctrl are heard wherever the keyboard is, not only on the
        # canvas: hovering a port gives it no focus, and the hint has to
        # come and go with the key all the same
        QApplication.instance().installEventFilter(self)

        # The graph last worked on, kept from the session before. One that
        # belonged to a file since deleted is let go with its file, rather
        # than coming back from nowhere under a name that is gone.
        saved = window.cfg.get("hydra_graph", default=None)
        path = window.cfg.get("hydra_path", default=None)
        path = path if isinstance(path, str) else None
        if path is not None and not os.path.exists(path):
            saved, path = None, None
        self.load(saved if isinstance(saved, dict) else {})
        self.path = path
        self._restoring = False
        self.forget_steps()

    # ------------------------------------------------------------- editing

    def _menu_bar(self):
        """File and Edit, then a menu for each category of component."""
        menus = QMenuBar()
        menus.setNativeMenuBar(False)       # in Hydra, not the system's
        file = menus.addMenu("File")
        add_command(file, "New", self.new_graph, "Start an empty graph")
        add_command(file, "Open…", self.open_graph, "Open a .hydra file")
        add_command(file, "Start Page", self.show_start,
                 "The recent graphs as cards, to open one")
        file.addSeparator()
        add_command(file, "Save", self.save_graph,
                 "Save to the graph's file, asking where only the first time",
                 "Ctrl+S")
        add_command(file, "Save As…", self.save_graph_as,
                 "Save to a file you choose", "Ctrl+Shift+S")
        edit = menus.addMenu("Edit")
        add_command(edit, "Undo", self.undo, "", "Ctrl+Z")
        add_command(edit, "Redo", self.redo, "", "Ctrl+Y")
        edit.addSeparator()
        add_command(edit, "Copy", self.copy_selected, "", "Ctrl+C")
        add_command(edit, "Paste", self.paste, "", "Ctrl+V")
        add_command(edit, "Delete", self.remove_selected, "", "Del")
        edit.addSeparator()
        add_command(edit, "Group", self.group_selected,
                 "Draw the selected components together on a background",
                 "Ctrl+G")
        add_command(edit, "Ungroup", self.ungroup_selected,
                 "End the groups of the selected components", "Ctrl+Shift+G")
        edit.addSeparator()
        add_command(edit, "Hide", self.hide,
                 "Hide the selected components in the viewports", "Ctrl+H")
        add_command(edit, "Show", self.show_hidden,
                 "Show them again; all hidden ones with none selected",
                 "Ctrl+Shift+H")
        return menus

    def component_menu(self, at):
        menu = QMenu(self)
        for category in CATEGORIES:
            menu.addSection(category)
            for comp in COMPONENTS.values():
                if comp.category == category:
                    action = menu.addAction(comp.title)
                    icon = component_icon(comp)
                    if icon is not None:
                        action.setIcon(icon)
                    action.setToolTip(comp.description)
                    action.triggered.connect(
                        lambda checked=False, k=comp.key:
                        self.add_component(k, at))
        return menu

    def show_menu(self, scene_pos, screen_pos):
        """A port's menu over a port, a component's over a component, the
        add menu elsewhere."""
        port = self.canvas.scene()._port_at(scene_pos)
        item = self.canvas.scene()._node_at(scene_pos)
        group = self.canvas.group_at(scene_pos)
        if port is None and group is not None:
            self.group_menu(group).exec(screen_pos)
            return
        if port is None and item is not None:
            # an input's name counts as the input
            port = item.port_at(item.mapFromScene(scene_pos))
        if port is not None:
            self.port_menu(port).exec(screen_pos)
            return
        if item is None:
            self.find_component(scene_pos, screen_pos)
            return
        self.node_menu(item).exec(screen_pos)

    def find_component(self, scene_pos, screen_pos):
        """A field to type a component's name into, opened where the
        canvas was clicked; what is chosen is put there."""
        search = ComponentSearch(self)
        search.chosen.connect(
            lambda key, params: self.add_component(key, scene_pos, params))
        search.move(screen_pos)
        search.show()
        search.field.setFocus()
        self.search = search
        return search

    def port_menu(self, port):
        """Graft, Flatten or Reverse what passes the port."""
        menu = QMenu(self)
        flag = port.flag()
        for name, tip in (("Graft", "Every item on a branch of its own"),
                          ("Flatten", "Every item on one branch")):
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(flag == name.lower())
            action.setToolTip(tip)
            action.triggered.connect(
                lambda on, f=name.lower(): self.set_flag(port, f if on
                                                         else None))
        menu.addSeparator()
        reverse = menu.addAction("Reverse")
        reverse.setCheckable(True)
        reverse.setChecked("reverse" in port.flags())
        reverse.setToolTip("Each branch the other way round")
        reverse.triggered.connect(lambda on: self.set_reverse(port, on))
        if not port.is_output:
            menu.addSeparator()
            keep = menu.addAction("Internalize",
                                  lambda: self.internalize_input(port))
            keep.setToolTip("Keep what comes in as the input's own, "
                            "and let the wires go")
            keep.setEnabled(bool(len(self.graph.wired_tree(
                port.node_id, port.port.name, self.results))))
        return menu

    def set_flag(self, port, flag):
        """Graft, Flatten, or neither, on a port; a Reverse stays."""
        keep = [f for f in port.flags() if f == "reverse"]
        self._store_flags(port, keep + ([flag] if flag else []))

    def set_reverse(self, port, on):
        """Reverse on a port, or off, beside its Graft or Flatten."""
        keep = [f for f in port.flags() if f != "reverse"]
        self._store_flags(port, keep + (["reverse"] if on else []))

    def _store_flags(self, port, names):
        node = port.node_item.node
        flags = node.params.setdefault("flags", {})
        key = hydra.flag_key(port.port.name, port.is_output)
        names = hydra.flags_of(names)
        if not names:
            flags.pop(key, None)
        else:
            # one flag as its name, as files have kept it, more as a list
            flags[key] = names[0] if len(names) == 1 else names
        if not flags:
            node.params.pop("flags")
        port.node_item.relayout()
        self.solve()

    def node_menu(self, item):
        menu = QMenu(self)
        node = item.node
        field = NameField(node.title)
        field.setToolTip("Its name: type another, Enter to keep it; left "
                         "empty, the component's own comes back")
        named = QWidgetAction(menu)
        named.setDefaultWidget(field)
        menu.addAction(named)

        def keep():
            self.rename(node.id, field.text())
        field.editingFinished.connect(keep)
        field.returnPressed.connect(menu.close)
        menu.addSeparator()
        menu.name_field = field
        if node.component.sets:
            # Set Crv... for a curve, Set Vector... for a vector
            command = "hydraset" if node.component.picks else "hydravector"
            menu.addAction(f"{node.component.sets}...",
                           lambda: self.pick(node.id, command))
            if node.component.picks:
                keep = menu.addAction("Internalize",
                                      lambda: self.internalize(node.id))
                keep.setToolTip("Keep the picked objects as the graph's own "
                                "copy, whatever happens to them in the model")
                keep.setEnabled(any(
                    self.window.scene.get(oid) is not None
                    for oid in node.params.get("refs", [])))
            menu.addSeparator()
        item.add_menu_entries(menu)
        if any(p.kind in GEOMETRY_KINDS or p.kind == "any"
               for p in node.component.outputs):
            cast = menu.addAction("Cast...", lambda: self.cast(node.id))
            cast.setToolTip("Add what this component makes to the model")
            cast.setEnabled(bool(self.cast_shapes(self._casting(node.id))))
            menu.addSeparator()
        if item.can_hide():
            if item.is_hidden():
                act = menu.addAction(
                    "Show", lambda: self.show_hidden(self._casting(node.id)))
                act.setShortcut(QKeySequence("Ctrl+Shift+H"))
                act.setToolTip("Show it in the viewports again")
            else:
                act = menu.addAction(
                    "Hide", lambda: self.hide(self._casting(node.id)))
                act.setShortcut(QKeySequence("Ctrl+H"))
                act.setToolTip("Hide it in the viewports")
        menu.addAction("Delete", lambda: self.remove_nodes([node.id]))
        return menu

    # -------------------------------------------------------------- casting

    def _casting(self, node_id):
        """The component right-clicked, with the rest of the selection when
        it is one of several selected."""
        selected = self.selected_ids()
        return selected if node_id in selected else [node_id]

    def cast_shapes(self, node_ids):
        """The geometry these components hand on, ready to be cast."""
        shapes = []
        for nid in node_ids:
            result = self.results.get(nid)
            if result is None:
                continue
            for port in self.graph.nodes[nid].component.outputs:
                if port.kind in GEOMETRY_KINDS or port.kind == "any":
                    # only what it carries that is geometry can be cast; a
                    # group stays one, to be one of the model's groups
                    shapes.extend(v for v in result.outputs.get(port.name, [])
                                  if hydra.fits("geometry", v))
        return shapes

    def cast(self, node_id):
        """Ask for a layer, and whether to group, then cast."""
        node_ids = self._casting(node_id)
        shapes = self.cast_shapes(node_ids)
        if not shapes:
            return []
        dialog = CastDialog(self.window.scene.layers,
                            len(hydra.shapes_in(shapes)),
                            bool(self.window.cfg.get("hydra_cast_group",
                                                     default=False)), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return []
        group = dialog.group.isChecked()
        if len(shapes) > 1:
            self.window.cfg.set("hydra_cast_group", group)
        return self.cast_into(node_ids, dialog.layer_id(), group)

    def cast_into(self, node_ids, layer_id, group=False):
        """Cast onto a layer, as one undo step: the objects are the model's
        from then on, and no longer follow the graph."""
        shapes = self.cast_shapes(node_ids)
        if not shapes:
            return []
        if self.window.processor.busy:
            self.status.setText("Finish or cancel the active command first")
            return []
        from ...core.mesh import MeshShape
        from ...core.text_object import TextShape
        from ...script_runtime import isolated_copy
        scene = self.window.scene
        self.window.history.checkpoint("Hydra: Cast")
        def model_copy(shape):
            # a mesh goes in as flat triangles, the way the graph shows it,
            # and lettering as text to edit, not as its outlines
            if isinstance(shape, MeshShape):
                return hydra.faceted(shape)
            if isinstance(shape, TextShape):
                return shape.copy()
            return isolated_copy(shape)
        objects, kept = [], []
        for value in shapes:
            members = [scene.add(model_copy(shape), layer_id=layer_id)
                       for shape in hydra.shapes_in([value])]
            objects.extend(members)
            if isinstance(value, hydra.GeometryGroup) and len(members) > 1:
                kept.append([obj.id for obj in members])
        ids = [obj.id for obj in objects]
        if group and len(ids) > 1:
            # all of it one group, groups and all
            scene.update_many(ids, group_id=uuid.uuid4().hex[:8])
        else:
            for members in kept:
                scene.update_many(members, group_id=uuid.uuid4().hex[:8])
        self.window.selection.set(ids)
        said = f"{len(ids)} object" + ("" if len(ids) == 1 else "s")
        where = scene.layers.full_path(layer_id)
        self.window.command_line.echo(
            f"Hydra cast {said} onto {where}"
            + (", grouped" if group and len(ids) > 1 else ""))
        self.status.setText(f"Cast {said}")
        return objects

    def type_panel(self, item):
        """A field over a panel to type its text into; a panel that shows
        what is wired into it has nothing of its own to type."""
        if self.graph.input_values(item.node.id, item.inputs[0].port,
                                   self.results)[1]:
            self.status.setText("It shows what comes in: take the wire "
                                "away to type into it")
            return None
        view = self.canvas
        field = PanelField(item.node.params.get("text", ""), view.viewport())
        field.setGeometry(view.mapFromScene(
            item.mapToScene(item.panel_area())).boundingRect())
        field.show()
        field.setFocus()
        self.panel_field = field

        def done(keep):
            if self.panel_field is not field:
                return
            self.panel_field = None
            if keep and field.toPlainText() != item.node.params.get("text"):
                item.node.params["text"] = field.toPlainText()
                item.update()
                self.changed()
            field.deleteLater()
            view.setFocus()

        field.finished.connect(done)
        return field

    def rename(self, node_id, name):
        """A component's own name, shown beside its icon; empty, it has its
        component's again."""
        node = self.graph.nodes.get(node_id)
        if node is None:
            return
        before = node.title
        node.rename(name)
        if node.title == before:
            return
        item = self.canvas.node_items[node_id]
        item.relayout()
        item.set_result(item.result)
        self.changed()

    def align(self, how):
        """Line up the chosen components as the align bar's button `how`
        says, as one step."""
        chosen = self.canvas.chosen_items()
        if len(chosen) < 2:
            return
        boxes = [(i.x(), i.y(), i.width, i.height) for i in chosen]
        for item, (x, y) in zip(chosen, arranged(boxes, how)):
            item.setPos(x, y)
        self.canvas.align_bar.follow()
        self.changed()

    def flip(self, node_id):
        """A Boolean Toggle switched to the other value."""
        node = self.graph.nodes[node_id]
        node.params["value"] = not node.params.get("value")
        self.canvas.node_items[node_id].update()
        self.changed()

    def pipe_menus(self, menu, node):
        """A Geometry Pipeline's layer and its types to take."""
        scene = self.window.scene
        layers = menu.addMenu("Layer")
        group = QActionGroup(layers)
        chosen = node.params.get("layer")
        for path in [None] + [scene.layers.full_path(layer.id)
                              for layer in scene.layers.all()]:
            action = layers.addAction("All layers" if path is None else path)
            action.setCheckable(True)
            action.setChecked(path == chosen)
            group.addAction(action)
            action.triggered.connect(
                lambda checked=False, p=path: self.set_pipe(node.id, layer=p))
        types = menu.addMenu("Types")
        for key, title in (("point", "Points"), ("curve", "Curves"),
                           ("brep", "Breps"), ("mesh", "Meshes")):
            action = types.addAction(title)
            action.setCheckable(True)
            action.setChecked(key in node.params.get("types", ()))
            action.triggered.connect(
                lambda on, k=key: self.set_pipe(node.id, kind=k, on=on))

    def set_pipe(self, node_id, layer=..., kind=None, on=True):
        """A Geometry Pipeline's layer (None: all of them), or one of its
        types taken or left."""
        params = self.graph.nodes[node_id].params
        if layer is not ...:
            params["layer"] = layer
        if kind is not None:
            kept = [t for t in params.get("types", []) if t != kind]
            params["types"] = [t for t in hydra.PIPE_TYPES
                               if t in kept or (on and t == kind)]
        self.changed()

    def change_range(self, item):
        dialog = RangeDialog(item.node.params, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.set_range(item, *dialog.values())

    def set_range(self, item, low, high, places):
        # the decimal places are the ones the range was typed to
        hydra.set_range(item.node.params, low, high)
        self.set_decimals(item, places)

    def type_value(self, item):
        """A field over the slider to type a value, or a range as 0.0-12."""
        view = self.canvas
        field = ValueField(item.value_text(), view.viewport())
        x0, _x1 = item._rail()
        area = QRectF(x0, 2, item.width - x0 - VALUE_GAP, NODE_HEIGHT - 4)
        field.setGeometry(view.mapFromScene(
            item.mapToScene(area)).boundingRect())
        field.show()
        field.setFocus()
        field.selectAll()
        self.value_field = field

        def close():
            field._done = True
            self.value_field = None
            field.deleteLater()
            view.setFocus()

        def commit(leaving):
            try:
                self.status.objectName()
            except RuntimeError:
                return               # Hydra closed while the field was open
            if self.canvas.node_items.get(item.node.id) is not item:
                close()              # its component gone, by undo or delete
                return
            try:
                hydra.type_into_slider(item.node.params, field.text())
            except (ValueError, HydraError):
                if leaving:
                    close()
                    return
                self.status.setText("Type a number such as 5, or a range "
                                    "such as 0.0-12")
                field.selectAll()
                return
            self.status.setText("")
            item.set_result(item.result)
            self.changed()
            close()

        field.committed.connect(commit)
        field.cancelled.connect(close)
        return field

    def set_decimals(self, item, places):
        hydra.set_decimals(item.node.params, places)
        item.set_result(item.result)
        self.changed()

    def start_placing(self, key):
        """A component clicked in the node bar waits on the cursor, its icon
        with a plus, until the canvas is clicked where it is to go; Escape
        or the right button puts it back."""
        self.placing = key
        self.canvas.viewport().setCursor(placing_cursor(COMPONENTS[key]))
        self.status.setText(f"Click on the canvas to place "
                            f"{COMPONENTS[key].title} · Esc to cancel")

    def stop_placing(self):
        if self.placing is None:
            return
        self.placing = None
        self.canvas.viewport().unsetCursor()
        self.status.setText("")

    def place(self, at):
        """The component waiting on the cursor, put down with its middle at
        `at`."""
        key = self.placing
        self.stop_placing()
        _labels, width, height = node_size(COMPONENTS[key])
        return self.add_component(key, at - QPointF(width / 2, height / 2))

    def add_component(self, key, at=None, params=None):
        """A component on the canvas, at `at` or in the middle, set up
        with `params` when given, as one step."""
        if at is None:
            at = self.canvas.mapToScene(self.canvas.viewport().rect().center())
            _labels, width, _height = node_size(COMPONENTS[key])
            at -= QPointF(width / 2, NODE_HEIGHT / 2)
        x, y = (at.x(), at.y()) if isinstance(at, QPointF) else at
        node = self.graph.add_node(key, x, y, params)
        self.show_canvas()
        self.canvas.add_item(node)
        self.changed()
        return node

    def pick(self, node_id, command="hydraset"):
        """Set a component by picking in the model: objects with the usual
        selection, or for a Vector its two points."""
        self.picking = node_id
        self.window.activateWindow()
        self.window.run_command(command)

    def set_inputs(self, node_id, values):
        """Points picked in the model for inputs no wire feeds."""
        node = self.graph.nodes.get(node_id)
        if node is None:
            return
        node.params["set"] = {name: list(v) for name, v in values.items()}
        for name in values:
            # picked anew, it no longer holds what was internalized
            node.set_internal(name, None)
        self.solve()

    def set_references(self, node_id, ids):
        node = self.graph.nodes.get(node_id)
        if node is None:
            return
        node.params["refs"] = list(ids)
        node.set_internal("out", None)       # the model's objects again
        self.solve()

    def internalize(self, node_id):
        """A geometry component's objects kept as the graph's own copy."""
        try:
            count = self.graph.internalize(node_id, self.window.scene)
        except HydraError as exc:
            self.status.setText(str(exc))
            return 0
        self.status.setText(f"Internalized {count} object"
                            + ("" if count == 1 else "s"))
        self.solve()
        return count

    def internalize_input(self, port):
        """What comes into an input kept as its own, the wires let go."""
        try:
            count = self.graph.internalize_input(port.node_id,
                                                 port.port.name, self.results)
        except HydraError as exc:
            self.status.setText(str(exc))
            return 0
        self.canvas.sync_wires()
        self.status.setText(f"Internalized {count} item"
                            + ("" if count == 1 else "s")
                            + f" into {port.port.name}")
        self.solve()
        return count

    def connect(self, source, output, target, input, add=False):
        """A wire into an input, in place of the one there, or with `add`
        beside it."""
        try:
            wire = self.graph.connect(source, output, target, input, add=add)
        except HydraError as exc:
            self.status.setText(str(exc))
            return None
        self.canvas.sync_wires()
        self.changed()
        return wire

    def remove_wire(self, source, output, target, input):
        """Take away the wire from that output into that input: what a wire
        drawn over it with Ctrl does."""
        wire = self.graph.wire_between(source, output, target, input)
        if wire is None:
            self.status.setText("No wire runs there to take away")
            return False
        self.disconnect(wire)
        self.status.setText("Wire taken away")
        return True

    def disconnect(self, wire):
        self.graph.disconnect(wire)
        self.canvas.sync_wires()
        self.changed()

    def wire_into(self, port_item):
        for wire in reversed(self.graph.wires):
            if (wire.target == port_item.node_id
                    and wire.input == port_item.port.name):
                return wire
        return None

    def remove_nodes(self, node_ids):
        for nid in node_ids:
            self.graph.remove_node(nid)
            self.canvas.remove_item(nid)
        self.canvas.sync_wires()
        self.canvas.sync_groups()
        self.changed()

    def selected_ids(self):
        return [i.node.id for i in self.canvas.scene().selectedItems()
                if isinstance(i, NodeItem)]

    def copy_selected(self):
        """The selected components and the wires between them, onto the
        clipboard."""
        ids = self.selected_ids()
        if not ids:
            return False
        data = QMimeData()
        data.setData(CLIPBOARD, json.dumps(self.graph.part(ids)).encode())
        QApplication.clipboard().setMimeData(data)
        self.status.setText(f"Copied {len(ids)} component"
                            + ("" if len(ids) == 1 else "s"))
        return True

    def paste(self):
        """What was copied, under the cursor if it is over the canvas, a
        step down and right of where it was if not."""
        mime = QApplication.clipboard().mimeData()
        if mime is None or not mime.hasFormat(CLIPBOARD):
            return []
        try:
            part = json.loads(bytes(mime.data(CLIPBOARD)).decode())
        except ValueError:
            return []
        nodes = part.get("nodes", [])
        if not nodes:
            return []
        left = min(n.get("x", 0.0) for n in nodes)
        top = min(n.get("y", 0.0) for n in nodes)
        cursor = self.canvas.mapFromGlobal(QCursor.pos())
        if self.canvas.viewport().rect().contains(cursor):
            at = self.canvas.mapToScene(cursor)
            dx, dy = at.x() - left, at.y() - top
        else:
            dx = dy = PASTE_STEP
        return self._place(part, dx, dy)

    def duplicate(self, node_ids, dx=0.0, dy=0.0):
        """Copies of components where they stand, wired among themselves."""
        return self._place(self.graph.part(node_ids), dx, dy)

    def _place(self, part, dx, dy):
        fresh = self.graph.paste(part, dx, dy)
        self.canvas.scene().clearSelection()
        for nid in fresh:
            self.canvas.add_item(self.graph.nodes[nid]).setSelected(True)
        self.canvas.sync_wires()
        self.canvas.sync_groups()
        self.solve()
        return fresh

    def group_menu(self, group):
        """A group's name to type, empty while it has none, and Ungroup."""
        menu = QMenu(self)
        field = NameField(group.name())
        field.setPlaceholderText("Name the group")
        field.setToolTip("Its name, written over it: type one, Enter to keep "
                         "it; left empty, it has none")
        named = QWidgetAction(menu)
        named.setDefaultWidget(field)
        menu.addAction(named)
        field.editingFinished.connect(
            lambda: self.name_group(group.group_id, field.text()))
        field.returnPressed.connect(menu.close)
        menu.addSeparator()
        # the components chosen, put in this group too
        chosen = [nid for nid in self.selected_ids()
                  if nid not in self.graph.groups.get(group.group_id, [])]
        add = menu.addAction("Add to Group",
                             lambda: self.add_to_group(group.group_id, chosen))
        add.setEnabled(bool(chosen))
        add.setToolTip("Put the selected components in this group too")
        menu.addAction("Ungroup", lambda: self.ungroup(group.group_id))
        menu.name_field = field
        return menu

    def name_group(self, group_id, name):
        """A group's name, written over it; empty, it has none."""
        before = self.graph.group_names.get(group_id, "")
        if (name or "").strip() == before:
            return
        item = self.canvas.group_items.get(group_id)
        if item is not None:
            # its name widens it: Qt is told before, to draw it whole
            item.prepareGeometryChange()
        self.graph.name_group(group_id, name)
        if item is not None:
            item.update()
        self.changed()

    def add_to_group(self, group_id, node_ids):
        if not self.graph.add_to_group(group_id, node_ids):
            return
        self.canvas.sync_groups()
        self.changed()

    def ungroup(self, group_id):
        self.graph.ungroup(group_id)
        self.canvas.sync_groups()
        self.changed()

    def group_selected(self):
        """The selected components in a group of their own."""
        if self.graph.group(self.selected_ids()) is None:
            return
        self.canvas.sync_groups()
        self.changed()

    def ungroup_selected(self):
        """The chosen group ended, or those of the selected components."""
        chosen = self.canvas.chosen_group
        gids = ({chosen.group_id} if chosen is not None else
                {self.graph.group_of(nid) for nid in self.selected_ids()})
        gids.discard(None)
        if not gids:
            return
        for gid in gids:
            self.graph.ungroup(gid)
        self.canvas.sync_groups()
        self.changed()

    def remove_selected(self):
        if self.canvas.chosen_group is not None:
            # Delete on a group's background ends the grouping, and only that
            self.ungroup_selected()
            return
        selected = self.canvas.scene().selectedItems()
        for wire in [i.wire for i in selected if isinstance(i, WireItem)]:
            self.graph.disconnect(wire)
        self.remove_nodes([i.node.id for i in selected
                           if isinstance(i, NodeItem)])

    def set_preview(self, node_id, shown):
        self.graph.nodes[node_id].preview = shown
        self.canvas.node_items[node_id].update()
        self.changed()

    def hide(self, node_ids=None):
        """Take these components out of the viewports: the selection if
        none are named."""
        self._set_hidden(self.selected_ids() if node_ids is None
                         else node_ids, True)

    def show_hidden(self, node_ids=None):
        """Put these components back in the viewports. With none named, the
        selection, or every hidden one when nothing is selected, as Show
        does for the model's objects."""
        if node_ids is None:
            node_ids = self.selected_ids() or list(self.graph.nodes)
        self._set_hidden(node_ids, False)

    def _set_hidden(self, node_ids, hidden):
        items = [self.canvas.node_items[nid] for nid in node_ids]
        items = [item for item in items
                 if item.can_hide() and item.is_hidden() != hidden]
        if not items:
            return
        for item in items:
            item.node.preview = not hidden
            item.update()
        self.status.setText(("Hidden" if hidden else "Shown")
                            + f" {len(items)} component"
                            + ("" if len(items) == 1 else "s"))
        self.changed()

    # ------------------------------------------------------------- solving

    def changed(self):
        # a step for Ctrl+Z at once, so two changes in quick succession
        # stay two steps
        self.record()
        # At most one solve per tick, not one once the changes stop: a
        # slider dragged without a pause has to show while it moves.
        if not self._timer.isActive():
            self._timer.start()

    def solve(self):
        self._timer.stop()
        self.results = self.graph.solve(self.window.scene)
        for nid, item in self.canvas.node_items.items():
            item.set_result(self.results.get(nid))
        self.canvas.style_wires(self.results)
        self.shapes = self.graph.preview_shapes(self.results)
        self._show_preview()
        if not self.graph.nodes:
            self.status.setText("Double-click the canvas to add a component")
        else:
            self.status.setText("")
        self.record()

    # ------------------------------------------------------------ undo, redo

    def record(self):
        """A step for Ctrl+Z when the graph is not as it was after the last
        one. A knob still being dragged is not a step yet: the drag as a
        whole is, when it is let go."""
        if not hasattr(self, "_undo") or self._restoring:
            return
        if any(item.mid_drag for item in self.canvas.node_items.values()):
            return
        now = self.graph.to_dict()
        if now == self._state:
            return
        self._undo.append(self._state)
        del self._undo[:-UNDO_STEPS]
        self._redo.clear()
        self._state = now

    def forget_steps(self):
        """A graph opened or begun anew starts a history of its own."""
        self._undo, self._redo = [], []
        self._state = self.graph.to_dict()

    def undo(self):
        return self._step(self._undo, self._redo, "Undone")

    def redo(self):
        return self._step(self._redo, self._undo, "Redone")

    def _step(self, source, target, said):
        self.record()                # a change not yet a step becomes one
        if not source:
            self.status.setText("Nothing to " + said[:-2].lower())
            return False
        target.append(self._state)
        self._state = source.pop()
        self._restoring = True
        try:
            self.load(self._state)
        finally:
            self._restoring = False
        self.status.setText(said)
        return True

    def set_active(self, active: bool):
        """A closed editor shows nothing in the model."""
        self.active = active
        self._show_preview()

    def _selection_changed(self):
        try:
            self._show_preview()
        except RuntimeError:
            pass                     # the window this belonged to is gone

    def _show_preview(self):
        """The graph in the model: violet, and what the selected components
        make in green instead, hidden ones too, so the selection shows."""
        scene = self.window.scene
        chosen = set(self.selected_ids()) if self.active else set()
        shown = self.graph.preview_shapes(
            self.results, only=set(self.graph.nodes) - chosen)
        picked = (self.graph.preview_shapes(self.results, only=chosen,
                                            hidden=True) if chosen else [])
        scene.hydra_preview = (self.meshes.overlay(shown)
                               if self.active and shown else None)
        scene.hydra_selected = (self.selected_meshes.overlay(picked)
                                if picked else None)
        for viewport in self.window.all_viewports():
            viewport.update()

    # --------------------------------------------------------- persistence

    def load(self, data: dict):
        if hasattr(self, "pages"):
            self.show_canvas()
        for nid in list(self.canvas.node_items):
            self.canvas.remove_item(nid)
        for item in self.canvas.wire_items:
            self.canvas.scene().removeItem(item)
        self.canvas.wire_items = []
        self.graph = Graph.from_dict(data)
        for node in self.graph.nodes.values():
            self.canvas.add_item(node)
        self.canvas.sync_wires()
        self.canvas.sync_groups()
        self.solve()

    def new_graph(self):
        self.load({})
        self.set_path(None)
        self.forget_steps()

    def set_path(self, path):
        """The file Save writes to, named in the Hydra window's title."""
        self.path = path
        dock = self.parentWidget()
        if isinstance(dock, QDockWidget):
            dock.setWindowTitle("Hydra" if path is None
                                else f"Hydra · {os.path.basename(path)}")

    def save_graph(self):
        """Into the graph's own file once it has one, asking only before."""
        if self.path and os.path.exists(self.path):
            return self._write(self.path)
        return self.save_graph_as()

    def save_graph_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Hydra Graph", self.path or "", "Hydra graph (*.hydra)")
        if not path:
            return False
        return self._write(path)

    def _write(self, path):
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.graph.to_dict(), fh, indent=1)
        except OSError as exc:
            self.status.setText(f"Could not save: {exc}")
            return False
        self.set_path(path)
        self._remember(path)
        self.status.setText(f"Saved {os.path.basename(path)}")
        return True

    def open_graph(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Hydra Graph", os.path.dirname(self.path or ""),
            "Hydra graph (*.hydra)")
        if path:
            self.open_path(path)

    def open_path(self, path):
        """A .hydra file, from the dialog or double-clicked outside."""
        path = os.path.abspath(path)
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as exc:
            self.status.setText(f"Could not open: {exc}")
            return False
        self.load(data if isinstance(data, dict) else {})
        self.set_path(path)
        self._remember(path)
        self.forget_steps()
        return True

    # ---------------------------------------------------------- start page

    def recent(self):
        """The .hydra files last saved or opened, newest first, those still
        there."""
        paths = self.window.cfg.get("hydra_recent", default=[])
        return [p for p in paths if isinstance(p, str) and os.path.exists(p)]

    def _remember(self, path):
        from ...utils.config import push_recent
        self.window.cfg.set("hydra_recent", push_recent(
            self.window.cfg.get("hydra_recent", default=[]), path))

    def show_start(self):
        """The graph being worked on and the recent ones, as cards; the
        empty canvas only when there is neither. The graph being worked on
        is offered to continue only when it is not its file's as saved:
        then the file's own card is the same thing."""
        current = (self.graph.to_dict()
                   if self.graph.nodes and self.unsaved() else None)
        recent = self.recent()
        if current is None and not recent:
            self.show_canvas()
            return False
        self.start.fill(current, recent)
        self.pages.setCurrentWidget(self.start)
        self.start.setFocus()
        return True

    def unsaved(self):
        """Whether the graph holds anything its file does not: never saved,
        its file gone, or changed since it was saved."""
        if self.path is None or not os.path.exists(self.path):
            return True
        saved = read_graph(self.path)
        return saved != json.loads(json.dumps(self.graph.to_dict()))

    def show_canvas(self):
        self.pages.setCurrentWidget(self.canvas)

    def starting(self):
        return self.pages.currentWidget() is self.start

    def eventFilter(self, obj, event):
        kind = event.type()
        if (kind == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape
                and getattr(self, "placing", None) is not None):
            self.stop_placing()
            return True
        # Ctrl+S, and Ctrl+Shift+S, typed anywhere in Hydra save the graph,
        # not the model the main window would
        if kind in (QEvent.Type.ShortcutOverride, QEvent.Type.KeyPress):
            save = save_key(event)
            if save is not None and self._holds(obj):
                if kind == QEvent.Type.KeyPress and save == "as":
                    self.save_graph_as()
                elif kind == QEvent.Type.KeyPress:
                    self.save_graph()
                event.accept()
                return True
            # in a text field they undo the typing, as they always do
            step = undo_key(event)
            if (step is not None and self._holds(obj)
                    and not isinstance(obj, QLineEdit)):
                if kind == QEvent.Type.KeyPress and step == "undo":
                    self.undo()
                elif kind == QEvent.Type.KeyPress:
                    self.redo()
                event.accept()
                return True
        if kind in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            flag = MODIFIER_OF.get(event.key())
            if flag is not None and not event.isAutoRepeat():
                mods = event.modifiers()
                # whether the key's own flag is in yet differs by platform
                mods = (mods | flag if kind == QEvent.Type.KeyPress
                        else mods & ~flag)
                self._modifiers_changed(mods)
        elif kind == QEvent.Type.ApplicationDeactivate:
            # let go in another program, a key would stay held here
            self._modifiers_changed(Qt.KeyboardModifier.NoModifier)
        return False

    def _holds(self, obj):
        """Whether a widget is Hydra's: the editor or anything in it, the
        search and the value field that float above it included."""
        try:
            floating = (getattr(self, "search", None),
                        getattr(self, "value_field", None))
            return isinstance(obj, QWidget) and (
                obj is self or self.isAncestorOf(obj)
                or any(obj is f for f in floating if f is not None))
        except RuntimeError:
            return False

    def _modifiers_changed(self, mods):
        try:
            self.canvas.scene().modifiers_changed(mods)
        except RuntimeError:
            pass        # the window this belonged to is gone

    def shutdown(self):
        QApplication.instance().removeEventFilter(self)
        self.window.cfg.set("hydra_graph", self.graph.to_dict())
        self.window.cfg.set("hydra_path", self.path)
        self.set_active(False)
