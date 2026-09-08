# Script & automate

The whole modelling engine runs with or without a GUI, so anything you can do
by hand can be scripted, batch-processed, or driven by an AI. The command
layer is fully decoupled from Qt.

## The Script pane

Open **Script** in the bottom workspace or **Tools → Script Editor**
(++ctrl+grave++). The editor, assistant and command
history can sit alongside each other; use **Expand** or drag the dividers
when you need more room. Hiding the pane keeps your draft.

Open drafts, their file paths and unsaved text are recovered after a normal
app close. Use **Save** to write a reusable `.py` file; recovered drafts are
not a substitute for saving your scripts.

Use the close button on a script tab to remove that draft. Unsaved code offers
**Save**, **Discard**, or **Cancel**; canceling a save keeps the tab open.
Closing a draft does not remove geometry you have already kept. Resolve a
running script or its pending preview with **Stop**, **Keep**, or **Discard**
before closing that draft. Other idle tabs can still be closed.

Write Python in the editor, or start with **Examples**. The **⋯** menu beside
**Run** contains **New**, **Open**, **Save**, and **Help**. Open and Save use
ordinary `.py` files. **Stop** appears during a run; **Keep** and **Discard**
appear when a preview is ready. The editor provides these names:

| Name | Meaning |
|---|---|
| `doc` | a working copy of the current document, using the Document API below |
| `geo` | Serpentine's geometry functions; also available as `doc.geo` |
| `selected` | the selected scene objects when you start the run |

For example, this script creates a box on a named layer:

```python
width, depth, height = 40, 30, 20
doc.add(geo.make_box((0, 0, 0), width, depth, height),
        name="Block", layer="Generated")
print("Volume:", doc.volume("Block"))
```

**Run** prepares a preview without committing its geometry to the drawing.
Inspect it in a model viewport: green shows additions and changes, and red
shows removals. Choose **Keep** to apply it as one undoable change
or **Discard** to leave the drawing as it was. Editing and rerunning the same
script replaces its previously generated outputs. Original input geometry
and unrelated objects remain in the document unless your script explicitly
changes them.

Python errors are shown with their source location. A failed or stopped run
does not commit partial geometry. **Stop** interrupts Python execution;
a running native geometry operation may need to finish before cancellation
can take effect. If the live document changes after Run, make a fresh preview
before keeping it. Finish or cancel an active modelling command before Keep.

These are trusted Python scripts with normal Python file and library access.
Preview/Discard controls document changes; it is not a security sandbox and
cannot reverse a file your script writes or another external side effect.
The staged editor does not provide the live GUI's `window` or `api` objects.

### Ribs along a guide curve

Select one curve in the viewport before running this example. Change `count`,
`width` and `height` to explore the result. The frames follow the curve's
tangent without flipping unexpectedly at an inflection.

```python
import numpy as np

if len(selected) != 1 or selected[0].kind != "curve":
    raise ValueError("Select one guide curve before Run.")

count, width, height = 12, 30, 45
frames = geo.sample_curve_frames(selected[0].shape, count)
for i, (origin, tangent, up) in enumerate(frames):
    tangent, up = np.asarray(tangent), np.asarray(up)
    side = np.cross(up, tangent)
    placement = np.eye(4)
    placement[:3, :3] = np.column_stack((tangent, side, up))
    placement[:3, 3] = origin
    rib = geo.make_box((-1, -width / 2, 0), 2, width, height)
    doc.add(geo.apply_matrix(rib, placement),
            name=f"Rib {i + 1:02d}", layer="Ribs")
print(f"Prepared {count} ribs.")
```

The assistant can also prepare a script draft for you. Review the code in
the Script pane and choose Run yourself; handing code to the editor does
not execute it.

## The Document API

`serpentine3d.scripting.Document` is the stable, headless-friendly API — the
same one whether you run it standalone or inside the app.

In the Script pane, `doc` is already supplied. Create a `Document` yourself
when running standalone, as in this example:

```python
from serpentine3d.scripting import Document

doc = Document()
box = doc.add(doc.geo.make_box((0, 0, 0), 40, 40, 20), name="Block")
doc.run("filletedge", ["Block", "", "5"])     # command + its prompt answers
print("volume:", doc.volume("Block"))
doc.save("block.serp")
doc.export("block.stl")
```

`doc.geo` is the full geometry module (`make_box`, `make_sphere`,
`boolean_union`, …). `doc.run(command, inputs)` drives **any** interactive
command by feeding its prompts as strings — an empty string finishes a
selection or accepts a default.

| Method | Does |
|---|---|
| `doc.add(shape, name=, layer=)` | add geometry to the scene |
| `doc.run(cmd, [inputs])` | run any command, answering its prompts |
| `doc.objects()` / `doc.get(name)` | list / fetch scene objects |
| `doc.volume/area/length/bbox(name)` | measure |
| `doc.save(path)` / `doc.export(path)` | write `.serp` / any format |
| `doc.import_(path)` | import a file |

## Headless batch runner

`serp3d-batch` runs a script with `doc`, `geo` and `args` predefined — no
display needed, ideal for CI, conversions and overnight jobs.

```bash
serp3d-batch make_part.py output.step          # fresh document
serp3d-batch tweak.py --open existing.serp      # open a file first
```

```python
# make_part.py
box = doc.add(geo.make_box((0, 0, 0), 100, 100, 100), name="Crate")
doc.run("filletedge", ["Crate", "", "5"])
doc.export(args[0] if args else "crate.step")
```

## Plugins

Plugins register **first-class commands** — with prompts, object snaps, undo
and MCP support for free — and menu items. Two ways to ship one:

**1. Drop a file** into `~/.serpentine3d/plugins/` (or `SERP3D_PLUGIN_DIR`):

```python
# ~/.serpentine3d/plugins/greeble.py
def serpentine3d_plugin(ctx):
    base = ctx.requests()

    @ctx.command("greeble")
    def cmd_greeble(c):
        objs = yield base.SelectReq("Pick solids to greeble")
        c.echo(f"{len(objs)} object(s) would be greebled here.")
```

**2. Ship a package** exposing an entry point:

```toml
[project.entry-points."serpentine3d.plugins"]
myplugin = "myplugin:register"
```

The callable receives a `PluginContext`:

- `ctx.command` — the same decorator built-in commands use (generator
  commands yield `PointReq` / `SelectReq` / … and work from the command line,
  the viewport, scripts *and* MCP automatically)
- `ctx.requests()` — the request types module
- `ctx.window` / `ctx.scene` — GUI handles (`None` when headless)
- `ctx.add_menu_action(label, fn)` — a *Plugins* menu entry

The `plugins` command lists what's loaded; a broken plugin is skipped with a
traceback instead of taking the app down.
