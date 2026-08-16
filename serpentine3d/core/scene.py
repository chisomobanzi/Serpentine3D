"""Scene graph: object storage, naming, visibility, change notification.

Core is Qt-free; UI subscribes via plain callables.
"""

from __future__ import annotations

import itertools
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field, replace

import numpy as np

from . import geometry
from .deferred import DeferredShape
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
    # A TopoDS_Shape, or a DeferredShape standing in for one that has been
    # read but not converted. Read it through `shape`, which converts what
    # it finds; the underscore is here so that property can exist at all.
    _shape: object
    kind: str                          # curve | surface | solid | point | compound
    layer_id: str
    visible: bool = True
    locked: bool = False               # visible but unselectable
    group_id: str | None = None        # objects sharing an id select together
    block_id: str | None = None        # instance of a block definition
    color: tuple[float, float, float] | None = None   # None -> layer color
    # {"metallic","roughness","opacity"} and optionally "color", which only
    # rendered mode reads — see Scene.render_color_of
    material: dict | None = None
    clip_plane: dict | None = None     # {"enabled": bool}: sections the view
    annotation: dict | None = None     # {"text": str}: model-space dot label
    linetype: str = "ByLayer"          # dash style; ByLayer -> use the layer's
    draw_order: int = 0                # higher draws on top (breaks depth ties)
    _mesh: DisplayMesh | None = field(default=None, repr=False, compare=False)
    _bounds: tuple | None = field(default=None, repr=False, compare=False)
    # The scene holding this object, so a bare `.shape` read on something
    # deferred can go through `Scene.realise` and get the whole job — an
    # object that converts to nothing removed, one that converts to two
    # given its sibling — rather than only the shape.
    _scene: object = field(default=None, repr=False, compare=False)

    @property
    def shape(self):
        """This object's geometry, converting it first if it has not been.

        Every reader goes through here, which is the point: there is no
        call site left that can be handed a placeholder by mistake.
        """
        held = self._shape
        if isinstance(held, DeferredShape):
            scene = self._scene
            if scene is not None:
                scene.realise(self.id)
            else:
                shapes = held.shapes()
                self._shape = shapes[0] if shapes else None
            held = self._shape
        return held

    @shape.setter
    def shape(self, value):
        self._shape = value

    @property
    def shape_ready(self) -> bool:
        """Whether the geometry exists, as opposed to a promise of it.

        Asking does not convert anything, which is what makes it usable in
        the places that must not: the sync key, the tests above it.
        """
        return not isinstance(self._shape, DeferredShape)

    def bbox(self) -> tuple[tuple, tuple]:
        """This object's world bounding box, worked out at most once.

        Measuring a B-rep walks the whole shape and a mesh reads every
        vertex — about 100us an object, which is nothing until something
        asks for all of them every frame. The gumball does exactly that,
        and on the cave file it cost 747 ms of every frame you orbited
        with the drawing selected.

        Keyed on the shape it measured rather than cleared by hand:
        geometry is changed here by swapping the shape for a new one, so
        the answer expires by itself and there is no invalidation to
        forget at a call site.
        """
        shape = self.shape
        if shape is None:
            return ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        cached = self._bounds
        if cached is not None and cached[0] is shape:
            return cached[1]
        box = geometry.bbox(shape)
        self._bounds = (shape, box)
        return box

    @property
    def mesh(self) -> DisplayMesh:
        # None is what a deferred object that converted to nothing is left
        # holding. The scene drops it, but whoever was already iterating
        # still has it and will ask; an empty mesh draws nothing, which is
        # the right picture, where the kernel would raise on the way there.
        shape = self.shape
        if shape is None:
            return DisplayMesh()
        if self._mesh is None:
            with _tess_lock(shape):
                if self._mesh is None:
                    self._mesh = tessellate(shape)
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
        self.layers.on_shown = self.realise_layer
        self._counters = {}
        self._listeners: list = []
        self._batch_depth = 0           # see batched()
        self._batched_kinds: set[str] = set()
        self.revision = 0               # bumped on every change notification
        self.named_views: dict = {}     # name -> camera params
        # Objects showing their control points. Kept here rather than on a
        # viewport because points on is something the drawing is doing: turn
        # a curve's points on in the Top view and its corners are there to
        # pick in the Right view too. See Viewport.cv_enabled.
        self.cv_enabled: set[str] = set()
        # Objects showing direction arrows, for the same reason and for as
        # long as `dir` runs. Which way a curve runs is a fact about the
        # drawing, not about the pane you happened to ask in.
        self.dir_enabled: set[str] = set()
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

    @contextmanager
    def batched(self):
        """Hold the notifications until the whole change is made.

        Listeners answer a change by reading the scene, and two of them read
        all of it — the layers panel rebuilds its tree and counts objects per
        layer, the status bar counts objects. One notification per object
        added therefore makes bulk work cost objects squared: 0.08 ms an
        object into an empty scene, 0.71 ms into one already holding 4000,
        about 4.7 seconds of opening the 522 MB cave file.

        Nobody wants the states in between. What comes out is the finished
        scene, once, and still sorted by kind so a listener that only asked
        about layouts is not woken by objects arriving.

        Notifications go out even if the body raises: a half-read file still
        changed the scene, and a panel showing what was there before is worse
        than one showing the half. `revision` still moves inside the batch,
        so a cache rebuilt part-way through can tell the scene shifted.
        """
        self._batch_depth += 1
        try:
            yield self
        finally:
            self._batch_depth -= 1
            if not self._batch_depth and self._batched_kinds:
                kinds, self._batched_kinds = self._batched_kinds, set()
                if "all" in kinds:
                    self._fire("all")       # already reaches everyone
                else:
                    for kind in sorted(kinds):
                        self._fire(kind)

    def notify(self, kind: str = "all"):
        self.revision += 1
        if self._batch_depth:
            self._batched_kinds.add(kind)
            return
        self._fire(kind)

    def _fire(self, kind: str):
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
        # A DeferredShape is geometry the file described and nothing has
        # converted. It answers for its own kind, because working the kind
        # out from the shape is exactly the conversion being put off.
        kind = (shape.kind if isinstance(shape, DeferredShape)
                else geometry.shape_kind(shape))
        obj = SceneObject(
            id=uuid.uuid4().hex[:8],
            name=name or self._auto_name(kind),
            _shape=shape,
            kind=kind,
            layer_id=layer_id or self.layers.current_id,
            _scene=self,
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

    # -- converting what was only read (see core/deferred.py) --

    def realise(self, obj_id: str) -> SceneObject | None:
        """Convert an object's deferred geometry, now.

        One Rhino object is usually one shape, but not always, and the two
        exceptions are why this is the scene's job rather than the object's.
        Roughly a sixth of the hidden objects in a real survey file convert
        to nothing at all, and an eager import made no object for those, so
        neither can this one. A few convert to two — a sewn brep and the
        mesh fallback for the faces that would not sew — and eager import
        made two objects, so this adds the sibling.

        Returns the object, or None if the geometry turned out to be
        nothing and it has been dropped.
        """
        obj = self.objects.get(obj_id)
        if obj is None or obj.shape_ready:
            return obj

        held = obj._shape
        shapes = held.shapes()
        if not shapes:
            # Emptied as well as dropped: something may still be holding
            # this object, and a placeholder that has already been asked
            # and answered nothing is worse to hand back than nothing.
            obj._shape = None
            self.remove(obj_id)
            return None

        obj._shape = shapes[0]
        obj._mesh = None
        # The file's word on the kind was a guess made without the geometry.
        obj.kind = geometry.shape_kind(shapes[0])
        for extra in shapes[1:]:
            self.add(extra, layer_id=obj.layer_id)
        self.notify("objects")
        return obj

    def realise_layer(self, layer_id: str) -> int:
        """Convert everything still deferred on a layer. Returns how many.

        This is what a layer being switched back on calls: doing the whole
        layer in one pass means the file behind it is opened once, and it
        keeps the cost where the user can see they asked for it.
        """
        pending = [o.id for o in self.all()
                   if o.layer_id == layer_id and not o.shape_ready]
        if not pending:
            return 0
        with self.batched():
            for obj_id in pending:
                self.realise(obj_id)
        return len(pending)

    def remove(self, obj_id: str):
        if obj_id in self.objects:
            del self.objects[obj_id]
            self._order.remove(obj_id)
            self.notify("objects")

    def replace_shape(self, obj_id: str, shape) -> SceneObject:
        """Swap an object's geometry (transform, boolean result, ...)."""
        old = self.objects[obj_id]
        new = replace(old, _shape=shape, kind=geometry.shape_kind(shape),
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
                        old, _shape=shape, kind=geometry.shape_kind(shape),
                        _mesh=None)
                    queue.append(rec["output"])
        finally:
            self._regen_active = False

    def update(self, obj_id: str, **fields) -> SceneObject:
        was_visible = self.objects[obj_id].visible
        new = replace(self.objects[obj_id], **fields)
        self.objects[obj_id] = new
        # Most of what a real drawing defers is hidden object by object on a
        # layer that is switched on, so this is the trigger that does the
        # work, not the layer one. Here rather than when the viewport gets
        # round to it: converting can leave nothing and remove the object,
        # and the middle of a draw is no place to discover that.
        if new.visible and not was_visible and not new.shape_ready:
            if self.realise(obj_id) is None:
                return new
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

    def render_color_of(self, obj: SceneObject) -> tuple[float, float, float]:
        """The colour rendered mode draws the object's surfaces in.

        An object carries two colours, the way it does in Rhino: the one it
        displays, which is the layer's unless it says otherwise, and the one on
        its material. A drawing set up for rendering usually leaves every
        object on its layer colour and puts the real colours on materials, so
        the two are meant to differ (#4). Materials made in the app have no
        colour of their own, and those objects render the colour they display.
        """
        return (obj.material or {}).get("color") or self.color_of(obj)

    def clear(self):
        self.objects.clear()
        self._order.clear()
        self._counters.clear()
        self.layers = LayerManager()
        self.layers.on_shown = self.realise_layer
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
        boxes = np.array([o.bbox() for o in objs], float)
        return (tuple(boxes[:, 0].min(axis=0)),
                tuple(boxes[:, 1].max(axis=0)))

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
