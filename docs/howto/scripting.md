# Script & automate

The whole modelling engine runs with or without a GUI, so anything you can do
by hand can be scripted, batch-processed, or driven by an AI. The command
layer is fully decoupled from Qt.

## The Document API

`serpentine3d.scripting.Document` is the stable, headless-friendly API — the
same one whether you run it standalone or inside the app.

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

## The in-app console

*Tools → Python Console* (++ctrl+grave++) gives a live interpreter with the
running scene in scope: `scene`, `selection`, `geo`, `window`, and `api` (the
same programmatic API the MCP server uses).

```python
b = scene.add(geo.make_box((0, 0, 0), 10, 10, 10))
api.command("zoomextents")
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
