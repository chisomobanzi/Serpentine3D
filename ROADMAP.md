# Roadmap & working notes

Live working notes for what is being built and why. The near-term backlog
comes from [issue #6](https://github.com/chisomobanzi/Serpentine3D/issues/6),
Lourenço Vaz Pinto's first-use report as a practising architect on Linux
(Bluefin), plus [#5](https://github.com/chisomobanzi/Serpentine3D/issues/5)
from Jonas Pedrotti.

Last updated when 0.8.2 was cut (2026-09-03).

---

## Where things stand

Version `0.8.2` in `pyproject.toml`, the lockfile and the three packaging
files; `CHANGELOG.md`'s 0.8.2 section is dated 2026-09-03. One fix, for
the first bug reported by someone who could not start the app at all
(#7, Manjaro/KDE Wayland on an RTX 3080): Serpentine3D now starts on
drivers reached through EGL, not just X11's GLX. Suite on Linux: 2709
passed, nothing skipped.

0.8.1 was a patch of fixes cut the same day as 0.8.0: far geometry and
its overlays hold still (the float32 anchors), Zoom Selected reaches
held sub-objects, a picked edge is visibly wide on every driver, and a
live fillet drag no longer lights a random edge. Released on 2026-09-02:
pushed, tagged `v0.8.1`, and published with the AppImage, the Windows
`.exe` and the macOS `.dmg` all attached.

0.8.0 was released on 2026-09-02: pushed, tagged, and published with the
AppImage, the Windows `.exe` and the macOS `.dmg` all attached. Its
suite stood at 2650 on Linux; macOS arm64 ran 2642 passed, 8 skipped.

The minor bump rather than another patch because the app does something
it could not do before. `section` is a new modelling command, and a layer
now carries a `hatch`, so a file saved by 0.8.0 holds material
information that 0.7.x drops on load. Old files still open: `native.py`
defaults the field to empty, and `FORMAT_VERSION` did not have to move.

0.7.3 was released on 2026-09-01: pushed, tagged, and published with the
AppImage, the Windows `.exe` and the macOS `.dmg` all attached.

### Wayland, released in 0.8.2

The first report from someone who could not start the app at all (#7,
Manjaro/KDE Plasma Wayland on an RTX 3080): a welcome window over a
stream of `QEGLPlatformContext: Failed to create context: 3009`, and
New Model doing nothing. Two things assumed X11's GLX. The surface
format asked for a 3.3 core profile without setting `renderableType`,
so on EGL Qt bound OpenGL ES, which has no core profile, and every
context was refused with EGL_BAD_MATCH including Qt's own backing
store. Behind that, Qt and PyOpenGL each pick GLX or EGL independently,
Qt by asking the driver and PyOpenGL by reading the session type, and
when they disagree the viewport's first GL call raises "Attempt to
retrieve context when no valid context" from inside `initializeGL`.
Both now live in `utils/glsetup.py`, which measures the binding Qt
actually got and pins PyOpenGL to it either way, since the mismatch
happens in both directions (a Wayland session falling back to XWayland
and GLX is the mirror image, and crashes identically). Reproduced with
`QT_XCB_GL_INTEGRATION=xcb_egl` and verified as a screenshot: EGL and
GLX now render the same window.

Worth remembering that this stayed hidden through eight releases
because every machine it was tested on was X11. The AppImage is the
front door for a Linux user, and Wayland is the default on most
desktops shipping today.

### Far geometry, released in 0.8.1

The last open item on Jonas's list (#5): geometry past ~100,000 units
swam as the camera orbited, because vertices and the one MVP were both
absolute float32 and the world-to-eye subtraction re-rounded every
frame. Fixed with a per-mesh anchor: far meshes upload relative to
their bounding-box centre and every matrix folds the anchor back in
via float64 (`mesh_anchor`/`rebased`/`anchored` in `ui/viewport.py`;
`utils/math3d.py` now builds float64 matrices). Near the origin the
anchor is None and the draw loop keeps its old single shared matrix,
so the cave scene's one-upload-per-frame behaviour is untouched.
Measured on Xephyr: frame-to-frame pixel churn at 500k units dropped
0.052 to 0.014 under a slow orbit, the remainder being the orbit
itself. Overlays followed on 2026-09-02: one shared anchor at the camera
target covers the gumball, control points, previews, combs, arrows,
image planes and the grid of a far cplane, byte-identical near home.

### Drafting, released in 0.8.0

Sections and hatching, driven test-first and then looked at in the
running app:

- **`section`**: draw a line across the model and get the cut back, a
  filled face from a solid so there is something to hatch
- **A layer says what its material is hatched with**, set from the Layers
  panel row menu or `layer` → Hatch, saved with the file
- **`hatch` opens on that pattern** in both Corners and Region mode
- **A section cut is drawn in the hatch of the layer it cut through**, so
  concrete and steel read apart on one detail without hand-hatching
- **`solid` is flooded, not lined**, so a cut face keeps its bores open,
  and the screen and the PDF go through the same two functions

### Layers, released in 0.7.3

The whole of the layers panel Lourenço asked for, driven test-first and
then checked in the running app or under Xephyr:

- **Sublayers**, in three commits: the model, both file formats, the panel
- The layer tree on the RPC API and the MCP server, layers named by path
- `Walls::Interior` and `Roof::Interior` no longer collide on `.3dm` import
- Layers move up and down the list with the arrows, branch and all
- A layer dropped between two rows lands there, which is also how a
  sublayer comes back out of its branch
- The layer you draw on is chosen with a double-click, not a single click
- `+` makes a layer beside the picked one, `↳` makes one inside it

### Batch 1 — released in 0.7.2

All of it driven test-first and then exercised in the running app:

- Space acts as Enter at the command line (a text prompt still takes a space)
- Right mouse button orbits by default; Shift pans, Ctrl zooms, Ctrl+Shift
  orbits out of a parallel view
- `Scene.update_many()` — 15 bulk commands now notify the scene once instead
  of once per object (isolate on 300 objects: one rebuild, not 300)
- Layer Type and Print are drop-downs, not click-to-cycle, and the panel
  now fits all five columns into the dock width the app gives it
- Multi-select layers; one checkbox toggles all selected, one undo step
- A detail's scale is editable in the Properties panel
- Enter in a Properties field no longer re-runs the last command
- Two use-after-free crashes in the layers panel

### Cleared on Linux, 2026-09-01

- **Ctrl + right-drag zoom is verified on real input.**
  `tests/run_e2e.sh tests/e2e_ctrl_zoom.py` passes 10 of 10 under Xephyr,
  the three Ctrl-alone zoom checks included, the ones Windows could not
  answer, because it drops a lone synthetic Ctrl while delivering it when
  Shift is held. `e2e_alt_swipe`, `e2e_view_history` and `e2e_dod` (24
  checks) were run too, since batch 1's move of orbit to the right button
  had made them stale and nothing in CI runs them.
- **Two batch-1 layers-panel test files were failing on Linux**, not on
  Windows: they aimed a click at the middle of a check box cell, and Fusion
  draws the box hard against the left edge, so the click landed on bare cell
  and toggled nothing. They now aim at the box the style actually draws.
  Worth knowing that these passed on Windows for a style-dependent reason.
- **`test_layer_type_and_print_cells_offer_a_drop_down.py` was not flaky
  under load.** It was leaving a drop-down open. Two of its tests read the
  list and returned without ending the edit, so the panel was collected
  while Qt still held the drop-down as the focus widget; the next test to
  show a panel activated a window, Qt handed the focus on and committed an
  editor that was no longer there, and the run took a SIGSEGV. It landed in
  whichever test opened the next panel, which is why it read as a flake.
  Both tests now close the editor. Reproduced 10 times out of 10 with
  `pytest tests/test_config_snaps.py tests/test_layer_type_and_print_cells_offer_a_drop_down.py`,
  and 0 out of 10 after. **No test may leave a cell editor open.**
- **The clipped Type/Print drop-downs were the smaller half of the problem.**
  Rendering the dock as the app actually builds it showed the tree wanted
  336px of the 280px `PANEL_WIDTH` column, so Print was off the edge behind a
  sideways scrollbar and Type was cut in half. The panel had outgrown its
  column when batch 1 added the two columns. The name column now stretches
  and the other four keep a width measured from their own content (a
  hand-picked pixel width clips the same word on a desktop set to a bigger
  font), and `_ChoiceDelegate.updateEditorGeometry` opens a drop-down at the
  width its list needs, clamped inside the view. Worth repeating: a panel
  test that resizes its own widget proves nothing about the width the app
  gives it: **build `MainWindow` and grab the dock.**

### Sublayers, 2026-09-01

Three commits, each red-green with its own tests: the model
(`core/layers.py`), the two file formats, then the panel.

- **Each layer keeps its own visible and locked switch, and inheritance is
  worked out on top.** `LayerManager.is_visible()` is own-and-all-ancestors,
  `is_locked()` is own-or-any-ancestor. This is Rhino's model, and it is
  what lets a branch come back the way you left it when its parent is
  switched on again. `Scene.visible_objects` / `selectable_objects` ask
  those two, so nothing downstream had to learn about parents.
- **The layer table cannot be returned from the importer.** The parent
  process never reads the `.3dm`: a reader process forks converters and
  only each object's `meta` crosses the pipe. So `meta` carries
  `layer_chain`, a root-first tuple of appearance dicts, one rung per
  ancestor. That is also what lets an empty parent be made with the colour
  and switches the file gave it.
- **Rhino's persistent visibility is the layer's own switch.**
  `GetPersistentVisibility()` on the way in, and on the way out both are
  written: `Visible` gets the effective answer, the persistent bit gets the
  layer's own. `Layer.PathSeparator` cannot be called from Python in
  rhino3dm 8.32, so `::` is spelled out in `core/layers.py`.
- **A synthetic drop crashes `QTreeWidget.dropEvent`.** The panel's tree
  does the whole move itself and never calls `super().dropEvent`: with
  empty `QMimeData` and no live drag the base class takes a SIGSEGV, and
  the rows belong to the scene anyway, which redraws the moment the move
  lands.
- **The drag was verified with a real pointer.**
  `tests/e2e_sublayer_drag.py` brings its own window on a Xephyr, works
  out where the rows are, and drives xdotool from a **second process**:
  a drag runs a nested event loop inside the mouse-move handler that
  started it, so a driver thread in the same process is the one that loop
  is waiting on and both hang. The panel's own tests hand `dropEvent` a
  QDropEvent, which proves the handler works but not that a drag starts.
- **An indent is charged to the name column.** It is the column that
  stretches, so the expander every row grew turned a fresh window's own
  layer into "Defa...". Indent is 12px, the colour swatch gave up 4px, and
  a test now pins the name column against `sizeHintForColumn`. Deep names
  still run out of room in a 280px dock, so every row carries its full
  path as a tooltip.
- **Going in was a drag, coming out was nothing.** A layer only got back
  out of a branch by being dropped on the blank space under the last row,
  which is a gesture nobody guesses and which is gone as soon as the
  layers fill the panel. Lourenço asked outright where he was meant to
  drag it. So there is an `↰` button beside the `↳` one, and a row menu
  that names the branch it would leave ("Move out of Walls") with the top
  level offered only where that is a different move. Right-clicking now
  reaches the panel, which nothing had tested: a tree hands its
  context-menu position on in viewport coordinates, and a handler reading
  them as widget coordinates opens the menu for the wrong row.
- **A click that picks was also a click that chose.** Clicking a name made
  that layer current, so picking three layers to switch them off left the
  last one holding the next curve, and the redraw that followed the click
  emptied the tree mid-gesture: `pressedIndex` went stale, Qt refused the
  double-click that came after it, and the rename it should have opened
  never fired. Now a click only picks, so nothing redraws under Qt, the
  double-click lands, and it is what says where geometry goes. Rename
  moved to the row menu (F2 is already View > Front), and the button row
  is grouped: make, move, delete.
- **The API learned the tree.** `scene_info` reports `path`, `parent` and
  `shown` per layer, `layers` takes a `parent` on create, and a layer can
  be named by path, because `find_by_name` picks whichever Interior comes
  first and an assistant had no way to say which one it meant. Verified
  against the packaged AppImage over RPC, not just the checkout.

- **The + button had not heard about sublayers.** It made a top-level
  layer at the end of the list however deep the picked row was, so a
  sublayer's sibling came out as its uncle, off the bottom of the panel.
  It now makes a layer beside the picked one, at the picked one's level,
  which is the pair to `↳` making one inside it, and both leave the new
  row picked, so a second press works from the layer just made. Reported
  by Lourenço Vaz Pinto, verified with a real click on the AppImage.

### Layer reorder, 2026-09-01

- **A branch is not one run of the list.** `_order` is flat and a layer
  made later can sit between a parent and its child, so a move gathers the
  branch by id, lifts it out, and puts it down past the whole of the
  sibling it is passing. Swapping two positions would have left children
  behind.
- **The loader was nailing Default to the top.** It renames the file's
  Default onto the layer a fresh scene already has and creates the rest
  around it, so a file whose first layer is Roof came back with Default
  first. `set_order` runs after the first pass and puts the file's order
  back. `.3dm` needs nothing: it is written parents-first from `all()` and
  read back in table order.
- **Picked layers move as a block.** A layer whose neighbour that way is
  picked too stays put, and the moves run from the end being travelled
  towards, so a picked run keeps its own order and stops together instead
  of the front one leapfrogging the rest.

---

### Drag a layer where it goes, 2026-09-01

- **Qt's own gap between two rows is two pixels.** That is what
  `QAbstractItemView` leaves at each end of a row for its drop indicator,
  and no hand can hit it, so the tree reads a row in three bands instead:
  a quarter at each edge means beside it, the half between them means
  inside it. Qt's indicator is off and the tree paints its own line, at
  `visualItemRect(item).left()`, which is already indented by depth, so
  the line shows the level the layer would land at as well as the gap.
- **One move covers all three drops.** `place(layer_id, parent_id,
  before_id)` puts a layer under a parent and in front of one of that
  parent's layers. A drop onto a row is that parent with nothing in front
  of it, a drop above a row is the row's parent in front of the row, and
  a drop below is the next sibling, or nothing if there is none. Coming
  back out of a branch is a drop whose parent is `None`, so the gesture
  the user asked for needed no code of its own.
- **A real mouse found two things a QDropEvent cannot.** A drag only
  begins once the pointer has left the ten-odd pixels around the press
  that Qt reads as a click, and the gap between two rows is nearer than
  that, so the driver moves sideways first. And re-entering
  `app.exec()` after a `quit()` comes back with the window no longer
  taking a drag at all: `tests/e2e_layer_drag_between.py` pumps
  `processEvents()` in a loop instead, and six checks pass.

---

## Backlog from #6

Triaged by cost. Everything below is still open unless marked.

### Cheap

| Item | Notes |
|---|---|
| **Array / ArrayPath won't start on Enter** | No code reason found — `array`, `arraypath`, `arraypolar` are registered normally (`commands/transform.py:309,338,358`). Suspect the suggestion list (`array` is a prefix of two others) or a preselection interaction. **Needs a repro from Lourenço.** |
| **Layer reorder (move up/down)** | ✅ **Done, released in 0.7.3.** `move_up`/`move_down` on `LayerManager` move a layer among its siblings and carry its branch, the `↑` and `↓` buttons move the whole picked run as a block, and `set_order` makes a file's order the one it comes back in. A layer can also be dropped into the gap between two rows, which is how it goes to either end of the list and how a sublayer comes back out of its branch. |

### Medium

| Item | Notes |
|---|---|
| **Sublayers** | ✅ **Done, released in 0.7.3.** `parent` on `Layer`, inherited visibility and locking computed by `is_visible`/`is_locked` (each layer keeps its own switch, Rhino's model), both file formats, and a tree in the panel with a sublayer button and drag-to-reparent. The `Walls::Interior` / `Roof::Interior` import collision went with it, since an imported layer is matched by full path now. Notes below. |
| **Layer hatch** | ✅ **Done.** `hatch` on `Layer` (`core/layers.py`), one of `core/layout.py HATCH_PATTERNS`, empty for none. The paper-space `hatch` command opens its Pattern prompt on it in both Corners and Region mode, `layer` has a Hatch action, and the Layers panel sets it from the row menu, on the whole selection at once. It is a submenu and not a column because the tree's five columns already fill the 280px dock exactly; a sixth comes straight out of the layer name. A section cut is drawn in the hatch of the layer of the object it cut: `Scene.hatch_of`, threaded through `_section_cut` as an owner per region and out as `cut_by_obj`. `solid` is flooded by the painter (`annot_paint.fill_cut_solid`) rather than lined, so a cut face keeps its bores open, and Region mode opens its prompt on the material under the pointer. |
| **ArrayPath orientation** (Freeform, etc.) | `commands/transform.py:338`. Needs a proper frame-along-curve. |
| **Visual feedback when picking edges** | ✅ **Fixed 2026-09-02.** The highlight asked `glLineWidth` for 3px and the driver cap made it a hairline; it now rides the screen-space thick shader, gold over a dark halo. Previously: Lourenço reported none. **It exists** — `ui/viewport.py:1864` draws picked sub-object edges. So this is a *visibility/tuning* problem (colour, width, z-bias), not a missing feature. Look at it on screen before writing code. |

### Big

| Item | Notes |
|---|---|
| **Section / cut plane** | ✅ **`section` shipped.** Draw a line, get the cut: `core/geometry.py section_regions()`/`section_curves()`/`face_loops()`, command at `commands/solids_edit.py`. A solid gives the filled face, not the outline, so a hatch has something to fill. Still open: a display-only `clippingplane` (a clip distance in the shader), and Rhino-style *live* section/plan, which is much bigger and stays deferred. `core/hlr.py` is the relevant neighbour. |
| **Navigation of large .3dm is slow** | ⚠️ **Correcting an earlier wrong diagnosis.** Frustum culling *does* exist and is well built — `ui/viewport.py:1221 _cull()`, six clip planes, vectorised across all objects. So "it renders everything" is not the cause. This needs actual profiling on a real file before anyone writes code. **Ask Lourenço for one of his heavy files.** |
| **Opening .3dm is slow** | Import path is `fileio/rhino.py` + `fileio/rhino_parallel.py` (already multi-process). Profile before optimising. |
| **Layouts not imported from .3dm** | Likely **blocked upstream**: rhino3dm 8.32's `ViewInfo` exposes only `Name`, `Viewport`, wallpaper and focal-blur — no page geometry, no detail frames. `File3dm.Views` / `NamedViews` are all that's there. Confirm, then either say so publicly or find another route. |
| **Isolate slow with many objects** | ✅ Fixed in batch 1 (`Scene.update_many`). Worth re-testing on his file. |

### Non-code

- **Flathub.** Probably the single biggest discoverability lever. Lourenço
  is on Bluefin — an immutable, Flatpak-first distro whose users will never
  find an AppImage.
- **Discoverability generally.** He couldn't find the command list, the
  website, or the icon — *all three already exist*
  (`docs/reference/commands.md`, generated by `docs/gen_commands.py`;
  chisomobanzi.github.io/Serpentine3D; `assets/logo-256.png`). That is a
  navigation problem, not a missing-feature problem. Link the command
  reference from the site's top nav and the README's first screen.
- ~~**Donations.**~~ ✅ Ko-fi, shipped July 2026 (README, site, `FUNDING.yml`).

### Open questions for Lourenço

1. A repro for Array / ArrayPath not starting on Enter.
2. One of the large .3dm files that navigates slowly (for profiling).
3. How he searched when he couldn't find the command list — that tells us
   what to fix.

---

## How this work gets done

### TDD, enforced by subagents

Every behaviour change goes RED → GREEN → REFACTOR, each phase in an
**isolated subagent** so the test author never sees the implementation plan.
Invoke the `tdd` skill; it discovers the project's runner first.

This lives at user level, not in the repo, so it must be copied to a new
machine:

```
~/.claude/skills/tdd/SKILL.md
~/.claude/agents/tdd-test-writer.md
~/.claude/agents/tdd-implementer.md
~/.claude/agents/tdd-refactorer.md
~/.claude/hooks/skill-eval.md
~/.claude/settings.json   → merge the hooks.UserPromptSubmit entry:
    {"matcher": "", "hooks": [{"type": "command",
     "command": "cat \"$HOME/.claude/hooks/skill-eval.md\"", "timeout": 5}]}
```

The hook command already uses `$HOME`, so it is portable as written. Also
copy `~/.claude/projects/<sanitised-cwd>/memory/` — the folder name is
derived from the checkout path, so it needs renaming per machine
(`/home/you/Developer/Serpentine3D` → `-home-you-Developer-Serpentine3D`).

### Then verify in the real app

Tests passing is not the finish line — batch 1 found four real bugs *after*
green tests, including two crashes, all through driving the live app.

Two routes:

- **e2e harness (preferred on Linux):** `tests/run_e2e.sh [script]` — Xephyr
  + a clean-config app + `xdotool`, with `tests/rpc_client.py` for state.
  See `tests/e2e_*.py`. This is the repo's native path and it only works on
  Linux; on Windows it had to be hand-rolled with `SendInput`, which is why
  Ctrl+RMB is still unverified.

  ⚠️ These scripts assume the **shipped** mouse defaults, so batch 1's flip
  to a right-button orbit made three of them stale (they dragged button 2).
  `e2e_alt_swipe`, `e2e_dod` and `e2e_view_history` were updated to button
  3, and `run_e2e.sh`'s header comment — which claimed a clean config meant
  a middle-button orbit — was corrected. **Any change to a default input
  binding must sweep `tests/e2e_*.py`**, because nothing in CI runs them.
- **RPC / MCP:** the same socket the MCP server uses. `serpentine3d/api.py`
  is the surface — `command`, `scene_info`, `viewport_info`, `layers`,
  `select`, `undo`, `screenshot`. Launch with `SERP3D_RPC_PORT=5777` and a
  throwaway `SERP3D_CONFIG` so it never touches real settings.

Useful launch env: `SERP3D_NO_RECOVER=1 SERP3D_NO_SPLASH=1
SERP3D_NO_WELCOME=1 SERP3D_NO_UPDATE_CHECK=1` plus `SERP3D_CONFIG`,
`SERP3D_AUTOSAVE_DIR`, `SERP3D_JOURNAL_DIR` pointed at a temp dir.

### Tests

```bash
QT_QPA_PLATFORM=offscreen uv run pytest -q          # the suite (~85s)
QT_QPA_PLATFORM=offscreen uv run pytest tests/<f> -q
uv sync --extra dev                                  # if pytest is missing
```

Named as sentences about behaviour, with a module docstring saying why it
matters to a user. `tests/conftest.py` isolates config per test and gives an
`env` fixture (scene, selection, history, ctx, proc).

---

## Codebase notes worth knowing

- **Bulk changes:** anything touching many objects goes through
  `Scene.update_many(ids, **fields)` (`core/scene.py:406`) or
  `Scene.batched()` (`:198`) — one notification per command, not per object.
  A per-object `scene.update` loop in a new command is a bug.
- **The layers panel redraws itself from the scene on every notify, and a
  click or edit ends in a notify** — so the redraw lands *inside* Qt's own
  click/edit handling. Four guards exist for the consequences (`_updating`,
  `_in_item_change`, remember/restore in `rebuild()`, the modifier check in
  `_item_clicked`), documented in the `LayersPanel` docstring. Two crashes
  came from this. Never hold a `QTreeWidgetItem` across a notify — re-find
  rows by layer id.
- **Layering rules** (from `CONTRIBUTING.md`): OCC imports stay in `core/`;
  commands never touch Qt — a command is a generator yielding typed requests
  (`PointReq`, `SelectReq`, …), which is what lets the same code serve
  clicks, typed input, macros and MCP.
- Settings defaults live in `utils/config.py`; some are also spelled inline
  at the read site, so grep the key when changing one.
