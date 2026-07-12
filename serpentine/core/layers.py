"""Layer system."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace

DEFAULT_LAYER_ID = "default"

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


class LayerManager:
    def __init__(self):
        self._layers: dict[str, Layer] = {}
        self._order: list[str] = []
        self._counter = itertools.count(1)
        self.current_id = DEFAULT_LAYER_ID
        self._add(Layer(DEFAULT_LAYER_ID, "Default", _PALETTE[0]))

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

    @property
    def current(self) -> Layer:
        return self._layers[self.current_id]

    # -- mutations --
    def create(self, name: str | None = None,
               color: tuple[float, float, float] | None = None) -> Layer:
        n = next(self._counter)
        layer_id = f"layer{n}"
        while layer_id in self._layers:
            n = next(self._counter)
            layer_id = f"layer{n}"
        if not name:
            name = f"Layer {n:02d}"
        if color is None:
            color = _PALETTE[len(self._order) % len(_PALETTE)]
        layer = Layer(layer_id, name, color)
        self._add(layer)
        return layer

    def rename(self, layer_id: str, name: str):
        self._layers[layer_id] = replace(self._layers[layer_id], name=name)

    def set_visible(self, layer_id: str, visible: bool):
        self._layers[layer_id] = replace(self._layers[layer_id], visible=visible)

    def set_color(self, layer_id: str, color: tuple[float, float, float]):
        self._layers[layer_id] = replace(self._layers[layer_id], color=color)

    def set_locked(self, layer_id: str, locked: bool):
        self._layers[layer_id] = replace(self._layers[layer_id], locked=locked)

    def remove(self, layer_id: str):
        if layer_id == DEFAULT_LAYER_ID:
            raise ValueError("Cannot delete the default layer")
        del self._layers[layer_id]
        self._order.remove(layer_id)
        if self.current_id == layer_id:
            self.current_id = DEFAULT_LAYER_ID

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
