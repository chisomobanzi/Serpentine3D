# Install

Serpentine needs Python 3.10+ on Linux with OpenGL 3.3.

## From source

```bash
git clone https://github.com/chisomo-banzi/Serpentine3D
cd Serpentine3D
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/serp
```

The heavy dependency is `cadquery-ocp` (the OpenCASCADE kernel);
everything installs from PyPI wheels — no conda, no compiler.

## Entry points

| Command | What it starts |
|---|---|
| `serp` | the GUI |
| `serp file.serp` | the GUI with a file |
| `serp-batch script.py` | headless scripting (no display needed) |
| `serp-mcp` | the MCP server for AI clients |

## AppImage

A self-contained AppImage recipe lives in `packaging/appimage`:

```bash
./packaging/appimage/build-appimage.sh
```

## Configuration

Settings live in `~/.config/serpentine/config.json` (edit through
*Tools → Settings*). A `template.serp` in the same directory becomes
the startup template. Autosaves land in `~/.serpentine/autosave` and
are offered for recovery after a crash.
