"""Being the default application for .serp files.

Each platform allows a different amount of help:

- Linux lets a user-level process do the whole job: register a MIME type
  and desktop entry, then `xdg-mime default`. No elevation, no dialog.
- Windows deliberately does not let applications set defaults (the
  UserChoice registry key is hash-protected), so the honest move is to
  open the Default Apps settings page where one click finishes it. The
  installer has already registered `Serpentine3D.Document`.
- macOS keeps the choice in Finder (Get Info -> Change All), so all that
  can be offered is the instruction.

The launch-time dialog lives in app.py; everything below is headless.
"""

from __future__ import annotations

import os
import subprocess
import sys

MIME = "application/x-serpentine3d"
DESKTOP_ID = "serpentine3d.desktop"
_WIN_PROGID = "Serpentine3D.Document"


def exec_line() -> str:
    """How a file manager should start this very install."""
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return f"{appimage} %F"
    if getattr(sys, "frozen", False):
        return f"{sys.executable} %F"
    return f"{sys.executable} -m serpentine3d %F"


def desktop_entry(exec_cmd: str) -> str:
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Serpentine3D\n"
        "GenericName=NURBS Modeller\n"
        "Comment=NURBS surface modeller\n"
        f"Exec={exec_cmd}\n"
        "Icon=serpentine3d\n"
        "Terminal=false\n"
        "Categories=Graphics;3DGraphics;Engineering;\n"
        f"MimeType={MIME};\n"
        "Keywords=CAD;NURBS;3D;modelling;\n"
        "StartupWMClass=serpentine3d\n"
    )


def mime_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<mime-info xmlns="http://www.freedesktop.org/standards/'
        'shared-mime-info">\n'
        f'  <mime-type type="{MIME}">\n'
        "    <comment>Serpentine3D 3D model</comment>\n"
        '    <glob pattern="*.serp"/>\n'
        '    <icon name="serpentine3d"/>\n'
        "  </mime-type>\n"
        "</mime-info>\n"
    )


def _data_home() -> str:
    return os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share")


def status() -> str:
    """'default' | 'not_default' | 'unknown' — never raises."""
    if sys.platform.startswith("linux"):
        try:
            out = subprocess.run(
                ["xdg-mime", "query", "default", MIME],
                capture_output=True, text=True, timeout=5, check=False)
            return ("default" if out.stdout.strip() == DESKTOP_ID
                    else "not_default")
        except Exception:                                  # noqa: BLE001
            return "unknown"
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer"
                r"\FileExts\.serp\UserChoice")
            progid, _ = winreg.QueryValueEx(key, "ProgId")
            return "default" if progid == _WIN_PROGID else "not_default"
        except Exception:                                  # noqa: BLE001
            return "unknown"
    return "unknown"


def should_offer(config) -> bool:
    """Ask on launch? Once, and never when the answer is already yes."""
    if config.get("file_assoc", "asked", default=False):
        return False
    return status() != "default"


def make_default() -> tuple[bool, str]:
    """Do as much as the platform permits. (something_happened, message)."""
    if sys.platform.startswith("linux"):
        return _make_default_linux()
    if sys.platform == "win32":
        try:
            os.startfile("ms-settings:defaultapps")
            return True, ("Settings opened — pick Serpentine3D under "
                          ".serp to finish.")
        except Exception:                                  # noqa: BLE001
            return False, ("Open Settings > Apps > Default apps and pick "
                           "Serpentine3D for .serp files.")
    if sys.platform == "darwin":
        return False, ("In Finder: Get Info on a .serp file, choose "
                       "Serpentine3D under 'Open with', then Change All.")
    return False, "No file association support on this platform."


def _make_default_linux() -> tuple[bool, str]:
    share = _data_home()
    desktop_dir = os.path.join(share, "applications")
    mime_dir = os.path.join(share, "mime")
    os.makedirs(desktop_dir, exist_ok=True)
    os.makedirs(os.path.join(mime_dir, "packages"), exist_ok=True)

    desktop_path = os.path.join(desktop_dir, DESKTOP_ID)
    if not os.path.exists(desktop_path):
        # install-desktop.sh may have written a richer entry; only a
        # missing one (bare AppImage download) gets this minimal stand-in
        with open(desktop_path, "w") as f:
            f.write(desktop_entry(exec_line()))
    mime_path = os.path.join(mime_dir, "packages", "serpentine3d.xml")
    if not os.path.exists(mime_path):
        with open(mime_path, "w") as f:
            f.write(mime_xml())

    def _run(cmd) -> bool:
        try:
            subprocess.run(cmd, capture_output=True, timeout=15,
                           check=False)
            return True
        except Exception:                                  # noqa: BLE001
            return False

    _run(["update-desktop-database", desktop_dir])
    _run(["update-mime-database", mime_dir])
    if not _run(["xdg-mime", "default", DESKTOP_ID, MIME]):
        return False, ("Could not run xdg-mime — set the default from "
                       "your file manager's 'Open With' menu instead.")
    return True, "Serpentine3D is now the default app for .serp files."
