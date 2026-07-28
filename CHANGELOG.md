# Changelog

## Unreleased

- **Rhino files open across every core**: a 65259-object `.3dm` took about
  fifteen minutes to open on a 22-core machine, and the machine was idle for
  almost all of it
  ([#3](https://github.com/chisomobanzi/Serpentine3D/issues/3)). The cost is
  not the geometry kernel: it is rhino3dm's Python binding, where reading one
  float off a point costs 11 µs and reaching one mesh vertex costs 25 µs,
  against 0.25 µs for a plain Python attribute. A survey mesh has millions of
  vertices, so mesh reading alone was 90% of an import — and it is Python-side
  work, which holds the GIL, so no amount of threads would have moved it.

  Objects convert independently, so they now convert in parallel processes.
  Three details are what make that a fix rather than a disappointment. Workers
  are forked from the process that read the file, so they inherit the model
  copy-on-write instead of each paying ten seconds and a private copy to open
  it again. Objects are dealt out interleaved rather than in blocks, because a
  drawing keeps its meshes together and a block split hands one worker every
  expensive object. And the reader itself is a separate, thread-free process,
  because the app cannot fork: its tessellation threads hold locks a forked
  child would inherit already locked.

  Progress and Cancel work exactly as before. Files under 8 MB stay on the
  single-process path, where starting a helper would cost more than it saves,
  and `SERP3D_IMPORT_WORKERS=1` forces it everywhere.

- **A broken macOS build now fails the build**: 0.5.2's `.dmg` was assembled
  from an empty app bundle and reported success, because the bundle died
  before writing its selftest report and the check read the file the previous
  release had left behind.

## 0.5.2 — 2026-07-28

A performance release, measured on one 522 MB cave survey: 5933 objects,
8.3 million triangles. It drew at 5.8 fps and took nearly five seconds to
answer a click. Both of those turned out to be work the app was repeating
rather than work the machine couldn't do.

- **Big scenes are workable again**: a 5900-object cave survey drew at 5.8 fps —
  slow enough that orbiting it was guesswork. Almost none of that was the
  graphics card. The draw loop asked the driver where each shader variable
  lived, by name, once per object per frame — 26000 lookups before a single
  pixel was filled, about a third of the frame — and re-sent the camera matrix,
  the display mode and the object colour for every object even when they hadn't
  changed since the object before. It also drew everything, including the
  five-sixths of the model behind you. Uniform locations are now looked up once
  per shader, values are only sent when they actually differ, and objects whose
  bounding box falls outside the view are skipped. An object now costs two GL
  calls to draw — bind its geometry, draw it — down from about seven. Draw
  order is unchanged, so coincident surfaces and transparency still resolve
  the same way.

  The other per-frame pass had the same shape. Before drawing, the viewport
  asks every object which dash style it uses, so it can notice when the answer
  changes — and that meant fetching the object's layer once per object, plus
  an `import` statement inside the loop that Qt's import hook turned into real
  work 5900 times a frame. A drawing has thousands of objects and a few dozen
  layers, so the layers are now read once per frame and the import moved to
  the top of the file. That pass went from 11.9 ms to 2.7 ms.

  Together: the cave went from **5.8 fps to 16.6 fps zoomed out, and 48 fps
  working inside the model**, where culling does the most good.

- **Clicking to select is immediate again**: in the 5900-object cave survey,
  picking an object meant a wait of about five seconds before it highlighted.
  Deciding what you clicked on means testing the cursor against geometry, and
  that test is linear in how much geometry there is, so the fix was to stop
  looking at nearly all of it.

  Three of the four passes over the drawing were pure overhead. Each object's
  bounding box was projected to the screen one object at a time, and each
  projection rebuilt the whole camera matrix from scratch — for a camera that
  cannot move part-way through a click. The matrix is now worked out once and
  reused until the camera actually moves, the boxes are tested in a single pass
  over the drawing, and objects wholly behind the camera are ruled out rather
  than tested, which working inside a model is most of the model.

  That still left the shape a survey file actually takes: two of those 5900
  objects are scanned meshes of 3.3 million triangles each, so narrowing the
  drawing to "the objects near the cursor" narrows it to the cave. Each big
  mesh now sorts its triangles and wireframe segments into a coarse grid once,
  with a bounding box per cell, and a click rejects cells by exactly the test
  that rejects whole objects. Working inside the cave, a click went from
  **4712 ms to 134 ms**. The sort takes a second or two per million triangles,
  so it happens on a background thread when the mesh first reaches the screen —
  never on the click that needs it. Box selection and sub-object (Ctrl+Shift)
  picking take the same route and got the same speed-up.

## 0.5.1 — 2026-07-27

A fix release, all of it from one real file: a 921 MB Rhino set design that
wouldn't open. Large imports now finish, say what they are doing while they
work, and can be cancelled — plus the dialog and shading problems that turned
up alongside, and the file-format filters from
[#2](https://github.com/chisomobanzi/Serpentine3D/issues/2).

- **Large Rhino files finish importing**: a 921 MB set-design `.3dm` (17802
  objects, 1900 of them polysurfaces totalling 42k faces and 78k edges) never
  came back at all. Each face rediscovered which edges bound it by testing
  every edge in the brep — about 1.1 billion surface projections — and the
  fallback that splits an untrimmed face handed OpenCASCADE's boolean engine
  the whole edge list too, one such face taking 62 seconds. Edges are now
  pruned by bounding box first, and each stage gets only the edges it can
  actually use. The worst polysurface in that file went from an estimated 103
  minutes to 3.5, and the file as a whole now loads in about half an hour
  (13492 objects, 2.1 GB peak). Still slow, but finite — and now visible and
  interruptible while it runs.

- **Import shows what it is doing, and can be cancelled**: opening a big file
  no longer just stops repainting with no way out but killing the app. A
  progress dialog appears once the work is slow enough to warrant one, names
  the object (and, on a large polysurface, the face) being converted, and
  Cancel stops it — leaving the scene exactly as it was. Large meshes report
  as they convert too: the same file holds four over 1.5 million faces, each
  21 seconds in what used to be one uninterruptible call. That conversion also
  got about a fifth quicker on the way — it was re-resolving the mesh's face
  list once per face — so the progress costs nothing.

- **The progress dialog moves on its own**: dragging the "Opening" dialog
  dragged the main window with it. Under GNOME's `attach-modal-dialogs` a
  dialog-type window is glued to its parent; this one now asks for a normal
  window type, as the file and STL-quality choosers already did, and places
  itself over the middle of the main window rather than wherever the window
  manager felt like putting it.

- **Black objects are visible in shaded mode**: shading multiplies the object's
  colour, so an object on a black layer had nothing left to shade — it came out
  flat black against a viewport background that is itself nearly black, and the
  only way to see the model was to change the layer colour. Dark fills are now
  lifted clear of black, more the darker they are, the way Rhino keeps
  black-layer objects legible. Hue is preserved and colours that are bright
  enough already are untouched, so a dark blue stays blue and nothing else
  changes. Only the fill is lifted: edges keep the object's true colour, so a
  black object still draws black wireframe over its surface.

- **Rhino import no longer crashes on breps with unconvertible faces**: when a
  face can't be rebuilt as an exact surface, the importer falls back to its
  render mesh — but then handed that mesh to OpenCASCADE's sewer along with
  the real faces, so one bad face killed the whole file (`Add(): incompatible
  function arguments ... MeshShape`). Exact faces and mesh fallbacks are now
  kept apart, so the rest of the object still comes in as real geometry.

- **File dialogs list every supported format** ([#2](https://github.com/chisomobanzi/Serpentine3D/issues/2)):
  Open/Import were missing **Rhino `.3dm`**, DXF and SVG — all of which import
  fine — while offering `.3mf`, which can only be exported; Export was missing
  `.3dm`, DXF, glTF and USD. One shared filter string was used for both
  directions. Filters now derive from `fileio`, so the chooser can't drift from
  what the app can actually read and write.
- **Open/Import default to "All supported"**: one entry listing every readable
  format, selected by default, so you no longer have to know which format
  dropdown a file hides behind. Export is the opposite case — the filter *is*
  the format choice — so it lists real formats only (no "All files"), and a
  filename typed without an extension now takes the selected format's
  (`part` → `part.stl`) rather than failing to export.

## 0.5.0 — 2026-07-22

The "interchange" release: real interoperability with the rest of the 3D
world — FBX, STL and 3MF in and out — plus print-readiness checks, Rhino-style
linetypes and draw order on drawing sheets, and a full documentation site.

- **FBX import/export**: pure-Python, mesh-based FBX in both directions;
  exports **binary** FBX so Blender, Maya, Unreal and Unity import it cleanly.
- **STL for 3D printing**: import and export with **mesh-quality presets**
  (deflection settings) so you choose how finely exact surfaces are sampled;
  the quality dialog is untethered from the main window (GNOME fix).
- **3MF export**: modern print format alongside STL.
- **printcheck**: 3D-print readiness analysis — flags problems before you
  send a model to the slicer.
- **Linetypes on sheets**: dashed / dotted / hidden / center line styles
  (Rhino parity), with hidden-line removal now computing per-shape visible
  edges so dashed solids hide correctly in layout export (PDF/SVG).
- **Draw order**: bring-to-front / send-to-back (Rhino parity).
- **Drafting sheets**: a `+` button on the bottom tab bar to add a sheet.
- **Command line**: right-click runs the typed command (Rhino-style).
- **Documentation site**: a full MkDocs (Material) site — Diátaxis-structured
  tutorials, how-to guides, reference and explanation — published to GitHub
  Pages, with a landing page covering the headless/batch workflow, downloadable
  sample scenes, and privacy-friendly (cookieless) analytics.
- **Linux polish**: modal dialogs and file choosers untethered from the main
  window (GNOME attach-modal-dialogs), using Qt's own sized file dialog.

## 0.3.0 — 2026-07-16

The "daily-driver" release: everything learned from real playtesting,
plus the rebrand.

- **Live everywhere**: creation commands previsualise as you pick (box
  grows to the cursor, cylinder/sphere/arc ghost-follow); Rhino-style
  reference-point transforms (scale/rotate by grabbing a point and
  dragging it home) with live previews on move, copy, mirror, extrude
  and arrays.
- **Gumball, finished**: drag or click-and-type exact distances/angles/
  factors with a live readout, grid snapping, Alt-copy — and a hard
  crash fixed (OCCT null-surface segfault when scaling a second axis).
- **Right mouse button**: Enter during a command (finishes selections,
  accepts defaults), repeat-last when idle, drag still orbits; commands
  now terminate cleanly when done (a bubbled Return used to re-run
  them instantly).
- **Viewports**: dockable/floatable extra viewports — model space and a
  paper sheet side by side; zoom tools (zoomselected/zoomwindow/zoom).
- **New commands**: orient/orient3pt, closecrv, clipping planes
  (gumball-movable section planes), selection filters (F6), pipe,
  point/divide, dupborder/dupedge, untrim, edgesrf, extractisocurve,
  seldup, purge, what, boundingbox, viewcapture to file/clipboard,
  back/left/bottom views, osnap toggles, command macros.
- **Rhino import**: aliases *and* keyboard shortcuts from a real Rhino
  8 settings file map onto Serpentine3D equivalents (62/88 in the
  reference setup), with user shortcuts overriding built-in keys.
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
- Desktop integration (`packaging/install-desktop.sh`): launcher,
  icon, `.serp` file association; MIT licence; `examples/hero_scene.py`.

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
