# Install

## Download

Each build bundles the OpenCASCADE kernel and Python runtime — nothing else
to install.

| Platform | Download |
|---|---|
| **Linux** | [`Serpentine3D-x86_64.AppImage`](https://github.com/chisomobanzi/Serpentine3D/releases/latest/download/Serpentine3D-x86_64.AppImage) — `chmod +x` and run |
| **Windows** | [`Serpentine3D-Setup-x86_64.exe`](https://github.com/chisomobanzi/Serpentine3D/releases/latest/download/Serpentine3D-Setup-x86_64.exe) — installer |
| **macOS** (Apple Silicon) | [`Serpentine3D-arm64.dmg`](https://github.com/chisomobanzi/Serpentine3D/releases/latest/download/Serpentine3D-0.4.0-arm64.dmg) — drag to Applications |

The GUI needs a GPU with OpenGL 3.3 drivers (any normal desktop). Headless
use (`serp3d-batch`, the MCP server, file conversion) works anywhere.

## From source

Requires Python 3.10+. Works on Linux, Windows and macOS.

```bash
git clone https://github.com/chisomobanzi/Serpentine3D
cd Serpentine3D
python3 -m venv .venv
.venv/bin/pip install -e .        # or: uv pip install -e .
.venv/bin/serp3d
```

The heavy dependency is `cadquery-ocp` (the OpenCASCADE kernel); everything
installs from PyPI wheels — no conda, no compiler. The full test suite passes
on all three platforms.

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
