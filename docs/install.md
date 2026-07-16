# Install

Serpentine3D needs Python 3.10+ on Linux with OpenGL 3.3.

## From source

```bash
git clone https://github.com/chisomobanzi/Serpentine3D
cd Serpentine3D
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/serp3d
```

The heavy dependency is `cadquery-ocp` (the OpenCASCADE kernel);
everything installs from PyPI wheels — no conda, no compiler.

## Entry points

| Command | What it starts |
|---|---|
| `serp3d` | the GUI |
| `serp3d file.serp` | the GUI with a file |
| `serp3d-batch script.py` | headless scripting (no display needed) |
| `serp3d-mcp` | the MCP server for AI clients |

## AppImage

A self-contained AppImage recipe lives in `packaging/appimage`:

```bash
./packaging/appimage/build-appimage.sh
```

## SpaceMouse

3Dconnexion devices work out of the box when
[spacenavd](https://spacenav.sourceforge.net/) is running
(`sudo apt install spacenavd`) — Serpentine3D speaks the daemon's
socket directly, on X11 and Wayland alike. Slide to pan, push/pull to
zoom, tilt/twist to orbit; buttons default to Fit and Perspective.
Sensitivity and inversion live in *Settings → Mouse*; the `spacemouse`
command shows status and a live axis readout (`Diag`).

## Configuration

Settings live in `~/.config/serpentine3d/config.json` (edit through
*Tools → Settings*). A `template.serp` in the same directory becomes
the startup template. Autosaves land in `~/.serpentine3d/autosave` and
are offered for recovery after a crash.
