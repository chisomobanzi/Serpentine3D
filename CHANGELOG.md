# Changelog

## Unreleased

- `dot` — Rhino-style model-space annotation dots: camera-facing label
  bubbles anchored to 3D points, constant screen size, selectable,
  saved in `.serp`. Copies, mirrors, arrays and orient now carry
  object colour, material, annotation and group across (`add_from`).
- Daily-driver command batch: `pipe` (round-corner tube along any rail,
  capped or open), `point` / `divide` (point objects with viewport
  markers, picking, snapping and `.serp` round-trip), `dupborder` /
  `dupedge` (extract naked borders or Ctrl+Shift-picked edges as
  curves), `untrim` (Holes/All modes), `edgesrf` (Coons patch from
  2–4 connected curves), `extractisocurve` (U/V/Both at a picked
  point), `seldup`, `purge` (empty layers + unused blocks) and `what`
  (object report: kind, layer, measures, bbox, validity).
- Renamed to **Serpentine3D** across the board (after Rhinoceros3D /
  Rhino3D): Python package `serpentine3d`, CLI `serp3d` /
  `serp3d-mcp` / `serp3d-batch` (`serp` kept as a convenience alias),
  desktop entry + icon + `application/x-serpentine3d` MIME type, data
  dirs `~/.serpentine3d` and `~/.config/serpentine3d` (pre-rename dirs
  migrate automatically on first launch), plugin entry-point group
  `serpentine3d.plugins`, drop-in hook `serpentine3d_plugin(ctx)`,
  env vars `SERP3D_*`, AppImage `Serpentine3D-x86_64.AppImage`.
  `.serp` files keep their extension; files saved before the rename
  still load.

## 0.2.0 — 2026-07-14

The "documentation and depth" release: nine feature waves on top of the
0.1 core.

### Modelling
- Sub-object selection (Ctrl+Shift+click edges/faces) feeding
  `filletedge` (smooth chains, variable start/end radii),
  `chamferedge` and `pushpull`.
- Deformers: `twist`, `taper`, `bend`, `flow` (curve-to-curve with
  rotation-minimizing frames).
- `extend`, `matchcrv` (G0/G1), curvature combs (`curvaturegraph`),
  `draftanalysis` display mode, `zebra`, false-colour curvature.
- Native mesh objects: OBJ/3DM/DXF meshes import instantly without
  sewing, transform, export and round-trip through `.serp`;
  `meshtobrep` / `breptomesh` convert both ways.
- Central tolerance policy (`core/tolerance.py`).

### UX
- Clickable command option chips, settable any time (`Cap=Yes`,
  `BothSides`, `Style`...), Rhino-style `Name=Value` typing.
- Live ghost previews while typing values (extrude, offsetsrf).
- `help` command + F1 searchable command browser; arrow-key nudge
  (Shift ×10, Ctrl ×0.1); scroll zoom anchors under the cursor.
- Gumball manipulator, settings dialog, osnap bar, mouse remapping,
  Rhino alias/shortcut import (0.1.x, polished here).

### Drafting
- Annotations on sheets are selectable, draggable, deletable and
  editable (`annotedit`); detail frames move/resize with grips.
- Associative dimensions anchored through detail views.
- Named annotation styles (`dimstyle`), multiline text, click-region
  hatching from detail linework, `sheetindex`, per-sheet revision
  tables.

### Performance
- Background tessellation with AABB placeholders for heavy shapes.
- Picking prefiltered by projected bounds; granular scene
  notifications keep panels quiet during sheet edits.
- Screen-space wide-line shader (llvmpipe-safe) + per-layer
  lineweights on screen.

### Rendering & viewports
- `4view` quad layout (Top/Front/Right/Perspective, all live).
- Per-object materials (metallic/roughness/opacity) with presets,
  exported to GLB PBR and bound UsdPreviewSurface in USDA.
- `rendered` display mode: studio lighting, ground shadow, sorted
  transparency.

### Robustness & platform
- `.serp` v2: atomic zip container with metadata + thumbnail; v1 still
  loads.
- Record history: `recordhistory` makes loft/extrude/revolve rebuild
  when their input curves change; records persist and undo.
- Seeded fuzz tests and an HLR crash corpus against the isolated
  hidden-line worker.
- Plugin architecture: `~/.serpentine3d/plugins/*.py` or
  `serpentine3d.plugins` entry points; Plugins menu; `plugins` command.
- mkdocs documentation site (`docs/`), AppImage recipe
  (`packaging/appimage`), 160+ unit/integration tests + 24-check GUI
  E2E suite.

## 0.1.0 — 2026-07

Initial build: OCC-backed scene, generator command engine, viewport
with snaps/CPlanes/display modes, curves→surfaces→solids→booleans,
transforms, layers, undo, units (feet-inches), autosave + crash
recovery, STEP/3DM/OBJ/DXF/SVG/GLB/USD/PDF interchange, layouts with
HLR details, Python console + API + batch, MCP server, CI.
