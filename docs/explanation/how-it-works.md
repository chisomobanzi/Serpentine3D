# How it works

A short tour of the ideas behind Serpentine3D — useful for understanding why
it behaves the way it does, and for extending it.

## Exact geometry, not meshes

Serpentine3D models **BREP/NURBS** geometry on the
[OpenCASCADE](https://www.opencascade.com/) kernel (version 7.9, via the `OCP`
Python bindings) — the same kind of exact boundary representation Rhino and
STEP use. A circle is a real circle at any zoom; a fillet is a true surface,
not a faceted approximation.

The viewport **tessellates on demand** — it turns the exact geometry into
triangles and polylines only to draw them, at a resolution tied to the object
size. This is also why mesh exports (STL, OBJ, glTF) have a quality/deflection
setting: you're choosing how finely to sample exact surfaces. Heavy imported
meshes stay native mesh objects so they display instantly.

<figure markdown>
  <video autoplay loop muted playsinline
         style="width:100%;max-width:900px;height:auto;border-radius:6px">
    <source src="../../assets/clips/pushpull.webm" type="video/webm">
    <source src="../../assets/clips/pushpull.mp4" type="video/mp4">
  </video>
  <figcaption>Push/pull a face and the exact solid is rebuilt — then
  re-tessellated for display.</figcaption>
</figure>

## Commands are generators

Every command is a Python **generator** that *yields typed requests* for the
input it needs:

```python
@command("circle")
def cmd_circle(ctx):
    center = yield PointReq("Center")
    radius = yield NumberReq("Radius", minimum=0)
    ctx.scene.add(geo.make_circle(center, radius))
```

The same code serves **four front-ends at once**: typed input on the command
line, clicks in the viewport, a script calling `doc.run(...)`, and an AI
calling the MCP tools. Write a command (or a [plugin](../howto/scripting.md))
once and it works everywhere, with undo, object snaps and previews for free.

## Headless by design

Because commands never touch Qt directly, the whole modelling engine runs
without a GUI. The [`Document` API](../howto/scripting.md), the `serp3d-batch`
runner and the MCP server all drive the exact same command layer — the GUI is
just one more front-end on top.

## AI integration

The running app opens a localhost JSON-RPC bridge; the
[MCP server](../howto/ai-mcp.md) speaks to it so an assistant can create
geometry, run any command, and *screenshot the viewport* to check its own
work. The in-app assistant uses the same surface.

## Robustness

A few kernel operations (notably hidden-line removal for drawing sheets) can
crash on degenerate input, so Serpentine3D runs them in an **isolated worker
subprocess** that auto-restarts — a bad projection can never take the app
down. Autosave runs every few minutes and is offered for recovery after a
crash.

## The stack

| Layer | Choice |
|---|---|
| Kernel | OpenCASCADE 7.9 via `cadquery-ocp` pip wheels (no conda) |
| UI | PySide6 + a raw OpenGL 3.3 viewport |
| Commands | `serpentine3d/commands/` — generator protocol, shared by GUI + MCP |
| Headless | `scripting.py` (`Document`), `batch.py` (`serp3d-batch`) |
| AI | `mcp_server/` → localhost JSON-RPC bridge (`rpc.py`) |

The layering rule: OpenCASCADE imports stay in `core/`, and commands never
import Qt — that separation is what makes the headless and AI paths possible.
