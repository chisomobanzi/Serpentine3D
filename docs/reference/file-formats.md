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
| `.svg` | ✓ | ✓ | Paths import as curves (béziers exact); layouts export as vector SVG |
| `.glb` |  | ✓ | Binary glTF with materials (Unreal / Blender / web) |
| `.usda` / `.usd` |  | ✓ | USD for virtual-production pipelines |
| `.e57` | ✓ |  | Point clouds: separate registered scans with RGB colours; Cartesian and spherical coordinates |
| `.skp` | ✓ |  | SketchUp 2013 onward: groups and components as solids and polysurfaces, tags as layers, material colours |

## Notes

- **E57 scans.** Choose File > Import or drag an `.e57` file into the window.
  Each scan becomes a separate named point cloud, positioned using its stored
  scan pose. E57 coordinates are in metres and are converted to the current
  model units. Invalid samples are omitted; 16-bit colours are converted to
  8-bit RGB for display. Save as `.serp` to retain the imported clouds. Embedded
  photographs, intensity and scanner-specific metadata are not imported.
- **SketchUp files.** Choose File > Import or drag a `.skp` into the window;
  SketchUp itself is not needed, on any platform. Each group or component at
  the top of the model becomes an object for every separate body in it,
  joined into a solid where its faces close, so push/pull, booleans and
  fillets work on it; stray edges come in as curves beside it, and what one
  group made is grouped so it selects together. Faces loose at the top of the
  model come in one object per tag. Tags become layers with their colours and
  visibility, and a group's material colour becomes its colour. Sizes are
  converted from SketchUp's inches to the model units. Curved surfaces arrive
  as the flat facets SketchUp draws them with, every facet edge showing;
  textures, face-by-face colours, scenes and dimensions are not imported. The
  file is read by [OpenSKP](https://github.com/iamahsanmehmood/openskp), which
  does not yet read every file: some saved by SketchUp 2018 and 2019 and by
  very old versions fail, and say so. Export those from SketchUp as OBJ, FBX
  or DXF instead.
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
