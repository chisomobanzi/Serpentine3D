# Roadmap & working notes

Live working notes for what is being built and why. The near-term backlog
comes from [issue #6](https://github.com/chisomobanzi/Serpentine3D/issues/6),
Lourenço Vaz Pinto's first-use report as a practising architect on Linux
(Bluefin), plus [#5](https://github.com/chisomobanzi/Serpentine3D/issues/5)
from Jonas Pedrotti.

Last updated after batch 1 (commit `7841794`, 2026-08-27).

---

## Where things stand

Version `0.7.1` in `pyproject.toml`; `CHANGELOG.md` has an unreleased
`0.7.2` section holding batch 1. **The version bump and release have not
been cut.** Suite: 2392 passed, 9 skipped.

### Batch 1 — shipped, unreleased

All of it driven test-first and then exercised in the running app:

- Space acts as Enter at the command line (a text prompt still takes a space)
- Right mouse button orbits by default; Shift pans, Ctrl zooms, Ctrl+Shift
  orbits out of a parallel view
- `Scene.update_many()` — 15 bulk commands now notify the scene once instead
  of once per object (isolate on 300 objects: one rebuild, not 300)
- Layer Type and Print are drop-downs, not click-to-cycle
- Multi-select layers; one checkbox toggles all selected, one undo step
- A detail's scale is editable in the Properties panel
- Enter in a Properties field no longer re-runs the last command
- Two use-after-free crashes in the layers panel

### Needs a human before release

- **Ctrl + right-drag zoom is unverified by hand.** It has a passing test
  through the real viewport event path, but on the Windows box synthetic
  Ctrl never reached the app (Shift did — some global hook ate it), so it
  was never driven end-to-end. Try it once on Linux.
- **Cosmetic:** the layers panel Type/Print combo editors are clipped by the
  narrow columns ("Contin ⌄"). Widen the columns or the editor.
- `tests/test_layer_type_and_print_cells_offer_a_drop_down.py` is
  timing-sensitive: it relies on a zero-timer redraw plus `qWait`. It passes
  clean but flaked once under heavy CPU contention (two suites at once).

---

## Backlog from #6

Triaged by cost. Everything below is still open unless marked.

### Cheap

| Item | Notes |
|---|---|
| **Array / ArrayPath won't start on Enter** | No code reason found — `array`, `arraypath`, `arraypolar` are registered normally (`commands/transform.py:309,338,358`). Suspect the suggestion list (`array` is a prefix of two others) or a preselection interaction. **Needs a repro from Lourenço.** |
| **Layer reorder (move up/down)** | Needs layer order to be first-class and persisted. Do it with sublayers — same data change. |

### Medium

| Item | Notes |
|---|---|
| **Sublayers** | The big one for architects, and a latent correctness bug: `fileio/rhino.py:680 read_layers()` reads only `layer.Name`, so `Walls::Interior` and `Roof::Interior` collide on import. **Confirmed viable:** rhino3dm 8.32 exposes `Layer.ParentLayerId` and `Layer.FullPath`. Work: `parent` field on `Layer` (`core/layers.py:24`, frozen dataclass), hierarchy in the panel (already a `QTreeWidget`), inherited visibility/lock, save format, undo snapshot. |
| **Layer hatch** | A `hatch` field on `Layer`, used as the default by the paper-space `hatch` command (`commands/drafting.py:431`). Machinery exists: `core/layout.py:105 Hatch`, `:236 hatch_lines()`. But "hatch when cut" implies the section tool — do that first. |
| **ArrayPath orientation** (Freeform, etc.) | `commands/transform.py:338`. Needs a proper frame-along-curve. |
| **Visual feedback when picking edges** | Lourenço reported none. **It exists** — `ui/viewport.py:1864` draws picked sub-object edges. So this is a *visibility/tuning* problem (colour, width, z-bias), not a missing feature. Look at it on screen before writing code. |

### Big

| Item | Notes |
|---|---|
| **Section / cut plane** | Split it. A display-only `clippingplane` is modest (a clip distance in the shader). A `section` command returning curves is easy on OCC (`BRepAlgoAPI_Section` with a plane). Rhino-style *live* section/plan is much bigger — defer. `core/hlr.py` is the relevant neighbour. |
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
- **Donations.** GitHub Sponsors / Ko-fi — a five-minute README + site edit.

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
