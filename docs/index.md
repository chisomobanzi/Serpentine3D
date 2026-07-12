# Serpentine

**An open-source NURBS surface modeller for Linux, with native AI
integration via MCP.**

Serpentine (`serp`) is a freeform surface modeller in the spirit of
Rhinoceros 3D — exact BREP/NURBS geometry on the OpenCASCADE kernel, not
meshes. It is built for set designers, architects and industrial
designers who want a genuine Rhino-style workflow on Linux: a command
line that prompts for input, layers, object snaps, construction planes,
paper-space drafting, STEP/3DM/OBJ interchange, and a dark, focused
interface.

## Highlights

- **Command-line driven.** Type `loft`, click curves, done. Clickable
  option chips (`Cap=Yes`), live ghost previews while you type values,
  Rhino alias import.
- **Exact geometry.** Solids, lofts, sweeps, fillets with chains and
  variable radii, booleans, offsets, shelling, deformers (twist, taper,
  bend, flow), draft-angle and curvature analysis.
- **Drafting.** Paper-space layouts with detail views, hidden-line
  rendering, associative dimensions, hatches, revision tables, PDF/SVG
  output.
- **Fast on big scenes.** Background tessellation, picking culled by
  screen bounds, native mesh objects for heavy OBJ/3DM props.
- **AI-native.** A bundled MCP server lets Claude (or any MCP client)
  see the viewport, create geometry and run every command.
- **Extensible.** Drop-in Python plugins, a stable scripting API, a
  Python console, and headless batch mode.

## Where next

- [Install](install.md)
- [Tutorial: model a stage flat](tutorial.md)
- [Command reference](commands.md)
