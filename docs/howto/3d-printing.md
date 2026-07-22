# Export for 3D printing

Serpentine3D models are exact solids, so they export as clean, watertight
meshes. Two formats and a pre-flight check cover the whole workflow.

## Check it's printable first

Run `printcheck`, select your objects, and read the report:

```
printcheck
```

```
Bracket — PRINT-READY
  watertight: yes · manifold: yes
  size: 40 x 25 x 12 mm
  min wall: 12 mm
  overhangs >45°: 28.4% of surface — may need supports
```

- **watertight / manifold** — for a solid these come from the geometry itself,
  so a valid solid always passes (tessellation slivers won't raise false
  alarms). An *imported mesh* is judged by its actual triangle connectivity.
- **min wall** — the thinnest wall found, flagged `(THIN)` below the threshold.
- **overhangs** — downward-facing area steeper than 45° from vertical
  (excluding the face resting on the build plate), i.e. what would want
  supports.

## STL

`export` → **STL — 3D printing**. Serpentine writes **binary STL** (compact,
what every slicer expects) and asks for a mesh quality:

| Preset | Curves | File size |
|---|---|---|
| Draft | coarse, faceted | smallest |
| Standard | matches the on-screen mesh | small |
| **Fine** *(default)* | smooth | medium |
| Ultra fine | maximum detail | largest |

Finer presets tessellate curved surfaces into more triangles — smoother
prints, bigger files. All objects merge into one watertight mesh.

## 3MF

`export` → **3MF — 3D printing**. The modern container that Bambu Studio,
PrusaSlicer and Cura prefer over STL: it keeps **real units**, **per-object
colour**, and **separate objects** instead of one merged soup.

## Do it headless

Both formats work from a script or CI (see [Script & automate](scripting.md)):

```python
doc.export("bracket.stl")        # Standard quality
# finer mesh:
from serpentine3d.fileio import stl
stl.export_stl([(o.name, o.shape) for o in doc.objects()],
               "bracket.stl", quality="fine")
```

## Tips

- STL carries no units — slicers assume millimetres, so model in mm (or use
  3MF, which stores the unit).
- Thin walls print poorly; if `printcheck` flags `(THIN)`, thicken with
  `shell` or a push/pull before exporting.
- Reorient the part so large overhangs face upward, or plan for supports.
