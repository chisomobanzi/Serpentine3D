# Serpentine

**An open-source NURBS surface modeller for Linux, with native AI integration via MCP.**

Serpentine (`serp`) is a freeform surface modeller in the spirit of Rhinoceros 3D —
BREP/NURBS geometry on the OpenCASCADE kernel, not meshes. It is built for set
designers, architects, and industrial designers who want a genuine Rhino-style
workflow on Linux: a command line that prompts for input, layers, object snaps to
a construction plane, STEP/OBJ interchange, and a dark, focused interface.

Named for the serpentine stone of Zimbabwean Shona sculpture, and for the
S-curve at the heart of NURBS geometry.

![Serpentine screenshot](screenshots/17_showcase.png)

## Why

- **No genuine open-source NURBS modeller exists for Linux.** FreeCAD is
  parametric CAD; Blender is mesh-based. Serpentine fills the freeform
  surface-modelling gap.
- **First CAD tool with native AI integration.** The bundled MCP server lets
  Claude (or any MCP client) see your viewport, create geometry, run any
  command, and manage the scene.

## Install

Requires Python 3.10+ on Linux with OpenGL 3.3.

```bash
git clone <this-repo> && cd Serpentine3D
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/serp        # launch
```

The OpenCASCADE kernel ships as pip wheels (`cadquery-ocp`) — no conda, no
system packages.

## The command line

Everything works Rhino-style: type a command, answer its prompts. Prompts accept
typed coordinates (`10,5,0`, relative `@5,0,0`) or viewport clicks on the
construction plane. `Tab` completes command names, `Up`/`Down` recall history,
`Enter` on an empty line repeats the last command, `Escape` cancels.

| | Commands |
|---|---|
| **Curves** | `line` `polyline` `curve` (interpolated NURBS) `circle` `arc` `ellipse` `rectangle` |
| **Surfaces** | `extrude` `revolve` `loft` `sweep1` `planarsrf` |
| **Solids** | `box` `sphere` `cylinder` `cone` `torus` |
| **Booleans** | `booleanunion` `booleandifference` `booleanintersection` |
| **Transform** | `move` `copy` `rotate` `scale` `scalenu` `mirror` `array` |
| **Edit** | `join` `explode` `offset` `fillet` `delete` `hide` `show` `rename` `undo` `redo` |
| **Analysis** | `distance` `length` `area` `volume` |
| **View** | `top` `front` `right` `perspective` `zoomextents` `wireframe` `shaded` `ghosted` `grid` `snap` |
| **Layers** | `layer` (new/current/show/hide/rename) — or use the Layers panel |
| **Files** | `new` `open` `save` `import` `export` |

Most commands have Rhino-compatible aliases (`l`, `pl`, `c`, `m`, `co`, `mi`, ...).

### Navigation & shortcuts

- **Middle mouse** orbit · **Shift+Middle** pan · **Scroll** zoom
- **F1–F4** top/front/right/perspective · **Ctrl+E** zoom extents · **F7** grid
- **Ctrl+Z / Ctrl+Y** undo/redo · **Ctrl+A** select all · **Delete** delete selection
- **Ctrl+S / Ctrl+O / Ctrl+N** save/open/new
- Click to select (Shift-click adds), click empty space to deselect
- **Object snaps** (end/mid/center) are on by default while picking points —
  a white square marks the snap; toggle with `snap`
- Launch with a file: `serp model.serp` (or any importable format)

## File formats

| Format | Import | Export | Notes |
|---|---|---|---|
| `.serp` | ✓ | ✓ | Native: JSON scene + embedded binary BREP |
| `.step` / `.stp` | ✓ | ✓ | Exact BREP exchange via OCCT |
| `.obj` | ✓ | ✓ | Tessellated mesh |

## MCP server (AI integration)

Serpentine exposes its full modelling surface as MCP tools. Start the app,
then register the server with your MCP client:

```bash
claude mcp add serpentine -- /path/to/.venv/bin/serp-mcp
```

Tools: `serp_scene_info`, `serp_screenshot` (returns an image of the viewport),
`serp_create_curve`, `serp_create_surface`, `serp_boolean`, `serp_transform`,
`serp_select`, `serp_command` (run any command with its interactive inputs),
`serp_layers`, `serp_import`, `serp_export`, `serp_measure`, `serp_undo`,
`serp_viewport`.

The combination of `serp_screenshot` and `serp_command` means an AI assistant
can model alongside you: it sees what you see and can operate every tool the
command line offers. The bridge is a localhost-only JSON-RPC socket
(`~/.serpentine/rpc.port`); set `SERP_NO_RPC=1` to disable it.

## Architecture

```
serpentine/
├── core/          # kernel layer: geometry builders, tessellation,
│                  #   scene graph, layers, selection, undo history
├── commands/      # generator-based interactive commands (Rhino-style
│                  #   prompt protocol, shared by GUI + MCP)
├── ui/            # Qt: GL viewport, command line, panels, dark theme
├── fileio/        # .serp / STEP / OBJ
├── mcp_server/    # stdio MCP server -> RPC bridge
├── api.py         # programmatic API over a running session
└── rpc.py         # localhost JSON-RPC bridge
```

Geometry is exact BREP on OpenCASCADE 7.9 (via the `OCP` pybind11 bindings);
the viewport tessellates on demand with trim-aware isocurve display. Commands
are Python generators that yield typed input requests — the same command code
serves typed input, viewport clicks, and MCP calls.

## Development

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest            # unit tests (geometry, scene, commands, file I/O)
```

## License

MIT
