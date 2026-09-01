"""Layer system."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace

DEFAULT_LAYER_ID = "default"

# What a layer path is written with, the separator Rhino uses:
# "Walls::Interior" is the layer Interior sitting under the layer Walls.
PATH_SEPARATOR = "::"

# muted but distinguishable object colors, dark-theme friendly
_PALETTE = [
    (0.85, 0.85, 0.85),   # light grey
    (0.95, 0.65, 0.30),   # amber
    (0.40, 0.70, 0.95),   # sky blue
    (0.55, 0.85, 0.50),   # green
    (0.90, 0.50, 0.55),   # rose
    (0.75, 0.60, 0.95),   # violet
    (0.95, 0.85, 0.45),   # gold
    (0.45, 0.85, 0.80),   # teal
]


@dataclass(frozen=True)
class Layer:
    id: str
    name: str
    color: tuple[float, float, float]
    visible: bool = True
    locked: bool = False
    lineweight: float = 1.4        # on-screen edge width in pixels
    linetype: str = "Continuous"   # dash-pattern name (core/linetype.py)
    print_width: float = 0.0       # plotted pen width in mm; 0 = device default
    parent: str | None = None      # the layer this one sits under, if any


class LayerManager:
    def __init__(self):
        self._layers: dict[str, Layer] = {}
        self._order: list[str] = []
        self._counter = itertools.count(1)
        self.current_id = DEFAULT_LAYER_ID
        self._add(Layer(DEFAULT_LAYER_ID, "Default", _PALETTE[0]))
        # Called with a layer id when that layer is switched on, whoever
        # switched it. The scene sets it, to convert the geometry it read
        # from the file and put off converting (see core/deferred.py). A
        # table on its own has nothing to convert and leaves it None.
        self.on_shown = None

    def _add(self, layer: Layer):
        self._layers[layer.id] = layer
        self._order.append(layer.id)

    # -- queries --
    def get(self, layer_id: str) -> Layer:
        return self._layers[layer_id]

    def find_by_name(self, name: str) -> Layer | None:
        for layer in self.all():
            if layer.name.lower() == name.lower():
                return layer
        return None

    def all(self) -> list[Layer]:
        return [self._layers[i] for i in self._order]

    def children(self, layer_id: str) -> list[Layer]:
        """The layers directly under this one, in the order they were made."""
        return [la for la in self.all() if la.parent == layer_id]

    def descendants(self, layer_id: str) -> list[Layer]:
        """Everything under this one, a branch at a time."""
        out = []
        for child in self.children(layer_id):
            out.append(child)
            out.extend(self.descendants(child.id))
        return out

    def ancestors(self, layer_id: str) -> list[Layer]:
        """Every layer above this one, nearest first.

        Walks by id rather than trusting the chain to end: set_parent
        refuses to make a loop, but a file written by something else can
        still hand us one, and a hung app is a worse answer than a short
        list. A parent that is not there any more ends the walk too.
        """
        out = []
        seen = {layer_id}
        parent = self._layers[layer_id].parent
        while (parent is not None and parent in self._layers
               and parent not in seen):
            seen.add(parent)
            out.append(self._layers[parent])
            parent = self._layers[parent].parent
        return out

    def full_path(self, layer_id: str) -> str:
        """What the file calls this layer: "Walls::Interior"."""
        names = [la.name for la in reversed(self.ancestors(layer_id))]
        names.append(self._layers[layer_id].name)
        return PATH_SEPARATOR.join(names)

    def find_by_path(self, path: str) -> Layer | None:
        """The layer at a full path, which is what a name alone cannot say.

        Walls::Interior and Roof::Interior are two layers sharing a leaf
        name, so find_by_name can only ever answer with one of them.
        """
        wanted = path.strip().lower()
        for layer in self.all():
            if self.full_path(layer.id).lower() == wanted:
                return layer
        return None

    def is_visible(self, layer_id: str) -> bool:
        """Whether the layer is really on screen, its parents counted.

        A layer keeps its own switch whatever a parent does, so switching a
        parent back on leaves a child that was off still off.
        """
        return (self._layers[layer_id].visible
                and all(la.visible for la in self.ancestors(layer_id)))

    def is_locked(self, layer_id: str) -> bool:
        """Whether the layer is really locked, its parents counted."""
        return (self._layers[layer_id].locked
                or any(la.locked for la in self.ancestors(layer_id)))

    @property
    def current(self) -> Layer:
        return self._layers[self.current_id]

    # -- mutations --
    def create(self, name: str | None = None,
               color: tuple[float, float, float] | None = None,
               parent: str | None = None) -> Layer:
        n = next(self._counter)
        layer_id = f"layer{n}"
        while layer_id in self._layers:
            n = next(self._counter)
            layer_id = f"layer{n}"
        if not name:
            name = f"Layer {n:02d}"
        if color is None:
            color = _PALETTE[len(self._order) % len(_PALETTE)]
        layer = Layer(layer_id, name, color, parent=parent)
        self._add(layer)
        return layer

    def rename(self, layer_id: str, name: str):
        self._layers[layer_id] = replace(self._layers[layer_id], name=name)

    def set_visible(self, layer_id: str, visible: bool):
        branch = [layer_id] + [la.id for la in self.descendants(layer_id)]
        was = {i for i in branch if self.is_visible(i)}
        self._layers[layer_id] = replace(self._layers[layer_id], visible=visible)
        if self.on_shown is None:
            return
        # Everything that came on, not only the layer that was clicked. A
        # child under a parent that was off has geometry nobody has
        # converted yet, and it is on screen now.
        for i in branch:
            if i not in was and self.is_visible(i):
                self.on_shown(i)

    def set_color(self, layer_id: str, color: tuple[float, float, float]):
        self._layers[layer_id] = replace(self._layers[layer_id], color=color)

    def set_lineweight(self, layer_id: str, weight: float):
        self._layers[layer_id] = replace(self._layers[layer_id],
                                         lineweight=max(0.2, float(weight)))

    def set_linetype(self, layer_id: str, name: str):
        self._layers[layer_id] = replace(self._layers[layer_id],
                                         linetype=name or "Continuous")

    def set_print_width(self, layer_id: str, width: float):
        self._layers[layer_id] = replace(self._layers[layer_id],
                                         print_width=max(0.0, float(width)))

    def set_parent(self, layer_id: str, parent_id: str | None):
        """Move a layer, and everything under it, to sit under another one.

        A layer cannot go under itself or under one of its own children: a
        branch that contains itself has no top, so nothing could say what
        it inherits or what its path is.
        """
        if parent_id is not None:
            if parent_id not in self._layers:
                raise ValueError(f"No such layer: {parent_id}")
            if parent_id == layer_id or parent_id in {
                    la.id for la in self.descendants(layer_id)}:
                raise ValueError("A layer cannot sit under itself")
        self._layers[layer_id] = replace(self._layers[layer_id],
                                         parent=parent_id)

    def set_locked(self, layer_id: str, locked: bool):
        self._layers[layer_id] = replace(self._layers[layer_id], locked=locked)

    def remove(self, layer_id: str) -> list[str]:
        """Remove a layer and everything under it. Returns what went.

        The branch goes together because a layer whose parent is gone has
        no path and nothing to inherit from, which is not a layer any more.
        Whatever was drawn on one of them is the caller's to see to first,
        and Scene.remove_layer is the caller that does.
        """
        going = [layer_id] + [la.id for la in self.descendants(layer_id)]
        if DEFAULT_LAYER_ID in going:
            raise ValueError("Cannot delete the default layer")
        for i in going:
            del self._layers[i]
            self._order.remove(i)
        if self.current_id in going:
            self.current_id = DEFAULT_LAYER_ID
        return going

    # -- snapshot support --
    def snapshot(self) -> dict:
        return {
            "layers": dict(self._layers),
            "order": list(self._order),
            "current": self.current_id,
        }

    def restore(self, snap: dict):
        self._layers = dict(snap["layers"])
        self._order = list(snap["order"])
        self.current_id = snap["current"]
