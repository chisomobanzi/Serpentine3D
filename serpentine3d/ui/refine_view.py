"""A pane's finer meshes, for what it is zoomed in on (#168).

core/refine.py decides which faces need meshing again and does it. This is
the pane's side. Once the camera has stood still for SETTLE_MS, it asks which
objects it can see whose meshes now stray more than refine.TRIGGER_PX, and
hands each to the worker pool. What comes back is drawn and picked in place
of the object's own mesh, in this pane only: the scene's mesh stays as it
was, for every other pane and every export.

A finer mesh is kept while the object is in view and still wants it, and
belongs to the mesh it was made from, so an edit, which makes a new one,
leaves it behind by itself.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QTimer
from OCP.TopoDS import TopoDS_Shape

from ..core import refine

# How long the camera stands still before a pane asks for finer meshes. Long
# enough that a zoom by the wheel is one ask, not one per notch.
SETTLE_MS = 250
# The most objects one pane keeps finer meshes for. Each holds a copy of its
# object's mesh as well, so the nearest few are worth it and the rest are not.
MAX_OBJECTS = 24
_KINDS = frozenset(("surface", "solid", "compound"))


class PaneRefiner:
    """A viewport's finer meshes: `shown(obj)` is what it draws for `obj`."""

    def __init__(self, viewport):
        self._vp = viewport
        # object id -> (mesh uid it was made from, {face: level}, mesh)
        self.meshes: dict[str, tuple] = {}
        self.epoch = 0                  # moves when what is shown changes
        self._camera_key = None
        self._generation = 0
        self._asked: dict[str, int] = {}    # object id -> generation in flight
        self._timer = QTimer(viewport)
        self._timer.setSingleShot(True)
        self._timer.setInterval(SETTLE_MS)
        self._timer.timeout.connect(self.plan)

    def shown(self, obj):
        """The mesh this pane draws and picks for `obj`."""
        base = obj.mesh
        entry = self.meshes.get(obj.id)
        if entry is not None and entry[0] == base.uid:
            return entry[2]
        return base

    def frame(self, width: int, height: int) -> None:
        """Called every frame the pane draws the model: start the settle
        timer whenever what it shows has moved."""
        vp, cam = self._vp, self._vp.camera
        key = (cam.projection, cam.fov, cam.distance, cam.azimuth,
               cam.elevation, tuple(cam.target), width, height,
               vp.scene.revision, vp._tess_epoch, vp.display_mode)
        if key != self._camera_key:
            self._camera_key = key
            self._timer.start()

    def _refinable(self, obj) -> bool:
        return (obj.kind in _KINDS and not obj.annotation
                and obj.mesh_ready and isinstance(obj.shape, TopoDS_Shape))

    def plan(self) -> None:
        """Ask for finer meshes for what is in view, and let go of the rest."""
        vp = self._vp
        if vp.space != "model" or vp.display_mode == "technical":
            return
        width, height = vp.width(), vp.height()
        if width < 2 or height < 2:
            return
        view = refine.View.of(vp.camera, width, height)
        objects = [obj for obj in vp.scene.drawable_objects()
                   if self._refinable(obj)]
        wanted = []
        if objects:
            boxes = np.array([obj.bbox() for obj in objects], float)
            strays = refine.strays(boxes, refine.deflections(boxes), view)
            order = np.argsort(-strays)
            wanted = [objects[i] for i in order[:MAX_OBJECTS]
                      if strays[i] > refine.TRIGGER_PX]
        keep = {obj.id for obj in wanted}
        dropped = [oid for oid in self.meshes if oid not in keep]
        for oid in dropped:
            del self.meshes[oid]
        for oid in [oid for oid in self._asked if oid not in keep]:
            del self._asked[oid]
        if dropped:
            self._changed()
        if not wanted:
            return
        self._generation += 1
        for obj in wanted:
            self._ask(obj, view, self._generation)

    def _ask(self, obj, view, generation: int) -> None:
        self._asked[obj.id] = generation
        shape, base = obj.shape, obj.mesh
        entry = self.meshes.get(obj.id)
        current = entry[1] if entry is not None and entry[0] == base.uid \
            else None
        oid, done = obj.id, self._vp._refineDone

        def work():
            try:
                levels = refine.plan(shape, base, view)
                if levels == current:
                    done.emit((oid, base.uid, generation, None, None))
                    return
                mesh = refine.refined(shape, base, levels) if levels else None
                done.emit((oid, base.uid, generation, levels, mesh))
            except Exception:                           # noqa: BLE001
                # the pane keeps drawing the mesh it had, which is right
                done.emit((oid, base.uid, generation, None, None))
        self._vp._worker_pool().submit(work)

    def install(self, result) -> None:
        """A finer mesh, or word that none is needed, back from a worker."""
        oid, base_uid, generation, levels, mesh = result
        if self._asked.get(oid) != generation:
            return                          # asked again since, or let go
        del self._asked[oid]
        obj = self._vp.scene.get(oid)
        if obj is None or not obj.mesh_ready or obj.mesh.uid != base_uid:
            return
        if levels is None:
            return                          # unchanged, or it failed
        if levels:
            self.meshes[oid] = (base_uid, levels, mesh)
        elif self.meshes.pop(oid, None) is None:
            return
        self._changed()

    def _changed(self) -> None:
        self.epoch += 1
        self._vp.update()
