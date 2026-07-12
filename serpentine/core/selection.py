"""Selection state, decoupled from UI."""

from __future__ import annotations


class SelectionManager:
    def __init__(self, scene):
        self.scene = scene
        self._ids: list[str] = []      # ordered
        self._listeners: list = []

    def add_listener(self, fn):
        self._listeners.append(fn)

    def _notify(self):
        for fn in self._listeners:
            fn()

    @property
    def ids(self) -> list[str]:
        # prune stale ids lazily
        self._ids = [i for i in self._ids if i in self.scene.objects]
        return list(self._ids)

    def objects(self) -> list:
        return [self.scene.objects[i] for i in self.ids]

    def is_selected(self, obj_id: str) -> bool:
        return obj_id in self._ids

    def set(self, ids: list[str]):
        self._ids = [i for i in ids if i in self.scene.objects]
        self._notify()

    def toggle(self, obj_id: str):
        if obj_id in self._ids:
            self._ids.remove(obj_id)
        else:
            self._ids.append(obj_id)
        self._notify()

    def select_all(self):
        self._ids = [o.id for o in self.scene.selectable_objects()]
        self._notify()

    def clear(self):
        if self._ids:
            self._ids = []
            self._notify()
