"""Selection state, decoupled from UI."""

from __future__ import annotations


class SelectionManager:
    def __init__(self, scene):
        self.scene = scene
        self._ids: list[str] = []      # ordered
        self.subobjects: list = []     # [(obj_id, "edge"|"face", index)]
        self._listeners: list = []
        self.filter_kinds: set = set()   # e.g. {"curve"}; empty = any
        self.filter_active = False       # F6-style master toggle

    def filter_allows(self, kind: str) -> bool:
        """May viewport picking select objects of this kind?"""
        if not self.filter_active or not self.filter_kinds:
            return True
        return kind in self.filter_kinds

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
        self.subobjects = []
        self._notify()

    def toggle_subobject(self, obj_id: str, kind: str, index: int):
        entry = (obj_id, kind, index)
        if entry in self.subobjects:
            self.subobjects.remove(entry)
        else:
            self.subobjects.append(entry)
        self._notify()

    def subobjects_of(self, obj_id: str, kind: str) -> list[int]:
        return [i for (oid, k, i) in self.subobjects
                if oid == obj_id and k == kind]

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
        if self._ids or self.subobjects:
            self._ids = []
            self.subobjects = []
            self._notify()
