"""Isolated Python document runs. No live GUI objects enter the worker."""

from __future__ import annotations

import builtins
import copy
import dataclasses
import hashlib
import io
import sys
import time
import traceback

import numpy as np
from OCP.BRepBuilderAPI import BRepBuilderAPI_Copy
from OCP.TopoDS import TopoDS_Shape

from .core.deferred import DeferredShape
from .scripting import Document


class ScriptStopped(BaseException):
    """Cancellation is distinct from a script's ordinary exception handler."""


def fingerprint(value):
    """Semantic state, ignoring caches, listeners, and notification revisions.

    Normal CAD edits replace immutable shapes. A cancelled command restores
    clones of the same shapes, so it must compare equal despite a new revision.
    """
    if isinstance(value, TopoDS_Shape):
        return (hash(value), int(value.Orientation()))
    if isinstance(value, DeferredShape):
        return ("deferred", id(value))
    if isinstance(value, np.ndarray):
        return (str(value.dtype), value.shape,
                hashlib.blake2b(value.tobytes(), digest_size=16).digest())
    if dataclasses.is_dataclass(value):
        return tuple((f.name, fingerprint(getattr(value, f.name)))
                     for f in dataclasses.fields(value)
                     if f.name not in {"_mesh", "_bounds", "_scene"})
    if isinstance(value, dict):
        return tuple(sorted((k, fingerprint(v)) for k, v in value.items()))
    if isinstance(value, (list, tuple)):
        return tuple(fingerprint(v) for v in value)
    if isinstance(value, set):
        return frozenset(fingerprint(v) for v in value)
    return value


def isolated_copy(value):
    """Copy geometry as well as Python metadata; discard live display caches."""
    if isinstance(value, TopoDS_Shape):
        return BRepBuilderAPI_Copy(value, True, False).Shape()
    if isinstance(value, DeferredShape):
        # Leave expensive conversions deferred, but never expose their shared
        # results to user Python or worker tessellation.
        return DeferredShape(lambda: [isolated_copy(s) for s in value.shapes()],
                             kind=value.kind)
    if dataclasses.is_dataclass(value):
        result = copy.copy(value)
        for field in dataclasses.fields(value):
            item = (None if field.name in {"_mesh", "_bounds", "_scene"}
                    else isolated_copy(getattr(value, field.name)))
            object.__setattr__(result, field.name, item)
        return result
    if isinstance(value, dict):
        return {k: isolated_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [isolated_copy(v) for v in value]
    if isinstance(value, tuple):
        return tuple(isolated_copy(v) for v in value)
    return copy.deepcopy(value)


def _display_geometry(objects):
    """Only changed objects are tessellated, never the entire drawing."""
    triangles, segments, points = [], [], []
    for obj in objects:
        mesh = obj.mesh
        if len(mesh.triangles):
            triangles.append(mesh.vertices[mesh.triangles.ravel()])
        if len(mesh.edge_segments):
            segments.append(mesh.edge_segments.reshape(-1, 3))
        if len(mesh.points):
            points.append(mesh.points)
    return tuple(np.concatenate(items) if items else np.empty((0, 3), np.float32)
                 for items in (triangles, segments, points))


def execute_script(source, filename, snapshot, selected_ids, owner, stop):
    """Return a staged result or an error; never apply anything to the model."""
    output = io.StringIO()
    lines = 0

    def trace(frame, event, arg):
        nonlocal lines
        if stop.is_set():
            raise ScriptStopped()
        lines += 1
        if lines % 1000 == 0:
            time.sleep(.001)  # let Qt and other Python workers acquire the GIL
        return trace

    def script_print(*args, **kwargs):
        kwargs.setdefault("file", output)
        builtins.print(*args, **kwargs)

    try:
        sys.settrace(trace)
        doc = Document()
        doc.scene.restore(isolated_copy(snapshot))
        for obj in doc.scene.all():
            obj._scene = doc.scene
        owned = {r["output"] for r in doc.scene.history_records
                 if r.get("op") == "script_output" and r.get("owner") == owner}
        for oid in owned:
            doc.scene.remove(oid)
        doc.scene.history_records = [r for r in doc.scene.history_records
                                     if r.get("output") not in owned]
        doc.selection.set([oid for oid in selected_ids if doc.scene.get(oid)])
        initial = {obj.id: fingerprint(obj) for obj in doc.scene.all()}
        selected = doc.selection.objects()
        environment = {"doc": doc, "geo": doc.geo, "selected": selected,
                       "__name__": "__serpentine_script__", "__file__": filename,
                       "__builtins__": dict(vars(builtins), print=script_print)}
        exec(compile(source, filename, "exec"), environment, environment)
        changed = [obj for obj in doc.scene.all()
                   if obj.id not in initial or fingerprint(obj) != initial[obj.id]]
        created = [obj.id for obj in doc.scene.all() if obj.id not in initial]
        removed_ids = set(snapshot["objects"]) - set(doc.scene.objects)
        for oid in created:
            doc.scene.history_records.append({"op": "script_output", "inputs": [],
                                              "output": oid, "owner": owner})
        # Both geometry batches are private copies, including deleted objects.
        added_overlay = _display_geometry(changed)
        removed_overlay = _display_geometry(
            isolated_copy(snapshot["objects"][oid]) for oid in removed_ids)
        result = doc.scene.snapshot()
        changed_ids = {obj.id for obj in changed}
        # Retain original immutable shapes/display caches for untouched inputs.
        for oid in set(result["objects"]) & set(snapshot["objects"]) - changed_ids:
            result["objects"][oid] = snapshot["objects"][oid].clone()
        return {"snapshot": result, "overlay": (added_overlay, removed_overlay),
                "changed": len(changed), "removed": len(removed_ids),
                "output": output.getvalue(), "messages": doc.messages}
    except ScriptStopped:
        return {"stopped": True, "output": output.getvalue()}
    except BaseException:
        return {"error": traceback.format_exc(), "output": output.getvalue()}
    finally:
        sys.settrace(None)
