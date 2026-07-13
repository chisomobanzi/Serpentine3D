"""Stable scripting API — works headless and inside the app.

    from serpentine3d.scripting import Document
    doc = Document()
    box = doc.add(doc.geo.make_box((0, 0, 0), 10, 10, 10), name="Base")
    doc.run("filletedge", ["Base", "", "1"])
    doc.save("part.serp")
    doc.export("part.step")

`doc.geo` is the full geometry module (make_box, boolean_union, ...);
`doc.run` drives any interactive command with its inputs as strings.
"""

from __future__ import annotations

from . import fileio
from .core import geometry as geo
from .core.history import History
from .core.scene import Scene
from .core.selection import SelectionManager


class Document:
    geo = geo

    def __init__(self, path: str | None = None):
        self.scene = Scene()
        self.selection = SelectionManager(self.scene)
        self.history = History(self.scene)
        from .commands import CommandContext, CommandProcessor
        self._ctx = CommandContext(self.scene, self.selection, self.history)
        self._proc = CommandProcessor(self._ctx)
        self.messages: list[str] = []
        self._ctx.add_echo_listener(self.messages.append)
        if path:
            self.open(path)

    # -- objects --

    def add(self, shape, name: str | None = None, layer: str | None = None):
        layer_id = None
        if layer:
            existing = self.scene.layers.find_by_name(layer)
            layer_id = (existing or self.scene.layers.create(layer)).id
        return self.scene.add(shape, name=name, layer_id=layer_id)

    def objects(self) -> list:
        return self.scene.all()

    def get(self, name_or_id: str):
        return (self.scene.get(name_or_id)
                or self.scene.find_by_name(name_or_id))

    def remove(self, name_or_id: str):
        obj = self.get(name_or_id)
        if obj:
            self.scene.remove(obj.id)

    # -- commands --

    def run(self, command: str, inputs: list | None = None) -> list[str]:
        """Run any Serpentine3D command, feeding `inputs` in order.
        Returns the messages it echoed."""
        start = len(self.messages)
        if not self._proc.run(command):
            raise RuntimeError(f"Unknown command: {command}")
        for value in (inputs or []):
            if not self._proc.busy:
                break
            text = (",".join(str(v) for v in value)
                    if isinstance(value, (list, tuple)) else str(value))
            from .commands.base import SelectReq
            if isinstance(self._proc.request, SelectReq):
                if text == "":
                    self._proc.finish_selection()
                else:
                    obj = self.get(text)
                    if obj is not None:
                        self._proc.click_object(obj.id)
                    else:
                        self._proc.provide_text(text)
            else:
                self._proc.provide_text(text)
        if self._proc.busy:
            prompt = self._proc.prompt_text()
            self._proc.cancel()
            raise RuntimeError(f"Command needs more input: {prompt}")
        return self.messages[start:]

    # -- persistence --

    def open(self, path: str):
        fileio.import_file(self.scene, path)

    def save(self, path: str):
        if not path.endswith(".serp"):
            path += ".serp"
        fileio.export_file(self.scene, path)

    def export(self, path: str, only: list | None = None):
        ids = None
        if only:
            ids = [self.get(n).id for n in only if self.get(n)]
        fileio.export_file(self.scene, path, only_ids=ids)

    def import_(self, path: str) -> int:
        return fileio.import_file(self.scene, path)

    # -- measurement passthroughs --

    def volume(self, name: str) -> float:
        return geo.volume(self.get(name).shape)

    def area(self, name: str) -> float:
        return geo.surface_area(self.get(name).shape)

    def length(self, name: str) -> float:
        return geo.curve_length(self.get(name).shape)

    def bbox(self, name: str | None = None):
        if name:
            return geo.bbox(self.get(name).shape)
        return self.scene.bbox()
