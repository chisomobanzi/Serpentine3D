# Scripting & plugins

## The console

*Tools → Python Console* (`` Ctrl+` ``) gives a live interpreter with
`sp` — the stable scripting API — plus `scene`, `selection`, `run()`.

```python
ids = [sp.add_box((i * 12, 0, 0), 10, 10, 10) for i in range(5)]
sp.set_color(ids[0], (1, 0, 0))
run("zoomextents")
```

## Headless batch

```bash
serp-batch myscript.py --output out.step
```

Runs the same `sp` API without a display — good for CI, conversions and
overnight jobs.

## Plugins

Two ways to extend Serpentine:

**1. Drop a file** into `~/.serpentine/plugins/` (or `SERP_PLUGIN_DIR`):

```python
# ~/.serpentine/plugins/greeble.py
def serpentine_plugin(ctx):
    base = ctx.requests()

    @ctx.command("greeble")
    def cmd_greeble(c):
        objs = yield base.SelectReq("Pick solids to greeble")
        c.echo(f"{len(objs)} object(s) would be greebled here.")
```

**2. Ship a package** exposing an entry point:

```toml
[project.entry-points."serpentine.plugins"]
myplugin = "myplugin:register"
```

Either way the callable receives a `PluginContext` with:

- `ctx.command` — the same decorator built-in commands use (generator
  commands yield `PointReq`/`SelectReq`/... and work from the command
  line, the viewport, scripts *and* MCP automatically)
- `ctx.requests()` — the request types module
- `ctx.window` / `ctx.scene` — GUI handles (None when headless)
- `ctx.add_menu_action(label, fn)` — a *Plugins* menu entry

`plugins` lists what's loaded; broken plugins are skipped with a
traceback rather than taking the app down.
