"""Scene graph: object storage, naming, visibility, change notification.

Core is Qt-free; UI subscribes via plain callables.
"""

from __future__ import annotations

import itertools
import threading
import uuid
from dataclasses import dataclass, field, replace

import numpy as np

from . import geometry
from .layers import LayerManager
from .tessellate import DisplayMesh, tessellate


def _rebuild_record(rec: dict, shapes: list):
    op = rec["op"]
    p = rec.get("params", {})
    if op == "loft":
        return geometry.loft(shapes, ruled=bool(p.get("ruled")))
    if op == "extrude":
        return geometry.extrude(shapes[0], tuple(p["direction"]),
                                float(p["dist"]), cap=bool(p.get("cap")))
    if op == "revolve":
        return geometry.revolve(shapes[0], tuple(p["origin"]),
                                tuple(p["axis"]), float(p["angle"]))
    raise ValueError(f"Unknown history op '{op}'")


_TESS_GUARD = threading.Lock()
_TESS_LOCKS: dict[int, tuple] = {}      # id(shape) -> (shape, Lock)


def _tess_lock(shape) -> threading.Lock:
    with _TESS_GUARD:
        ent = _TESS_LOCKS.get(id(shape))
        if ent is None or ent[0] is not shape:
            ent = (shape, threading.Lock())
            _TESS_LOCKS[id(shape)] = ent
        if len(_TESS_LOCKS) > 1024:     # bound the registry
            for k in list(_TESS_LOCKS)[:512]:
                if not _TESS_LOCKS[k][1].locked():
                    del _TESS_LOCKS[k]
        return ent[1]


@dataclass
class SceneObject:
    id: str
    name: str
    shape: object                      # TopoDS_Shape
    kind: str                          # curve | surface | solid | point | compound
    layer_id: str
    visible: bool = True
    locked: bool = False               # visible but unselectable
    group_id: str | None = None        # objects sharing an id select together
    block_id: str | None = None        # instance of a block definition
    color: tuple[float, float, float] | None = None   # None -> layer color
    material: dict | None = None       # {"metallic","roughness","opacity"}
    clip_plane: dict | None = None     # {"enabled": bool}: sections the view
    annotation: dict | None = None     # {"text": str}: model-space dot label
    linetype: str = "ByLayer"          # dash style; ByLayer -> use the layer's
    draw_order: int = 0                # higher draws on top (breaks depth ties)
    _mesh: DisplayMesh | None = field(default=None, repr=False, compare=False)

    @property
    def mesh(self) -> DisplayMesh:
        if self._mesh is None:
            with _tess_lock(self.shape):
                if self._mesh is None:
                    self._mesh = tessellate(self.shape)
        return self._mesh

    @property
    def mesh_ready(self) -> bool:
        return self._mesh is not None

    def clone(self) -> "SceneObject":
        return replace(self)


