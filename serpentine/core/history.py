"""Snapshot-based undo/redo.

Snapshots are shallow: SceneObject clones share the underlying immutable
TopoDS_Shape and cached mesh, so a checkpoint costs O(objects), not O(geometry).
"""

from __future__ import annotations

MAX_UNDO = 100


class History:
    def __init__(self, scene):
        self.scene = scene
        self._undo: list[tuple[str, dict]] = []
        self._redo: list[tuple[str, dict]] = []

    def checkpoint(self, label: str = ""):
        """Record state before a mutating operation."""
        self._undo.append((label, self.scene.snapshot()))
        if len(self._undo) > MAX_UNDO:
            self._undo.pop(0)
        self._redo.clear()

    def discard_checkpoint(self):
        """Drop the most recent checkpoint (cancelled/no-op command)."""
        if self._undo:
            self._undo.pop()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> str | None:
        if not self._undo:
            return None
        label, snap = self._undo.pop()
        self._redo.append((label, self.scene.snapshot()))
        self.scene.restore(snap)
        return label or "operation"

    def redo(self) -> str | None:
        if not self._redo:
            return None
        label, snap = self._redo.pop()
        self._undo.append((label, self.scene.snapshot()))
        self.scene.restore(snap)
        return label or "operation"
