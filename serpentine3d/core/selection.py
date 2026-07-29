"""Selection state, decoupled from UI."""

from __future__ import annotations


class SelectionManager:
    def __init__(self, scene):
        self.scene = scene
        self._ids: list[str] = []      # ordered
        # The same ids again, for asking. The draw loop asks once per object
        # in the drawing, so reading the list instead cost objects x
        # selection: 190 ms of every frame on a big file with all of it
        # selected. Order matters elsewhere, hence both.
        self._index: set[str] = set()
        self.previous_ids: list[str] = []   # last non-empty selection
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

    def _assign(self, ids):
        """The one place the selection is written, so the two views of it
        cannot drift apart."""
        self._ids = list(ids)
        self._index = set(self._ids)

    @property
    def ids(self) -> list[str]:
        # prune stale ids lazily
        live = [i for i in self._ids if i in self.scene.objects]
        if len(live) != len(self._ids):
            self._assign(live)
        return live

    def objects(self) -> list:
        return [self.scene.objects[i] for i in self.ids]

    def is_selected(self, obj_id: str) -> bool:
        return obj_id in self._index

    def set(self, ids: list[str]):
        if self._ids:
            self.previous_ids = list(self._ids)
        self._assign(i for i in ids if i in self.scene.objects)
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
        if obj_id in self._index:
            self._ids.remove(obj_id)
            self._index.discard(obj_id)
        else:
            self._ids.append(obj_id)
            self._index.add(obj_id)
        self._notify()

    def select_all(self):
        self._assign(o.id for o in self.scene.selectable_objects())
        self._notify()

    def clear(self):
        if self._ids or self.subobjects:
            if self._ids:
                self.previous_ids = list(self._ids)
            self._assign(())
            self.subobjects = []
            self._notify()