class Scene:
    def __init__(self):
        self.objects: dict[str, SceneObject] = {}
        self._order: list[str] = []
        self.layers = LayerManager()
        self._counters = {}
        self._listeners: list = []
        self.revision = 0               # bumped on every change notification
        self.named_views: dict = {}     # name -> camera params
        self.layouts: list = []         # drafting sheets (core/layout.py)
        self.units: str = "mm"          # document units (utils/units.py)
        self.block_defs: dict = {}      # id -> {"name", "shapes": [TopoDS]}
        self.annot_styles: dict = {}    # name -> text/dim style overrides
        self.image_planes: list = []    # reference images (pictureframe)
        self.record_history = False     # new surfaces remember their inputs
        self.history_records: list = []   # {"op", "inputs", "output", ...}
        self._regen_active = False

    # -- notification --
    def add_listener(self, fn, kinds: tuple | None = None):
        """Subscribe; kinds limits calls to those change categories
        ("objects", "layers", "layouts") — "all" changes always fire."""
        self._listeners.append((fn, frozenset(kinds) if kinds else None))

    def notify(self, kind: str = "all"):
        self.revision += 1
        for fn, kinds in self._listeners:
            if kinds is None or kind == "all" or kind in kinds:
                fn()

    # -- object management --
    def _auto_name(self, kind: str) -> str:
        n = self._counters.get(kind, 0) + 1
        self._counters[kind] = n
        return f"{kind.capitalize()} {n:02d}"

    def add(self, shape, name: str | None = None,
            layer_id: str | None = None) -> SceneObject:
        kind = geometry.shape_kind(shape)
        obj = SceneObject(
            id=uuid.uuid4().hex[:8],
            name=name or self._auto_name(kind),
            shape=shape,
            kind=kind,
            layer_id=layer_id or self.layers.current_id,
        )
        self.objects[obj.id] = obj
        self._order.append(obj.id)
        self.notify("objects")
        return obj

    def add_from(self, shape, like: SceneObject) -> SceneObject:
        """Add a shape carrying over another object's display attributes
        (layer, colour, material, annotation, group)."""
        obj = self.add(shape, layer_id=like.layer_id)
        fields = {}
        if like.color is not None:
            fields["color"] = like.color
        if like.material:
            fields["material"] = dict(like.material)
        if like.annotation:
            fields["annotation"] = dict(like.annotation)
        if like.group_id:
            fields["group_id"] = like.group_id
        if fields:
            obj = self.update(obj.id, **fields)
        return obj

    def remove(self, obj_id: str):
        if obj_id in self.objects:
            del self.objects[obj_id]
            self._order.remove(obj_id)
            self.notify("objects")

    def replace_shape(self, obj_id: str, shape) -> SceneObject:
        """Swap an object's geometry (transform, boolean result, ...)."""
        old = self.objects[obj_id]
        new = replace(old, shape=shape, kind=geometry.shape_kind(shape),
                      _mesh=None)
        self.objects[obj_id] = new
        self._regenerate_dependents(obj_id)
        self.notify("objects")
        return new

    def add_record(self, op: str, inputs: list, output: str, **params):
        """Remember how an object was built (record history)."""
        self.history_records.append({"op": op, "inputs": list(inputs),
                                     "output": output, "params": params})

    def _regenerate_dependents(self, changed_id: str):
        """Rebuild recorded outputs whose inputs changed, transitively."""
        if self._regen_active or not self.history_records:
            return
        self._regen_active = True
        try:
            queue = [changed_id]
            seen = set()
            while queue:
                cid = queue.pop(0)
                for rec in self.history_records:
                    if cid not in rec["inputs"] or rec["output"] in seen:
                        continue
                    seen.add(rec["output"])
                    old = self.objects.get(rec["output"])
                    parents = [self.objects.get(i) for i in rec["inputs"]]
                    if old is None or any(p is None for p in parents):
                        continue
                    try:
                        shape = _rebuild_record(rec,
                                                [p.shape for p in parents])
                    except Exception:              # noqa: BLE001
                        continue                   # keep the stale child
                    self.objects[rec["output"]] = replace(
                        old, shape=shape, kind=geometry.shape_kind(shape),
                        _mesh=None)
                    queue.append(rec["output"])
        finally:
            self._regen_active = False

    def update(self, obj_id: str, **fields) -> SceneObject:
        new = replace(self.objects[obj_id], **fields)
        self.objects[obj_id] = new
        self.notify("objects")
        return new

    def get(self, obj_id: str) -> SceneObject | None:
        return self.objects.get(obj_id)

    def find_by_name(self, name: str) -> SceneObject | None:
        for obj in self.all():
            if obj.name.lower() == name.lower():
                return obj
        return None

    def all(self) -> list[SceneObject]:
        return [self.objects[i] for i in self._order]

    def visible_objects(self) -> list[SceneObject]:
        return [o for o in self.all()
                if o.visible and self.layers.get(o.layer_id).visible]

    def selectable_objects(self) -> list[SceneObject]:
        return [o for o in self.visible_objects()
                if not o.locked and not self.layers.get(o.layer_id).locked]

    def is_selectable(self, obj_id: str) -> bool:
        obj = self.get(obj_id)
        return (obj is not None and obj.visible and not obj.locked
                and self.layers.get(obj.layer_id).visible
                and not self.layers.get(obj.layer_id).locked)

    def expand_group_ids(self, ids: list[str]) -> list[str]:
        """Grow a selection to whole groups."""
        groups = {self.objects[i].group_id for i in ids
                  if i in self.objects and self.objects[i].group_id}
        if not groups:
            return list(ids)
        out = list(ids)
        for o in self.selectable_objects():
            if o.group_id in groups and o.id not in out:
                out.append(o.id)
        return out

    def color_of(self, obj: SceneObject) -> tuple[float, float, float]:
        return obj.color or self.layers.get(obj.layer_id).color

    def clear(self):
        self.objects.clear()
        self._order.clear()
        self._counters.clear()
        self.layers = LayerManager()
        self.named_views = {}
        self.layouts = []
        self.block_defs = {}
        self.annot_styles = {}
        self.image_planes = []
        self.history_records = []
        # units are a user preference as much as a document property: keep
        self.notify()

    def format_length(self, value: float) -> str:
        from ..utils.units import format_length
        return format_length(value, self.units)

    def bbox(self) -> tuple[tuple, tuple] | None:
        objs = self.visible_objects()
        if not objs:
            return None
        mins = np.full(3, np.inf)
        maxs = np.full(3, -np.inf)
        for o in objs:
            mn, mx = geometry.bbox(o.shape)
            mins = np.minimum(mins, mn)
            maxs = np.maximum(maxs, mx)
        return (tuple(mins), tuple(maxs))

    # -- snapshot (undo/redo) --
    def snapshot(self) -> dict:
        import copy
        return {
            "objects": {k: v.clone() for k, v in self.objects.items()},
            "order": list(self._order),
            "counters": dict(self._counters),
            "layers": self.layers.snapshot(),
            "named_views": copy.deepcopy(self.named_views),
            "layouts": [lay.clone() for lay in self.layouts],
            "block_defs": {k: dict(v) for k, v in self.block_defs.items()},
            "annot_styles": {k: dict(v) for k, v in self.annot_styles.items()},
            "image_planes": copy.deepcopy(self.image_planes),
            "history_records": copy.deepcopy(self.history_records),
        }

    def restore(self, snap: dict):
        import copy
        self.objects = {k: v.clone() for k, v in snap["objects"].items()}
        self._order = list(snap["order"])
        self._counters = dict(snap["counters"])
        self.layers.restore(snap["layers"])
        self.named_views = copy.deepcopy(snap.get("named_views", {}))
        self.layouts = [lay.clone() for lay in snap.get("layouts", [])]
        self.block_defs = {k: dict(v) for k, v in
                           snap.get("block_defs", {}).items()}
        self.annot_styles = {k: dict(v) for k, v in
                             snap.get("annot_styles", {}).items()}
        self.image_planes = copy.deepcopy(snap.get("image_planes", []))
        self.history_records = copy.deepcopy(
            snap.get("history_records", []))
        self.notify()
