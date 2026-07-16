# Contributing to Serpentine3D

Thanks for looking under the hood. Bug reports, commands, and file-format
work are all welcome — this project aims to be a serious NURBS modeller
for Linux, and it gets there faster with more hands.

## Dev setup

```bash
git clone https://github.com/chisomobanzi/Serpentine3D.git
cd Serpentine3D
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/serp3d                # run the app
```

Python ≥ 3.10. The heavy dependency is `cadquery-ocp` (OpenCASCADE 7.9
prebuilt as pybind11 bindings) — it's a large wheel, but there is nothing
to compile.

## Running the tests

```bash
.venv/bin/pytest                          # the whole suite
QT_QPA_PLATFORM=offscreen .venv/bin/pytest   # headless (what CI does)
.venv/bin/pytest tests/test_commands.py -k fillet   # one area
```

CI runs the suite on Python 3.12 plus a `serp3d-batch` smoke test.
PRs need green CI; if you change behaviour, add or update a test that
would have caught the regression.

## Where things live

```
serpentine3d/
├── core/          # kernel layer: geometry builders, tessellation,
│                  #   scene graph, layers, selection, undo history
├── commands/      # generator-based interactive commands
├── ui/            # Qt: GL viewport, command line, panels
├── fileio/        # .serp / STEP / OBJ / glTF / DXF / SVG / USD
└── mcp_server/    # stdio MCP server -> RPC bridge
```

Two rules keep the layers clean:

1. **All OCP/OpenCASCADE imports stay in `core/`** (mostly
   `core/geometry.py`). Commands and UI talk to shapes only through the
   `core` API — this is what keeps commands testable without a display
   and the kernel swappable in principle.
2. **Commands never touch Qt.** A command is a Python generator that
   yields typed requests (`PointReq`, `NumberReq`, `SelectReq`, …) and
   receives the answer back — the same code serves viewport clicks,
   typed input, macros, and MCP calls.

## Adding a command

The generator protocol in one example:

```python
from .base import PointReq, NumberReq, command
from ..core import geometry as g

@command("tube", aliases=("tu",))
def cmd_tube(ctx):
    centre = yield PointReq("Centre of tube")
    radius = yield NumberReq("Radius", default=5.0)
    ctx.scene.add(g.make_cylinder(centre, radius, radius * 4), name="Tube")
    ctx.echo("Tube created.")
```

Registering it (import the module in `commands/__init__.py`) gets you
prompts, osnaps, undo, aliasing, macro support, and MCP exposure for
free. Look at `commands/curves.py` and `commands/transform.py` for
fuller examples — previews (`preview_fn`), option chips (`choices`),
and reference-point input are all shown there.

If the command exists in Rhino, keep its name and prompt order —
matching existing muscle memory is a design goal, not an accident.

## Pull requests

- Keep PRs focused; separate refactors from behaviour changes.
- Match the surrounding style (the codebase is plain PEP 8, no
  formatter is enforced).
- Describe *what a user can now do*, not just what the code does.
- Screenshots or a short capture for anything visual — there's a
  built-in `viewcapturetofile` command that helps.

Not sure whether an idea fits? Open an issue or a discussion first —
cheap to talk, expensive to rewrite.
