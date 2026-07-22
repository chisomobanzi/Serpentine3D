# File formats

`open` / `import` read a file into the scene; `save` / `export` write it. The
format is chosen by extension.

| Format | Import | Export | Notes |
|---|:---:|:---:|---|
| `.serp` | ✓ | ✓ | Native: JSON scene + embedded binary BREP, thumbnail and metadata |
| `.step` / `.stp` | ✓ | ✓ | Exact BREP exchange via OpenCASCADE |
| `.3dm` | ✓ | ✓ | Rhino: exact NURBS curves both ways; breps import as untrimmed NURBS faces, export as meshes; layers preserved |
| `.obj` | ✓ | ✓ | Tessellated mesh with `.mtl` colours |
| `.fbx` | ✓ | ✓ | Autodesk FBX (**binary**) — tessellated meshes; imports/exports cleanly to Blender, Maya, Unreal, Unity |
| `.stl` | ✓ | ✓ | 3D printing — watertight binary (or ASCII) STL for slicers, with draft→ultra mesh-quality presets on export |
| `.3mf` |  | ✓ | 3D printing — modern container with real units, colour and multi-part; preferred by Bambu Studio / PrusaSlicer / Cura |
| `.dxf` | ✓ | ✓ | Curves/meshes with layers; layout sheets export at paper scale |
| `.svg` | ✓ | ✓ | Paths import as curves (béziers exact); layouts export as vector SVG |
| `.glb` |  | ✓ | Binary glTF with materials (Unreal / Blender / web) |
| `.usda` / `.usd` |  | ✓ | USD for virtual-production pipelines |

## Notes

- **Exact vs. mesh.** `.serp`, `.step` and `.3dm` carry exact geometry.
  `.obj`, `.fbx`, `.stl`, `.3mf`, `.glb` and `.usd` are tessellated meshes —
  the display deflection (or STL quality preset) sets how fine.
- **Layouts.** `exportpdf` and `exportsvg` write drawing sheets, honouring
  [linetypes](../howto/drawings.md) and hidden-line detail modes.
- **Coordinate system.** Serpentine3D is Z-up. FBX export declares the Z-up
  axis system so orientation survives into Blender and others.
- **Headless.** Every format works from a script — `doc.export("part.step")`
  or `serp3d-batch` (see [Script & automate](../howto/scripting.md)).
