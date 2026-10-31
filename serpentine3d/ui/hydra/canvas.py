"""The canvas: wiring, copying and moving components, panning and
zooming."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QKeySequence, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView

from ...core import hydra
from ...core.hydra import COMPONENTS
from .align import AlignBar
from .groups import GroupItem
from .items import NodeItem, PortItem, WireItem
from .special import item_for, node_size
from .keys import hide_key, wiring_mode
from .style import ACCENT, COMPONENT_MIME


PAN_SLOP = 4                # pixels a right drag moves before it pans


SNAP_REACH = 26             # screen pixels a dropped wire finds a port within
ALIGN_REACH = 6             # screen pixels a dragged component lines up within
NEAR = 300                  # screen pixels another has to be within to line up


class HydraScene(QGraphicsScene):
    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        self._drag = None          # (fixed PortItem, WireItem)
        self._target = None        # the port a dragged wire would dock on
        self._mode = None          # what letting the dragged wire go would do
        self._last = None          # where the cursor last was, dragging
        # Shift and Ctrl as they stand, kept here rather than asked of Qt,
        # whose answer lags a key let go
        self.modifiers = Qt.KeyboardModifier.NoModifier
        self._copying = None       # (press point, {NodeItem: start}) Alt-drag
        self._guides = []          # the lines a dragged component is aligned on
        self.setBackgroundBrush(QColor("#232427"))

    def drawBackground(self, painter, rect):
        super().drawBackground(painter, rect)
        step = 24
        painter.setPen(QPen(QColor(255, 255, 255, 14), 1))
        x = int(rect.left()) - int(rect.left()) % step
        while x < rect.right():
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += step
        y = int(rect.top()) - int(rect.top()) % step
        while y < rect.bottom():
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += step

    def drawForeground(self, painter, rect):
        if not self._guides:
            return
        pen = QPen(ACCENT, 0, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.drawLines(self._guides)

    def _align(self, grabbed, moving):
        """Line the dragged components up: the one held by the cursor moves
        the little it takes for an edge or its middle to meet another's, or
        for a wire to it to run straight; the rest go with it."""
        scale = max(self.canvas.transform().m11(), 1e-6)
        reach = ALIGN_REACH / scale
        mine = _box(grabbed)
        # only what is on the screen and near: one far off, lined up by
        # chance, would pull it about along a line no one sees
        view = self.canvas
        shown = view.mapToScene(view.viewport().rect()).boundingRect()
        near = mine.adjusted(-NEAR / scale, -NEAR / scale,
                             NEAR / scale, NEAR / scale)
        others = [box for box in (_box(item)
                                  for item in self.canvas.node_items.values()
                                  if item not in moving)
                  if box.intersects(near) and box.intersects(shown)]
        best = {"x": None, "y": None, "wire": None}

        def offer(axis, gap, guide):
            if abs(gap) <= reach and (best[axis] is None
                                      or abs(gap) < abs(best[axis][0])):
                best[axis] = (gap, guide)

        for other in others:
            for at in _xs(mine):
                for there in _xs(other):
                    offer("x", there - at, ("x", there, mine, other))
            for at in _ys(mine):
                for there in _ys(other):
                    offer("y", there - at, ("y", there, mine, other))
        # a wire from or to a component staying put runs straight, before
        # any edge lines up
        for a, b in self._wired_ports(grabbed, moving):
            offer("wire", b.scenePos().y() - a.scenePos().y(),
                  ("wire", a, b))
        if best["wire"] is not None:
            best["y"], best["wire"] = best["wire"], None
        dx = best["x"][0] if best["x"] else 0.0
        dy = best["y"][0] if best["y"] else 0.0
        for item in moving:
            item.moveBy(dx, dy)
        self._guides = [_guide(found[1], dx, dy)
                        for found in best.values() if found is not None]
        self.update()

    def _wired_ports(self, grabbed, moving):
        """The ports of the held component, each with the port at the
        other end of a wire to a component that is not moving."""
        items = self.canvas.node_items
        still = {nid for nid, item in items.items() if item not in moving}
        pairs = []
        for wire in self.canvas.editor.graph.wires:
            if wire.target == grabbed.node.id and wire.source in still:
                pairs.append((grabbed.port(wire.input, False),
                              items[wire.source].port(wire.output, True)))
            elif wire.source == grabbed.node.id and wire.target in still:
                pairs.append((grabbed.port(wire.output, True),
                              items[wire.target].port(wire.input, False)))
        return [(a, b) for a, b in pairs if a is not None and b is not None]

    def _moving(self, grabbed):
        if grabbed.isSelected():
            return [i for i in self.selectedItems() if isinstance(i, NodeItem)]
        return [grabbed]

    def _port_at(self, pos):
        for item in self.items(pos):
            if isinstance(item, PortItem):
                return item
        return None

    def _node_at(self, pos):
        for item in self.items(pos):
            while item is not None and not isinstance(item, NodeItem):
                item = item.parentItem()
            if item is not None:
                return item
        return None

    def _dock_at(self, pos, port):
        """Where a wire dragged from `port` would dock if let go at `pos`:
        the nearest port of the other kind within reach of the cursor, or,
        over a component, its nearest port that takes what the wire
        carries."""
        reach = SNAP_REACH / max(self.canvas.transform().m11(), 1e-6)
        mine = port.node_item

        def far(other):
            d = other.scenePos() - pos
            return (d.x() ** 2 + d.y() ** 2) ** 0.5

        def wired(other):
            out, inp = (port, other) if port.is_output else (other, port)
            return self.canvas.editor.graph.wire_between(
                out.node_id, out.port.name, inp.node_id, inp.port.name)

        def fits(other):
            # to take a wire away, the end it runs to is the one that fits
            if self._mode == "remove":
                return wired(other) is not None
            out, inp = (port, other) if port.is_output else (other, port)
            return hydra.takes(inp.port.kind, out.port.kind)

        ends = [other for item in self.canvas.node_items.values()
                if item is not mine
                for other in (item.inputs if port.is_output else item.outputs)]
        near = [o for o in ends if far(o) <= reach]
        if near:
            # aimed at, a port is the one meant; only a wire being taken
            # away looks past it for the end the wire runs to
            if self._mode == "remove":
                near = [o for o in near if fits(o)] or near
            return min(near, key=far)
        node = self._node_at(pos)
        if node is None or node is mine:
            return None
        own = node.inputs if port.is_output else node.outputs
        fitting = [o for o in own if fits(o)] or own
        return min(fitting, key=far) if fitting else None

    def _show_target(self, target):
        if self._target is not None and self._target is not target:
            self._target.set_highlight(False)
        self._target = target
        if target is not None:
            target.set_highlight(True, self._mode)

    def modifiers_changed(self, modifiers):
        """Shift or Ctrl pressed or let go: hovered ports and a dragged wire
        show at once what they would do now."""
        self.modifiers = modifiers
        if self._drag is not None:
            self._mode = wiring_mode(modifiers)
            self._drag[1].mode = self._mode
            self._drag[1].update()
            if self._last is not None:
                self._follow(self._last)
        self.update()

    def mousePressEvent(self, event):
        if not isinstance(self.itemAt(event.scenePos(),
                                      self.canvas.transform()), GroupItem):
            self.canvas.choose_group(None)
        left = event.button() == Qt.MouseButton.LeftButton
        alt = event.modifiers() & Qt.KeyboardModifier.AltModifier
        node = self._node_at(event.scenePos())
        if left and alt and node is not None:
            self._start_copy(node, event.scenePos())
            event.accept()
            return
        port = self._port_at(event.scenePos())
        if port is not None and left:
            self._mode = wiring_mode(event.modifiers())
            # with Shift or Ctrl a wire is drawn, not one picked up
            wire = (None if port.is_output or self._mode is not None
                    else self.canvas.editor.wire_into(port))
            if wire is not None:
                # picking up a wire by its end: it hangs from its source
                self.canvas.editor.disconnect(wire)
                port = self.canvas.node_items[wire.source].port(wire.output,
                                                               True)
            temp = WireItem()
            temp.mode = self._mode
            self.addItem(temp)
            temp.set_ends(port.scenePos(), event.scenePos())
            self._drag = (port, temp)
            self._last = event.scenePos()
            # taken, or the view starts a selection box under the wire
            event.accept()
            return
        if left and node is not None and event.modifiers() & (
                Qt.KeyboardModifier.ShiftModifier
                | Qt.KeyboardModifier.ControlModifier):
            # Shift or Ctrl and a click take one in or out of the choice,
            # as they do with the model's objects
            node.setSelected(not node.isSelected())
            event.accept()
            return
        super().mousePressEvent(event)

    def _start_copy(self, node, at):
        """Alt-drag: the copies go with the cursor, the originals stay."""
        editor = self.canvas.editor
        chosen = ([i.node.id for i in self.selectedItems()
                   if isinstance(i, NodeItem)] if node.isSelected()
                  else [node.node.id])
        copies = editor.duplicate(chosen)
        self.clearSelection()
        items = [self.canvas.node_items[nid] for nid in copies]
        for item in items:
            item.setSelected(True)
        self._copying = (at, {item: item.pos() for item in items})

    def mouseMoveEvent(self, event):
        if self._copying is not None:
            at, starts = self._copying
            for item, start in starts.items():
                item.setPos(start + event.scenePos() - at)
            held = self._node_at(event.scenePos())
            if held in starts:
                self._align(held, list(starts))
            return
        if self._drag is not None:
            mode = wiring_mode(event.modifiers())
            if mode != self._mode:
                self._mode = self._drag[1].mode = mode
                self._drag[1].update()
            self._follow(event.scenePos())
            return
        super().mouseMoveEvent(event)
        grabbed = self.mouseGrabberItem()
        if (isinstance(grabbed, NodeItem)
                and event.buttons() & Qt.MouseButton.LeftButton
                and not getattr(grabbed, "mid_drag", False)):
            self._align(grabbed, self._moving(grabbed))

    def _follow(self, pos):
        port, temp = self._drag
        self._last = pos
        target = self._dock_at(pos, port)
        self._show_target(target)
        end = pos if target is None else target.scenePos()
        if port.is_output:
            temp.set_ends(port.scenePos(), end)
        else:
            temp.set_ends(end, port.scenePos())

    def mouseReleaseEvent(self, event):
        if self._guides:
            self._guides = []
            self.update()
        if self._copying is not None:
            self._copying = None
            self.canvas.editor.changed()
            return
        if self._drag is not None:
            port, temp = self._drag
            self._mode = wiring_mode(event.modifiers())
            other = self._dock_at(event.scenePos(), port)
            self._drag = self._last = None
            self.removeItem(temp)
            self._show_target(None)
            if other is not None and other.is_output != port.is_output:
                out, inp = (port, other) if port.is_output else (other, port)
                ends = (out.node_id, out.port.name, inp.node_id, inp.port.name)
                if self._mode == "remove":
                    self.canvas.editor.remove_wire(*ends)
                else:
                    self.canvas.editor.connect(*ends,
                                               add=self._mode == "add")
            self._mode = None
            return
        super().mouseReleaseEvent(event)
        # components dragged to a new place
        self.canvas.editor.record()

    def mouseDoubleClickEvent(self, event):
        if self._node_at(event.scenePos()) is None:
            self.canvas.editor.find_component(event.scenePos(),
                                              event.screenPos())
            return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        self.canvas.editor.show_menu(event.scenePos(), event.screenPos())


def _group_key(event):
    """"group" for Ctrl+G, "ungroup" for Ctrl+Shift+G, as in the model."""
    if event.key() != Qt.Key.Key_G:
        return None
    mods = event.modifiers()
    ctrl = Qt.KeyboardModifier.ControlModifier
    shift = Qt.KeyboardModifier.ShiftModifier
    if mods == ctrl:
        return "group"
    if mods == ctrl | shift:
        return "ungroup"
    return None


def _fit_key(event):
    """Ctrl+E, which fits the model to its view, and here the graph."""
    return (event.key() == Qt.Key.Key_E and event.modifiers()
            == Qt.KeyboardModifier.ControlModifier)


def _box(item):
    return QRectF(item.pos().x(), item.pos().y(), item.width, item.height)


def _xs(box):
    return box.left(), box.center().x(), box.right()


def _ys(box):
    return box.top(), box.center().y(), box.bottom()


def _guide(found, dx, dy):
    """The line shown along what a dragged component is aligned on, across
    both components; `found` is as _align offered it, before the move."""
    if found[0] == "wire":
        _kind, a, b = found
        return QLineF(a.scenePos(), b.scenePos())
    kind, there, mine, other = found
    mine = mine.translated(dx, dy)
    both = mine.united(other)
    if kind == "x":
        return QLineF(there, both.top() - 8, there, both.bottom() + 8)
    return QLineF(both.left() - 8, there, both.right() + 8, there)


class HydraCanvas(QGraphicsView):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        # made first: setting the scene up scrolls it, and it follows that
        self.align_bar = AlignBar(self)
        self.node_items: dict[str, NodeItem] = {}
        self.wire_items: list[WireItem] = []
        self.group_items: dict[str, GroupItem] = {}
        self.chosen_group = None   # the GroupItem whose background was clicked
        self.setScene(HydraScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setSceneRect(-5000, -5000, 10000, 10000)
        for policy in (self.setHorizontalScrollBarPolicy,
                       self.setVerticalScrollBarPolicy):
            policy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._pan = None
        # a box drawn with Shift or Ctrl: (add | remove, chosen before,
        # whether it has boxed anything yet)
        self._band = None
        self.setAcceptDrops(True)
        self.scene().selectionChanged.connect(self.align_bar.follow)
        self.scene().selectionChanged.connect(self._components_chosen)

    def sync_groups(self):
        """A background for each of the graph's groups, and no others."""
        groups = self.editor.graph.groups
        for gid in [g for g in self.group_items if g not in groups]:
            item = self.group_items.pop(gid)
            if item is self.chosen_group:
                self.chosen_group = None
            self.scene().removeItem(item)
        for gid in groups:
            if gid not in self.group_items:
                item = GroupItem(self, gid)
                self.scene().addItem(item)
                self.group_items[gid] = item
            self.group_items[gid].refit()

    def group_at(self, pos):
        """The group whose background, or name, is at `pos`, with no
        component over it there."""
        if self.scene()._node_at(pos) is not None:
            return None
        return next((item for item in self.scene().items(pos)
                     if isinstance(item, GroupItem)), None)

    def choose_group(self, item):
        """The group whose background was clicked, chosen alone; None to
        choose none."""
        if item is not None:
            self.scene().clearSelection()
        if self.chosen_group is not None and self.chosen_group is not item:
            self.chosen_group.set_chosen(False)
        self.chosen_group = item
        if item is not None:
            item.set_chosen(True)

    def _components_chosen(self):
        # components chosen and a group chosen do not go together
        if self.chosen_items() and self.chosen_group is not None:
            self.choose_group(None)

    def chosen_items(self):
        return [i for i in self.scene().selectedItems()
                if isinstance(i, NodeItem)]

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.align_bar.follow()

    def _dropped(self, event):
        return event.mimeData().hasFormat(COMPONENT_MIME)

    def dragEnterEvent(self, event):
        if self._dropped(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._dropped(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        if self._dropped(event):
            key = bytes(event.mimeData().data(COMPONENT_MIME)).decode()
            if key in COMPONENTS:
                at = self.mapToScene(event.position().toPoint())
                # the component's middle where it was let go
                _labels, width, height = node_size(COMPONENTS[key])
                self.editor.add_component(
                    key, at - QPointF(width / 2, height / 2))
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def add_item(self, node):
        item = item_for(self.editor, node)
        self.scene().addItem(item)
        self.node_items[node.id] = item
        return item

    def remove_item(self, node_id):
        item = self.node_items.pop(node_id, None)
        if item is not None:
            self.scene().removeItem(item)

    def style_wires(self, results):
        """Each wire drawn by what it carries: a line for one item, two for
        a list, two dashed for a tree."""
        for item in self.wire_items:
            result = results.get(item.wire.source)
            tree = (result.outputs.get(item.wire.output)
                    if result is not None else None)
            carries = tree.shape() if tree is not None else "item"
            if carries != item.carries:
                item.carries = carries
                item.update()

    def sync_wires(self):
        for item in self.wire_items:
            self.scene().removeItem(item)
        self.wire_items = []
        for wire in self.editor.graph.wires:
            item = WireItem(wire)
            self.scene().addItem(item)
            self.wire_items.append(item)
        self.update_wires()
        self.style_wires(self.editor.results)

    def update_wires(self, moved=None):
        for item in self.wire_items:
            w = item.wire
            if moved is not None and moved.node.id not in (w.source, w.target):
                continue
            if not (w.source in self.node_items
                    and w.target in self.node_items):
                continue             # an end gone, while the graph is rebuilt
            src = self.node_items[w.source].port(w.output, True)
            dst = self.node_items[w.target].port(w.input, False)
            item.set_ends(src.scenePos(), dst.scenePos())
        if moved is not None:
            group = self.group_items.get(
                self.editor.graph.group_of(moved.node.id))
            if group is not None:
                group.refit()

    def event(self, event):
        # Delete, Copy, Paste, Select All, Ctrl+E and Ctrl+G here are the
        # graph's, not the model's
        if event.type() == QEvent.Type.ShortcutOverride and (
                event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace)
                or event.matches(QKeySequence.StandardKey.Copy)
                or event.matches(QKeySequence.StandardKey.Paste)
                or event.matches(QKeySequence.StandardKey.SelectAll)
                or _fit_key(event) or _group_key(event)
                or hide_key(event)):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self.editor.remove_selected()
            return
        if event.matches(QKeySequence.StandardKey.Copy):
            self.editor.copy_selected()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            self.editor.paste()
            return
        if event.matches(QKeySequence.StandardKey.SelectAll):
            for item in self.node_items.values():
                item.setSelected(True)
            return
        if _fit_key(event):
            self.fit_all()
            return
        which = _group_key(event)
        if which == "group":
            self.editor.group_selected()
            return
        if which == "ungroup":
            self.editor.ungroup_selected()
            return
        which = hide_key(event)
        if which == "hide":
            self.editor.hide()
            return
        if which == "show":
            self.editor.show_hidden()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        if 0.2 < self.transform().m11() * factor < 3.0:
            self.scale(factor, factor)

    # The right button pans when dragged and opens a menu when only
    # clicked, so the menu waits for the release to know which it was.
    def contextMenuEvent(self, event):
        if event.reason() != event.Reason.Mouse:
            super().contextMenuEvent(event)

    def mousePressEvent(self, event):
        if self.editor.placing is not None:
            if event.button() == Qt.MouseButton.LeftButton:
                self.editor.place(self.mapToScene(event.position().toPoint()))
            else:
                self.editor.stop_placing()
            return
        if event.button() == Qt.MouseButton.RightButton:
            self._pan = (event.position(), False)
            return
        held = event.modifiers() & (Qt.KeyboardModifier.ShiftModifier
                                    | Qt.KeyboardModifier.ControlModifier)
        at = self.mapToScene(event.position().toPoint())
        scene = self.scene()
        if (event.button() == Qt.MouseButton.LeftButton and held
                and scene._node_at(at) is None and scene._port_at(at) is None):
            # a box drawn with Shift adds to the choice, with Ctrl takes from
            # it, as in the model; Qt's own box only replaces it, and the
            # choice is made up from that as the box goes
            ctrl = held & Qt.KeyboardModifier.ControlModifier
            self._band = ("remove" if ctrl else "add",
                          set(self.chosen_items()), False)
            event = QMouseEvent(event.type(), event.position(),
                                event.globalPosition(), event.button(),
                                event.buttons(),
                                Qt.KeyboardModifier.NoModifier)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan is not None:
            last, dragged = self._pan
            delta = event.position() - last
            if not dragged and delta.manhattanLength() < PAN_SLOP:
                return
            if not dragged:
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._pan = (event.position(), True)
            self.horizontalScrollBar().setValue(
                int(self.horizontalScrollBar().value() - delta.x()))
            self.verticalScrollBar().setValue(
                int(self.verticalScrollBar().value() - delta.y()))
            return
        super().mouseMoveEvent(event)
        if self._band is not None:
            self._make_up_choice()

    def mouseReleaseEvent(self, event):
        if (self._pan is not None
                and event.button() == Qt.MouseButton.RightButton):
            _last, dragged = self._pan
            self._pan = None
            self.unsetCursor()
            if not dragged:
                self.editor.show_menu(self.mapToScene(event.position().toPoint()),
                                      event.globalPosition().toPoint())
            return
        super().mouseReleaseEvent(event)
        if self._band is not None:
            _how, before, boxed = self._band
            if not boxed:
                # only a click, on nothing: the choice stays as it was
                for item in self.node_items.values():
                    item.setSelected(item in before)
            self._band = None

    def _make_up_choice(self):
        """The choice as the box drawn with Shift or Ctrl makes it: what was
        chosen before, with what the box holds added, or taken away."""
        how, before, _boxed = self._band
        boxed = set(self.chosen_items())
        chosen = before | boxed if how == "add" else before - boxed
        for item in self.node_items.values():
            item.setSelected(item in chosen)
        self._band = (how, before, True)

    def fit_all(self):
        """All the components in view, as Ctrl+E fits the model, zoomed in
        no further than they are drawn."""
        if not self.node_items:
            return
        bounds = None
        for item in self.node_items.values():
            box = item.sceneBoundingRect()
            bounds = box if bounds is None else bounds.united(box)
        self.fitInView(bounds.adjusted(-40, -40, 40, 40),
                       Qt.AspectRatioMode.KeepAspectRatio)
        scale = self.transform().m11()
        if not 0.2 <= scale <= 1.0:
            self.resetTransform()
            limit = min(max(scale, 0.2), 1.0)
            self.scale(limit, limit)
            self.centerOn(bounds.center())
