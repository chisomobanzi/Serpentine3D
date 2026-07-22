# Serpentine3D

**An open-source NURBS surface modeller for Linux, Windows & macOS — a
Rhino-style workflow with native AI (MCP) integration.**

Serpentine3D (`serp3d`) is a freeform surface modeller in the spirit of
Rhinoceros 3D — exact BREP/NURBS geometry on the OpenCASCADE kernel, not
meshes. It is built for set designers, architects and industrial designers
who want a genuine Rhino-style workflow: a command line that prompts for
input, layers, object snaps, construction planes, paper-space drafting, and
STEP / 3DM / OBJ / FBX / STL interchange. The whole modelling engine also
runs headless, so anything you build by hand can be scripted, batch-processed
or driven by an AI.

!!! tip "If you know Rhino"
    You'll feel at home — the same command-line workflow, the same aliases,
    the same object snaps, and it even imports your Rhino shortcuts. Not every
    command is here yet, but the ones that are work the way you'd expect.

## Highlights

- **Command-line driven.** Type `loft`, click curves, done. Clickable option
  chips (`Cap=Yes`), live ghost previews while you type values, Rhino alias
  import, and a right-click that runs whatever you've typed.
- **Exact geometry.** Solids, lofts, sweeps, fillets with chains and variable
  radii, booleans, offsets, shelling, deformers (twist, taper, bend, flow),
  draft-angle and curvature analysis.
- **Drafting.** Paper-space layouts with detail views, hidden-line rendering,
  associative dimensions, hatches, revision tables, linetypes and PDF/SVG
  output.
- **3D printing.** Watertight STL and modern 3MF export with mesh-quality
  presets, plus a `printcheck` command that reports watertight/manifold,
  thin walls, overhangs and print size.
- **Fast on big scenes.** Background tessellation, picking culled by screen
  bounds, native mesh objects for heavy OBJ/3DM/STL props.
- **AI-native.** A bundled MCP server lets Claude (or any MCP client) see the
  viewport, create geometry and run every command.
- **Headless-first.** A stable scripting API (`Document`), `serp3d-batch` for
  CI, and a Python console — the command layer is fully decoupled from the UI.

## Where next

- [Install](install.md) — download a build or run from source
- [Tutorial: model a stage flat](tutorial.md)
- [Scripting & plugins](scripting.md) · [AI / MCP integration](mcp.md)
- [Command reference](commands.md)
