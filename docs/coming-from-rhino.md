# Coming from Rhino

If you know Rhino, you'll feel at home — same command-line workflow, same
aliases, same object snaps, and it imports your Rhino shortcuts. Not every
command is here yet, but the ones that are work the way you'd expect. This
page maps your habits over and is honest about the gaps.

## What's the same

- **The command line.** Type a command, answer its prompts, click points or
  type coordinates (`10,5,0`, relative `@5,0,0`, polar `10<45`). ++tab++
  completes, ++enter++ repeats the last command.
- **Aliases.** `l`, `pl`, `c`, `m`, `co`, `mi`, `o`, `f`, … work as you'd
  expect, and you can import your own (below).
- **Object snaps** — end, mid, cen, quad, int, perp, near — on a persistent
  osnap bar, plus a construction plane (`cplane`).
- **The gumball** for move / rotate / scale, with numeric entry and Alt-drag
  copy; ++ctrl+shift++-click faces and edges for push/pull and fillets.
- **Layers**, display modes (`wireframe` / `shaded` / `ghosted` / `rendered`
  / `technical`), and **linetypes** per layer or object.
- **Two-space drafting** — model space plus paper-space **layouts** with
  detail views, associative dimensions and hidden-line output. See
  [Make a drawing sheet](howto/drawings.md).
- **Interchange** — reads and writes `.3dm` (exact NURBS curves), STEP, and
  more. See [File formats](reference/file-formats.md).

## Bring your Rhino settings over

In Rhino, export your aliases (*Options → Aliases → Export*) to a text file,
then in Serpentine3D:

- **Settings → Aliases** → import that file. Known Rhino commands are mapped
  to their Serpentine equivalents automatically; simple macros
  (`'_Zoom _Extents`, `-Osnap _Mid _Toggle`) are translated too.
- **Settings → Keyboard** → import a keybindings list (`F5 zoomextents` per
  line, or JSON) and bind any key to any command.

## Command map (a sample)

Most Rhino command names and aliases resolve directly. A few worth knowing:

| Rhino | Serpentine3D |
|---|---|
| `Line` `Polyline` `InterpCrv` | `line` `polyline` `curve` |
| `Circle` `Arc` `Rectangle` | `circle` `arc` `rectangle` |
| `ExtrudeCrv` `Revolve` `Loft` `Sweep1/2` | `extrude` `revolve` `loft` `sweep1` `sweep2` |
| `FilletEdge` `ChamferEdge` `Shell` | `filletedge` `chamferedge` `shell` |
| `BooleanUnion / Difference / Intersection` | `booleanunion` `booleandifference` `booleanintersection` |
| `Move` `Copy` `Rotate` `Scale` `Mirror` `Array` | `move` `copy` `rotate` `scale` `mirror` `array` |
| `Trim` `Split` `Join` `Explode` `Offset` | `trim` `split` `join` `offset` |
| `Layout` `Detail` `Make2D` `Dim` | `layout` `detail` `make2d` `dim` |
| `Zebra` `CurvatureAnalysis` `DraftAngleAnalysis` | `zebra` `curvature` `draftanalysis` |

The in-app `help` (or ++f1++) opens a searchable
[command reference](reference/commands.md) with every command and its aliases.

## What's different

- **Units** default to millimetres; set them with `units` (mm/cm/m/in/**feet
  & inches**), with an optional model rescale.
- A **right-click** in the viewport is Enter — it runs what you've typed or
  repeats the last command.
- **AI-native**: an [MCP server and in-app assistant](howto/ai-mcp.md) can see
  the viewport and run every command — Rhino has nothing equivalent built in.
- **Headless**: the whole engine [scripts and batches](howto/scripting.md)
  without a GUI.

## Not here yet

Serpentine3D is a young, focused modeller — it does direct NURBS/BREP
modelling and drafting well, but it is **not** a full Rhino replacement.
Notably absent today:

- **Grasshopper** / visual programming (and full history-based parametrics —
  `recordhistory` covers loft/extrude/revolve only).
- **SubD** modelling.
- A production **render engine** (`rendered` is a lit preview, not a raytracer)
  and Rhino's materials/lighting depth.
- The long tail of specialist commands, and the third-party plugin ecosystem.

If a command you rely on is missing, it's probably on the roadmap — the
project tracks requests, so it's worth asking on
[GitHub](https://github.com/chisomobanzi/Serpentine3D).

---

**Next:** [Install](getstarted/install.md) → [your first model](getstarted/first-model.md).
