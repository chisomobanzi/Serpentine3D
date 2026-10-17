"""Application entry point.

The whole point of this module is import order. Importing
``serpentine3d.app`` pulls in the OpenCASCADE geometry kernel (~150 MB),
which takes a couple of seconds on a cold start — long enough that the app
appears to hang after launch. So the launcher does the cheap work first
(GL format, QApplication, splash) and only *then* imports the app, so the
splash is on screen during that slow kernel load.

Keep this module free of heavy imports at the top level.
"""

from __future__ import annotations

import os
import signal
import sys

from . import version_line


def _apply_ui_scale() -> None:
    """Honour the saved interface scale (Settings → Display).

    Qt reads QT_SCALE_FACTOR only as the QApplication is built, so the
    value has to be in the environment before one exists — the same
    one-shot rule as the GL surface format below. Left unset at the
    default scale, so normal high-DPI detection stays untouched.
    """
    from .utils.config import Config
    try:
        scale = float(Config().get("display", "ui_scale", default=1.0))
    except (TypeError, ValueError):
        return                      # hand-edited settings are not a crash
    if 1.0 < scale <= 1.5:          # the slider's range
        os.environ["QT_SCALE_FACTOR"] = f"{scale:g}"
    else:
        # also clears a factor inherited from the process we were
        # restarted by, so scaling back to 100% sticks
        os.environ.pop("QT_SCALE_FACTOR", None)


def running_scale() -> float:
    """The interface scale this process runs at: whatever was in
    QT_SCALE_FACTOR when Qt read it. Not the saved setting, which may be
    waiting on a restart."""
    try:
        scale = float(os.environ.get("QT_SCALE_FACTOR", 1.0))
    except ValueError:
        return 1.0
    return scale if scale > 0 else 1.0


def main() -> int:
    # First, and before anything can print or open a window: the .3dm importer
    # spawns a helper process, and in a PyInstaller bundle a spawned child
    # re-enters this executable. Without this it would relaunch the whole app
    # instead of running the helper — one new window per worker.
    import multiprocessing
    multiprocessing.freeze_support()

    # The hidden-line worker gets in the same way, and for the same reason:
    # a bundle has no python to call, so it re-runs the app with this flag.
    # It is a helper, not the app — so no splash, no window, no Qt at all.
    from .utils.spawn import HLR_WORKER_FLAG
    if HLR_WORKER_FLAG in sys.argv:
        from .core.hlr import _worker_main
        _worker_main()
        return 0

    # Answered before Qt or the kernel is touched. An installed build is one
    # opaque file, and the moment you want to ask it what it is, is the
    # moment it is misbehaving — possibly too badly to survive importing
    # 150 MB of OpenCASCADE to tell you.
    if "--version" in sys.argv or "-V" in sys.argv:
        print(version_line())
        return 0

    if "--mcp" in sys.argv:
        # External assistants launch the installed app as a stdio server.
        # Keep stdout and startup free of the GUI, splash and geometry kernel.
        from .mcp_server.server import main as mcp_main
        mcp_main()
        return 0

    # Arm this before Qt and OpenCASCADE are imported: native faults bypass
    # Python's exception handlers, and a Windows GUI build has no terminal.
    from .utils.crash_log import enable as enable_crash_log
    enable_crash_log()

    if "--selftest" in sys.argv:
        # headless bundle check — no window, no splash
        from .app import _selftest
        return _selftest()

    if len(sys.argv) > 1 and sys.argv[1] == "replay":
        # re-execute a session journal: --check is headless, --video needs
        # a display for GL and imports the whole app
        from .replay_cli import main as replay_main
        return replay_main(sys.argv[2:])

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # The saved interface scale must be in the environment before the
    # QApplication below exists — see _apply_ui_scale.
    _apply_ui_scale()

    # Both the surface format and the share-group attribute are only read
    # as the QApplication is built, so they have to be set before one
    # exists: set the share group late and a second viewport draws
    # nothing, silently. Its own module rather than the viewport's, which
    # would drag the kernel in ahead of the splash.
    from .utils.glsetup import match_pyopengl_to_qt, set_default_gl_format
    set_default_gl_format()

    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)

    # Now that there is a context to ask about, and while PyOpenGL is
    # still unimported: point it at whichever driver binding Qt got. It
    # guesses GLX, and on Wayland the guess is wrong in a way that only
    # shows up as the viewport's first GL call raising.
    match_pyopengl_to_qt()

    splash = None
    from .ui.splash import SplashScreen, should_show
    if should_show():
        from . import __version__
        splash = SplashScreen(__version__)
        splash.show()
        splash.message("Loading geometry kernel…", 0.15)
        app.processEvents()          # paint the splash before we block

    # Heavy imports (kernel, viewport, ...) happen here, with the splash up.
    from .app import run_app
    return run_app(app, splash)


if __name__ == "__main__":
    raise SystemExit(main())
