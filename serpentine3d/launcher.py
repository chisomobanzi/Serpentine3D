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

import signal
import sys

from . import version_line


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

    if "--selftest" in sys.argv:
        # headless bundle check — no window, no splash
        from .app import _selftest
        return _selftest()

    signal.signal(signal.SIGINT, signal.SIG_DFL)

    # The default surface format must be set before the QApplication; do it
    # here (cheap, QtGui only) rather than import it from the viewport, which
    # would drag the kernel in early.
    from PySide6.QtGui import QSurfaceFormat
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setSamples(4)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)

    # Every viewport's context in one share group, so a mesh is uploaded once
    # however many views show it. Only read when the QApplication is built, so
    # it has to be set here — set it late and a second viewport draws nothing,
    # silently.
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv)

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
