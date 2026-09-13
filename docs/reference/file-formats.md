# File formats

`open` / `import` read a file into the scene; `save` / `export` write it. The
format is chosen by extension.

| Format | Import | Export | Notes |
|---|:---:|:---:|---|
| `.serp` | ✓ | ✓ | Native: JSON scene + embedded binary BREP, thumbnail and metadata |
| `.step` / `.stp` | ✓ | ✓ | Exact BREP exchange via OpenCASCADE |
| `.3dm` | ✓ | ✓ | Rhino: exact NURBS curves both ways; breps import as trimmed NURBS faces, export as meshes (use STEP for exact surfaces); layers with visibility/lock and hidden objects preserved; writes Rhino 5–8 |
| `.obj` | ✓ | ✓ | Tessellated mesh with `.mtl` colours |
| `.fbx` | ✓ | ✓ | Autodesk FBX (**binary**) — tessellated meshes; imports/exports cleanly to Blender, Maya, Unreal, Unity |
| `.stl` | ✓ | ✓ | 3D printing — watertight binary (or ASCII) STL for slicers, with draft→ultra mesh-quality presets on export |
| `.3mf` |  | ✓ | 3D printing — modern container with real units, colour and multi-part; preferred by Bambu Studio / PrusaSlicer / Cura |
| `.dxf` | ✓ | ✓ | Curves/meshes with layers; layout sheets export at paper scale |
| `.dwg` | ✓ | — | Bundled LibreDWG reader; geometry coverage follows DXF import; model and layout drops |
| `.svg` | ✓ | ✓ | Paths import as curves (béziers exact); layouts export as vector SVG |
| `.glb` | ✓ | ✓ | Binary glTF static meshes with base materials (Unreal / Blender / web) |
| `.usda` / `.usd` |  | ✓ | USD for virtual-production pipelines |
| `.e57` | ✓ |  | Point clouds: separate registered scans with RGB colours; Cartesian and spherical coordinates |

## Notes

- **GLB models.** Choose File > Import or drop a `.glb` into a model viewport.
  Static triangle meshes retain their names, node transforms and base material
  colour, opacity, metallic and roughness values. glTF uses Y-up coordinates
  and metres; imports convert to Z-up and the current model units. Texture maps,
  per-vertex colours, animation and rigging are not reproduced. Compressed meshes that require an
  unsupported extension must be re-exported without compression.
  Older Serpentine GLB exports wrote raw model units instead of metres; those
  files may need manual scaling when imported. New exports use metres.
- **DWG drawings.** Choose File > Import or drag a `.dwg` onto a model viewport.
  Dropping onto a layout sheet places its supported geometry at the cursor;
  dropping inside an entered detail imports into the model. The Windows,
  macOS and AppImage packages include LibreDWG, so no extra installation or
  network connection is needed. Conversion uses a temporary copy and leaves
  the original drawing unchanged. This is geometry import, not full AutoCAD
  document fidelity: blocks, text, dimensions, hatches, external references,
  ACIS solids and paper-space layouts are not reconstructed by the current
  DXF importer. DWG export is not offered.
- **E57 scans.** Choose File > Import or drag an `.e57` file into the window.
  Each scan becomes a separate named point cloud, positioned using its stored
  scan pose. E57 coordinates are in metres and are converted to the current
  model units. Invalid samples are omitted; 16-bit colours are converted to
  8-bit RGB for display. Save as `.serp` to retain the imported clouds. Embedded
  photographs, intensity and scanner-specific metadata are not imported.
- **Exact vs. mesh.** `.serp` and `.step` carry exact geometry both ways;
  `.3dm` is exact for curves but writes surfaces and solids as meshes — for
  an exact round trip through Rhino, export STEP and `import` it there.
  `.obj`, `.fbx`, `.stl`, `.3mf`, `.glb` and `.usd` are tessellated meshes —
  the display deflection (or STL quality preset) sets how fine.
- **Layouts.** `exportpdf` and `exportsvg` write drawing sheets, honouring
  [linetypes](../howto/drawings.md) and hidden-line detail modes.
- **Coordinate system.** Serpentine3D is Z-up. FBX export declares the Z-up
  axis system so orientation survives into Blender and others.
- **Headless.** Every format works from a script — `doc.export("part.step")`
  or `serp3d-batch` (see [Script & automate](../howto/scripting.md)).
