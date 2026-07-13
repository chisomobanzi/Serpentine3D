# AI / MCP integration

Serpentine3D ships an [MCP](https://modelcontextprotocol.io) server so AI
assistants can drive the modeller: create geometry, run any command,
inspect and screenshot the scene.

## Wiring it up

With the GUI running (it opens a local RPC bridge automatically), add
to your MCP client config — e.g. Claude Code:

```bash
claude mcp add serpentine3d -- /path/to/.venv/bin/serp3d-mcp
```

or in `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "serpentine3d": { "command": "/path/to/.venv/bin/serp3d-mcp" }
  }
}
```

The MCP server finds the running GUI through `~/.serpentine3d/rpc.port`.

## What the assistant can do

- `create_curve`, `create_solid`, `create_surface`, `transform`,
  `boolean` — direct geometry with exact parameters
- `run_command` — anything a user could type, with scripted answers to
  the prompts
- `scene_graph`, `measure`, `screenshot` — see what it's doing
- layers, selection, file open/save/export

Every mutation is undoable in the GUI, so a human can step back through
anything the assistant did.
