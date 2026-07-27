"""File import/export."""

import os

from . import native, obj, step

# The formats this module handles, as (label, extensions) — the single source
# of truth behind the file dialogs. Anything dispatched below belongs here, or
# the chooser silently stops offering it (GitHub #2: .3dm imported fine but was
# never listed, so Rhino files looked unsupported).
IMPORT_FORMATS = [
    ("Serpentine3D", (".serp",)),
    ("STEP", (".step", ".stp")),
    ("Rhino", (".3dm",)),
    ("Wavefront OBJ", (".obj",)),
    ("Autodesk FBX", (".fbx",)),
    ("STL", (".stl",)),
    ("DXF", (".dxf",)),
    ("SVG", (".svg",)),
]

EXPORT_FORMATS = [
    ("Serpentine3D", (".serp",)),
    ("STEP", (".step", ".stp")),
    ("Rhino", (".3dm",)),
    ("Wavefront OBJ", (".obj",)),
    ("Autodesk FBX", (".fbx",)),
    ("STL — 3D printing", (".stl",)),
    ("3MF — 3D printing", (".3mf",)),
    ("DXF", (".dxf",)),
    ("glTF binary", (".glb",)),
    ("USD", (".usda", ".usd")),
]

IMPORT_EXTS = {e for _, exts in IMPORT_FORMATS for e in exts}
EXPORT_EXTS = {e for _, exts in EXPORT_FORMATS for e in exts}


def _filter(formats, catch_alls: bool) -> str:
    """Build a Qt name-filter string.

    Catch-alls ("All supported", "All files") belong to reading only: they let
    you reach a file whatever it's called, and a bad guess just fails loudly on
    import. Saving is the opposite — the filter *is* the format choice, and a
    catch-all names none, leaving a typed "part" with no extension to dispatch
    on. So export lists real formats only, led (Qt selects the first) by the
    native one."""
    parts = []
    if catch_alls:
        every = " ".join(f"*{e}" for _, exts in formats for e in exts)
        parts.append(f"All supported ({every})")
    parts += [f"{label} ({' '.join('*' + e for e in exts)})"
              for label, exts in formats]
    if catch_alls:
        parts.append("All files (*)")
    return ";;".join(parts)


def import_filter() -> str:
    """Name filter for Open/Import dialogs."""
    return _filter(IMPORT_FORMATS, catch_alls=True)


def export_filter() -> str:
    """Name filter for Export dialogs."""
    return _filter(EXPORT_FORMATS, catch_alls=False)


def suffix_for_filter(name_filter: str) -> str:
    """The extension a chosen filter writes, without the dot — so a typed
    filename with no extension still saves in the selected format. The first
    extension wins when a filter lists several ("STEP (*.step *.stp)"); a
    filter naming no extension at all ("All files (*)") yields "", leaving
    whatever the user typed alone."""
    head, _, tail = name_filter.partition("(*.")
    if not head or not tail:
        return ""
    return tail.split()[0].rstrip(")").lower()


def ensure_suffix(path: str, name_filter: str) -> str:
    """Give a saved path an extension when the user typed none, so a bare
    "part" saves as the format they picked instead of failing to dispatch. A
    typed extension we can actually write wins over the dropdown; anything
    else ("my.part") keeps its text and gains the chosen suffix."""
    suffix = suffix_for_filter(name_filter)
    if not suffix:
        return path
    if os.path.splitext(path)[1].lower() in EXPORT_EXTS:
        return path
    return f"{path}.{suffix}"


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
    if ext == ".fbx":
        from . import fbx
        named = fbx.import_fbx(path)
        for name, shape in named:
            scene.add(shape, name=name)
        return len(named)
    if ext == ".stl":
        from . import stl
        named = stl.import_stl(path)
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
                thumbnail: bytes | None = None, stl_quality: str = "standard"):
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
    if ext == ".fbx":
        from . import fbx
        fbx.export_fbx([(o.name, o.shape, scene.color_of(o))
                        for o in objs], path)
        return
    if ext == ".stl":
        from . import stl
        stl.export_stl([(o.name, o.shape) for o in objs], path,
                       quality=stl_quality)
        return
    if ext == ".3mf":
        from . import threemf
        threemf.export_3mf(
            [(o.name, o.shape, scene.color_of(o)) for o in objs], path,
            unit=threemf.UNIT_3MF.get(scene.units, "millimeter"))
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
