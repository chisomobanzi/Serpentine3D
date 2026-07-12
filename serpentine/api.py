"""Programmatic API over a running Serpentine session.

Used by the RPC bridge (and therefore the MCP server). Every method runs on
the Qt main thread and returns plain JSON-serializable data.
"""

from __future__ import annotations

import os
import tempfile

from . import fileio
from .core import geometry as g


class ApiError(Exception):
    pass


class SerpApi:
    def __init__(self, window):
        self.window = window
        self.scene = window.scene
        self.selection = window.selection
        self.history = window.history
        self.viewport = window.viewport
        self.processor = window.processor

    # ------------------------------------------------------------- resolution

    def _obj(self, ref: str):
        obj = self.scene.get(ref) or self.scene.find_by_name(ref)
        if obj is None:
            raise ApiError(f"No object named or id '{ref}'")
        return obj

    def _objs(self, refs: list[str]) -> list:
        return [self._obj(r) for r in refs]

    def _obj_info(self, obj) -> dict:
        mn, mx = g.bbox(obj.shape)
        return {
            "id": obj.id,
            "name": obj.name,
            "kind": obj.kind,
            "layer": self.scene.layers.get(obj.layer_id).name,
            "visible": obj.visible,
            "bbox": [list(mn), list(mx)],
        }

    # ------------------------------------------------------------------ info

    def scene_info(self) -> dict:
        objs = self.scene.all()
        bounds = self.scene.bbox()
        return {
            "object_count": len(objs),
            "objects": [self._obj_info(o) for o in objs],
            "layers": [
                {"name": layer.name, "color": list(layer.color),
                 "visible": layer.visible,
                 "current": layer.id == self.scene.layers.current_id,
                 "object_count": sum(1 for o in objs
                                     if o.layer_id == layer.id)}
                for layer in self.scene.layers.all()
            ],
            "bounds": ([list(bounds[0]), list(bounds[1])]
                       if bounds else None),
            "selected": [o.name for o in self.selection.objects()],
            "display_mode": self.viewport.display_mode,
        }

    def screenshot(self, path: str | None = None, width: int | None = None,
                   height: int | None = None,
                   full_window: bool = False) -> dict:
        if not path:
            fd, path = tempfile.mkstemp(suffix=".png", prefix="serp_")
            os.close(fd)
        if full_window:
            from PySide6.QtWidgets import QApplication
            target = QApplication.activeModalWidget() or self.window
            img = target.grab().toImage()
        else:
            img = self.viewport.grabFramebuffer()
        if width:
            from PySide6.QtCore import Qt as _Qt
            img = img.scaledToWidth(int(width),
                                    _Qt.TransformationMode.SmoothTransformation)
        if not img.save(path):
            raise ApiError(f"Could not save screenshot to {path}")
        return {"path": path, "width": img.width(), "height": img.height()}

    # -------------------------------------------------------------- commands

    def command(self, command: str, inputs: list | None = None) -> dict:
        """Run a command exactly as if typed, feeding `inputs` in order."""
        messages: list[str] = []
        listener = messages.append
        self.window.ctx.add_echo_listener(listener)
        try:
            ok = self.processor.run(command.strip())
            if not ok:
                raise ApiError(messages[-1] if messages
                               else f"Unknown command {command}")
            for value in (inputs or []):
                if not self.processor.busy:
                    break
                text = (",".join(str(v) for v in value)
                        if isinstance(value, (list, tuple)) else str(value))
                if _is_selection_request(self.processor):
                    self._feed_selection(text)
                else:
                    self.processor.provide_text(text)
            if self.processor.busy:
                prompt = self.processor.prompt_text()
                self.processor.cancel()
                raise ApiError(
                    f"Command needs more input: '{prompt}'. "
                    f"Provide additional values in `inputs`.")
        finally:
            self.window.ctx._echo_fns.remove(listener)
        return {"messages": messages}

    def _feed_selection(self, text: str):
        if text.strip() == "":
            self.processor.finish_selection()
            return
        # try to resolve as object ref first (id or name), else keyword
        try:
            obj = self._obj(text.strip())
            self.processor.click_object(obj.id)
        except ApiError:
            self.processor.provide_text(text)

    # -------------------------------------------------------------- creation

    def create_curve(self, points: list, kind: str = "interp",
                     degree: int = 3, closed: bool = False,
                     name: str | None = None) -> dict:
        pts = [tuple(float(c) for c in p) for p in points]
        self.history.checkpoint("create_curve")
        try:
            if kind == "interp":
                shape = g.make_interp_curve(pts, closed=closed)
            elif kind == "control":
                shape = g.make_control_curve(pts, degree=degree,
                                             closed=closed)
            elif kind == "polyline":
                shape = g.make_polyline(pts, closed=closed)
            elif kind == "line":
                shape = g.make_line(pts[0], pts[1])
            else:
                raise ApiError(f"Unknown curve kind '{kind}' "
                               "(interp|control|polyline|line)")
        except g.GeometryError as exc:
            self.history.discard_checkpoint()
            raise ApiError(str(exc)) from exc
        obj = self.scene.add(shape, name=name)
        return self._obj_info(obj)

    def create_surface(self, operation: str, curves: list[str],
                       params: dict | None = None,
                       name: str | None = None) -> dict:
        params = params or {}
        objs = self._objs(curves)
        shapes = [o.shape for o in objs]
        self.history.checkpoint(f"create_surface:{operation}")
        try:
            if operation == "extrude":
                direction = tuple(params.get("direction", (0, 0, 1)))
                distance = float(params.get("distance", 10.0))
                cap = bool(params.get("cap", True))
                shape = g.extrude(shapes[0], direction, distance, cap=cap)
            elif operation == "revolve":
                axis_point = tuple(params.get("axis_point", (0, 0, 0)))
                axis_dir = tuple(params.get("axis_dir", (0, 0, 1)))
                angle = float(params.get("angle", 360.0))
                shape = g.revolve(shapes[0], axis_point, axis_dir, angle)
            elif operation == "loft":
                shape = g.loft(shapes, ruled=bool(params.get("ruled", False)))
            elif operation == "planar":
                shape = g.planar_face(shapes[0])
            elif operation == "sweep":
                if len(shapes) < 2:
                    raise ApiError("sweep needs [profile, rail]")
                shape = g.sweep1(shapes[0], shapes[1])
            else:
                raise ApiError(
                    f"Unknown operation '{operation}' "
                    "(extrude|revolve|loft|planar|sweep)")
        except g.GeometryError as exc:
            self.history.discard_checkpoint()
            raise ApiError(str(exc)) from exc
        obj = self.scene.add(shape, name=name)
        return self._obj_info(obj)

    def boolean(self, operation: str, targets: list[str],
                tools: list[str]) -> dict:
        t_objs = self._objs(targets)
        tool_objs = self._objs(tools)
        from functools import reduce
        self.history.checkpoint(f"boolean:{operation}")
        try:
            ops = {"union": g.boolean_union,
                   "difference": g.boolean_difference,
                   "intersection": g.boolean_intersection}
            if operation not in ops:
                raise ApiError("operation must be union|difference|intersection")
            fn = ops[operation]
            if operation == "union":
                shapes = [o.shape for o in t_objs + tool_objs]
                result = reduce(fn, shapes)
            else:
                tool_union = reduce(g.boolean_union,
                                    [o.shape for o in tool_objs])
                result = fn(t_objs[0].shape, tool_union)
                for extra in t_objs[1:]:
                    result = fn(result, tool_union)
        except g.GeometryError as exc:
            self.history.discard_checkpoint()
            raise ApiError(str(exc)) from exc
        keep = t_objs[0]
        for o in t_objs[1:] + tool_objs:
            self.scene.remove(o.id)
        new = self.scene.replace_shape(keep.id, result)
        return self._obj_info(new)

    # ------------------------------------------------------------- transform

    def transform(self, operation: str, targets: list[str],
                  params: dict | None = None) -> dict:
        params = params or {}
        objs = self._objs(targets)
        self.history.checkpoint(f"transform:{operation}")
        made = []
        try:
            for o in objs:
                if operation == "move":
                    offset = tuple(params.get("offset", (0, 0, 0)))
                    new_shape = g.translate(o.shape, offset)
                elif operation == "copy":
                    offset = tuple(params.get("offset", (0, 0, 0)))
                    made.append(self.scene.add(
                        g.translate(o.shape, offset), layer_id=o.layer_id))
                    continue
                elif operation == "rotate":
                    center = tuple(params.get("center", (0, 0, 0)))
                    axis = tuple(params.get("axis", (0, 0, 1)))
                    angle = float(params.get("angle", 0.0))
                    new_shape = g.rotate(o.shape, center, axis, angle)
                elif operation == "scale":
                    center = tuple(params.get("center", (0, 0, 0)))
                    if "factors" in params:
                        new_shape = g.scale(o.shape, center, 1.0,
                                            factors=tuple(params["factors"]))
                    else:
                        new_shape = g.scale(o.shape, center,
                                            float(params.get("factor", 1.0)))
                elif operation == "mirror":
                    point = tuple(params.get("plane_point", (0, 0, 0)))
                    normal = tuple(params.get("plane_normal", (1, 0, 0)))
                    new_shape = g.mirror(o.shape, point, normal)
                    if params.get("keep_original", False):
                        made.append(self.scene.add(new_shape,
                                                   layer_id=o.layer_id))
                        continue
                else:
                    raise ApiError(
                        "operation must be move|copy|rotate|scale|mirror")
                self.scene.replace_shape(o.id, new_shape)
        except g.GeometryError as exc:
            self.history.discard_checkpoint()
            raise ApiError(str(exc)) from exc
        return {
            "transformed": [o.name for o in objs],
            "created": [self._obj_info(o) for o in made],
        }

    # ------------------------------------------------------------- selection

    def select(self, names: list[str] | None = None,
               kind: str | None = None, layer: str | None = None,
               mode: str = "replace") -> dict:
        if mode == "clear":
            self.selection.clear()
            return {"selected": []}
        if names:
            ids = [self._obj(n).id for n in names]
        else:
            candidates = self.scene.visible_objects()
            if kind:
                candidates = [o for o in candidates if o.kind == kind]
            if layer:
                lay = self.scene.layers.find_by_name(layer)
                if lay is None:
                    raise ApiError(f"No layer '{layer}'")
                candidates = [o for o in candidates if o.layer_id == lay.id]
            ids = [o.id for o in candidates]
        if mode == "add":
            ids = self.selection.ids + [i for i in ids
                                        if i not in self.selection.ids]
        self.selection.set(ids)
        return {"selected": [o.name for o in self.selection.objects()]}

    # ---------------------------------------------------------------- layers

    def layers(self, action: str = "list", name: str | None = None,
               new_name: str | None = None, color: list | None = None,
               visible: bool | None = None,
               objects: list[str] | None = None) -> dict:
        mgr = self.scene.layers
        if action == "list":
            return {"layers": self.scene_info()["layers"]}
        if action == "create":
            self.history.checkpoint("create layer")
            layer = mgr.create(name, tuple(color) if color else None)
            self.scene.notify()
            return {"created": layer.name}
        layer = mgr.find_by_name(name or "")
        if layer is None:
            raise ApiError(f"No layer named '{name}'")
        if action == "rename":
            self.history.checkpoint("rename layer")
            mgr.rename(layer.id, new_name)
        elif action == "visible":
            self.history.checkpoint("layer visibility")
            mgr.set_visible(layer.id, bool(visible))
        elif action == "current":
            mgr.current_id = layer.id
        elif action == "color":
            self.history.checkpoint("layer colour")
            mgr.set_color(layer.id, tuple(color))
        elif action == "assign":
            self.history.checkpoint("assign layer")
            for ref in objects or []:
                self.scene.update(self._obj(ref).id, layer_id=layer.id)
        elif action == "delete":
            self.history.checkpoint("delete layer")
            for o in self.scene.all():
                if o.layer_id == layer.id:
                    self.scene.update(o.id, layer_id="default")
            mgr.remove(layer.id)
        else:
            raise ApiError(f"Unknown layer action '{action}'")
        self.scene.notify()
        return {"ok": True}

    # -------------------------------------------------------------- file i/o

    def import_file(self, path: str) -> dict:
        path = os.path.abspath(os.path.expanduser(path))
        if not os.path.exists(path):
            raise ApiError(f"File not found: {path}")
        self.history.checkpoint("import")
        try:
            n = fileio.import_file(self.scene, path)
        except Exception as exc:
            self.history.discard_checkpoint()
            raise ApiError(f"Import failed: {exc}") from exc
        self.viewport.zoom_extents()
        return {"imported": n}

    def export_file(self, path: str, selected_only: bool = False) -> dict:
        path = os.path.abspath(os.path.expanduser(path))
        ids = self.selection.ids if selected_only else None
        try:
            fileio.export_file(self.scene, path, only_ids=ids)
        except Exception as exc:
            raise ApiError(f"Export failed: {exc}") from exc
        return {"path": path}

    # --------------------------------------------------------------- measure

    def measure(self, what: str, targets: list[str] | None = None,
                points: list | None = None) -> dict:
        if what == "distance":
            if not points or len(points) != 2:
                raise ApiError("distance needs points=[[x,y,z],[x,y,z]]")
            d = sum((b - a) ** 2 for a, b in
                    zip(points[0], points[1])) ** 0.5
            return {"distance": d}
        objs = self._objs(targets or [])
        if not objs:
            raise ApiError("measure needs target objects")
        if what == "area":
            return {"area": sum(g.surface_area(o.shape) for o in objs)}
        if what == "volume":
            return {"volume": sum(g.volume(o.shape) for o in objs)}
        if what == "length":
            return {"length": sum(g.curve_length(o.shape) for o in objs)}
        if what == "bbox":
            infos = [self._obj_info(o) for o in objs]
            return {"bboxes": {i["name"]: i["bbox"] for i in infos}}
        if what == "centroid":
            return {"centroids": {o.name: list(g.centroid(o.shape))
                                  for o in objs}}
        raise ApiError("what must be distance|area|volume|length|bbox|centroid")

    # ------------------------------------------------------------------ misc

    def viewport_info(self, project: list | None = None) -> dict:
        """Debug/testing helper: viewport geometry, camera pose, and
        optional world->screen projection of points."""
        import numpy as np
        from PySide6.QtCore import QPoint
        vp = self.viewport
        origin = vp.mapToGlobal(QPoint(0, 0))
        cam = vp.camera
        out = {
            "origin": [origin.x(), origin.y()],
            "size": [vp.width(), vp.height()],
            "camera": {
                "target": list(map(float, cam.target)),
                "distance": cam.distance,
                "azimuth": cam.azimuth,
                "elevation": cam.elevation,
            },
            "display_mode": vp.display_mode,
            "selected": [o.name for o in self.selection.objects()],
        }
        if project:
            pts = np.asarray(project, float)
            scr = cam.project(pts, vp.width(), vp.height())
            out["projected"] = [[float(p[0]), float(p[1])] for p in scr]
        return out

    def undo(self) -> dict:
        label = self.history.undo()
        return {"undone": label}

    def redo(self) -> dict:
        label = self.history.redo()
        return {"redone": label}

    def set_viewport(self, view: str | None = None,
                     display_mode: str | None = None,
                     zoom_extents: bool = False,
                     grid: bool | None = None) -> dict:
        if view:
            self.viewport.set_view(view)
        if display_mode:
            self.viewport.set_display_mode(display_mode)
        if grid is not None:
            self.viewport.grid_visible = bool(grid)
        if zoom_extents:
            self.viewport.zoom_extents()
        self.viewport.update()
        return {"view": view, "display_mode": self.viewport.display_mode}


def _is_selection_request(processor) -> bool:
    from .commands.base import SelectReq
    return isinstance(processor.request, SelectReq)
