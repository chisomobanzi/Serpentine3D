"""3MF export — the modern 3D-printing container (Bambu Studio, PrusaSlicer,
Cura all prefer it over STL).

3MF is an OPC package (a zip) with three parts: [Content_Types].xml declares
the part types, _rels/.rels points at the model, and 3D/3dmodel.model is the
mesh XML. Unlike STL it keeps real units, per-object colour, and separate
objects — so a multi-part scene stays multi-part.
"""

from __future__ import annotations

import zipfile
from xml.sax.saxutils import escape

import numpy as np

from ..core.tessellate import tessellate

_CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"

# scene.units -> 3MF unit name
UNIT_3MF = {"mm": "millimeter", "cm": "centimeter", "m": "meter",
            "in": "inch", "ft": "foot"}

_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/'
    'content-types">\n'
    '  <Default Extension="rels" ContentType="application/vnd.'
    'openxmlformats-package.relationships+xml" />\n'
    '  <Default Extension="model" ContentType="application/vnd.'
    'ms-package.3dmanufacturing-3dmodel+xml" />\n'
    '</Types>\n')

_RELS = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
    'relationships">\n'
    '  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://'
    'schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel" />\n'
    '</Relationships>\n')


def export_3mf(named_shapes: list, path: str, *, unit: str = "millimeter"):
    """named_shapes: [(name, shape)] or [(name, shape, color)]. Each shape is
    tessellated into its own 3MF object; colour (rgb 0..1) becomes a base
    material. `unit` is a 3MF unit name (see UNIT_3MF)."""
    objects = []                 # (id, name, verts, tris, color)
    oid = 2                      # id 1 is reserved for the basematerials group
    for entry in named_shapes:
        name = entry[0]
        color = entry[2] if len(entry) > 2 else None
        mesh = tessellate(entry[1])
        if not mesh.has_faces:
            continue
        verts = np.asarray(mesh.vertices, float)
        tris = np.asarray(mesh.triangles, np.int64)
        objects.append((oid, name, verts, tris, color))
        oid += 1

    model = _model_xml(objects, unit)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("3D/3dmodel.model", model)


# --------------------------------------------------------------------- helpers

def _hex(color) -> str:
    r, g, b = (max(0, min(255, round(float(x) * 255))) for x in color[:3])
    return f"#{r:02X}{g:02X}{b:02X}FF"


def _attr(text: str) -> str:
    return escape(str(text), {'"': "&quot;"})


def _model_xml(objects: list, unit: str) -> str:
    has_color = any(o[4] is not None for o in objects)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           f'<model unit="{_attr(unit)}" xml:lang="en-US" '
           f'xmlns="{_CORE_NS}">',
           ' <resources>']

    if has_color:
        out.append('  <basematerials id="1">')
        for (_oid, name, _v, _t, color) in objects:
            col = color if color is not None else (0.72, 0.72, 0.72)
            out.append(f'   <base name="{_attr(name)}" '
                       f'displaycolor="{_hex(col)}" />')
        out.append('  </basematerials>')

    for idx, (oid, name, verts, tris, _color) in enumerate(objects):
        pid = f' pid="1" pindex="{idx}"' if has_color else ""
        out.append(f'  <object id="{oid}" type="model" '
                   f'name="{_attr(name)}"{pid}>')
        out.append('   <mesh>')
        out.append('    <vertices>')
        out.extend(f'     <vertex x="{x:.6g}" y="{y:.6g}" z="{z:.6g}" />'
                   for x, y, z in verts)
        out.append('    </vertices>')
        out.append('    <triangles>')
        out.extend(f'     <triangle v1="{int(a)}" v2="{int(b)}" '
                   f'v3="{int(c)}" />' for a, b, c in tris)
        out.append('    </triangles>')
        out.append('   </mesh>')
        out.append('  </object>')

    out.append(' </resources>')
    out.append(' <build>')
    out.extend(f'  <item objectid="{oid}" />'
               for (oid, _n, _v, _t, _c) in objects)
    out.append(' </build>')
    out.append('</model>')
    return "\n".join(out) + "\n"
