"""File import/export."""

import os

from . import native, obj, step


def import_file(scene, path: str) -> int:
    """Import any supported file into the scene. Returns object count added."""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".serp":
        native.load_scene(scene, path)
        return len(scene.all())
    if ext in (".step", ".stp"):
        shapes = step.import_step(path)
        base = os.path.splitext(os.path.basename(path))[0]
        for i, shape in enumerate(shapes, 1):
            name = base if len(shapes) == 1 else f"{base} {i:02d}"
            scene.add(shape, name=name)
        return len(shapes)
    if ext == ".obj":
        named = obj.import_obj(path)
        for name, shape in named:
            scene.add(shape, name=name)
        return len(named)
    if ext == ".dxf":
        from . import dxf as dxf_mod
        return dxf_mod.import_dxf(scene, path)
    if ext == ".svg":
        from . import svg as svg_mod
        return svg_mod.import_svg(scene, path)
    if ext == ".3dm":
        from . import rhino
        items = rhino.import_3dm(path)
        layer_map = {}
        for name, shape, meta in items:
            layer_id = None
            lname = meta.get("name")
            if lname:
                if lname not in layer_map:
                    existing = scene.layers.find_by_name(lname)
                    if existing is None:
                        existing = scene.layers.create(
                            lname, meta.get("color"))
                    layer_map[lname] = existing.id
                layer_id = layer_map[lname]
            scene.add(shape, name=name, layer_id=layer_id)
        return len(items)
    raise ValueError(f"Unsupported import format: {ext}")


def export_file(scene, path: str, only_ids: list | None = None,
                thumbnail: bytes | None = None):
    """Export scene (or subset) to a file, format by extension."""
    ext = os.path.splitext(path)[1].lower()
    objs = scene.all()
    if only_ids:
        objs = [o for o in objs if o.id in only_ids]
    if ext == ".serp":
        native.save_scene(scene, path, thumbnail=thumbnail)
        return
    if ext in (".step", ".stp"):
        step.export_step([o.shape for o in objs], path)
        return
    if ext == ".obj":
        obj.export_obj([(o.name, o.shape, scene.color_of(o))
                        for o in objs], path)
        return
    if ext == ".3dm":
        from . import rhino
        rhino.export_3dm(scene, path, only_ids=only_ids)
        return
    if ext == ".dxf":
        from . import dxf as dxf_mod
        dxf_mod.export_dxf(scene, path, only_ids=only_ids)
        return
    if ext == ".glb":
        from . import gltf
        gltf.export_glb(scene, path, only_ids=only_ids)
        return
    if ext in (".usda", ".usd"):
        from . import usd
        usd.export_usda(scene, path, only_ids=only_ids)
        return
    raise ValueError(f"Unsupported export format: {ext}")
