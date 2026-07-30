"""Starting a helper process without starting the app again.

`sys.executable` is not always python. python-appimage points it at the
AppImage and PyInstaller points it at the frozen app, both deliberately: it
means re-running it reproduces the whole environment, which is exactly what
multiprocessing wants — it hands the child a sentinel argv the app recognises
and `freeze_support()` answers.

`python -m some.module` has no such handshake. Hand that to the app and it
sees arguments it does not understand, shrugs, and opens a window. Every
helper became another copy of the application; none of them ran the helper.
So a caller that wants a module run in its own process has to name a real
interpreter, or ask the app to re-run itself with a flag it answers.
"""

from __future__ import annotations

import os
import sys

# What the app is called with when it is a helper rather than the app. The
# launcher answers this before it touches Qt or the geometry kernel.
HLR_WORKER_FLAG = "--hlr-worker"

HLR_MODULE = "serpentine3d.core.hlr"


def spawn_executable() -> str | None:
    """The interpreter a spawned helper should run, or None if there isn't one.

    Inside an AppImage `sys.executable` is the AppImage, not python:
    python-appimage sets it that way so re-running it reproduces the whole
    environment. multiprocessing takes it at face value and starts the child
    as `TheApp.AppImage -c "...spawn_main()..."`, which the AppImage's launcher
    hands to the app as arguments — so every worker opened another window,
    none of them ran the helper, and the import waited on a pipe forever.

    Naming the real interpreter fixes it. If it cannot be found we say so
    rather than guess, and the caller stays on the single-process path.

    Everywhere else the answer is the interpreter already running — not
    sys._base_executable, which in a virtualenv is the system python: it has
    none of our dependencies and never runs the venv's editable-install hook,
    so helpers died on import and every parallel import quietly became a
    serial one.
    """
    exe = sys.executable
    bundle = os.environ.get("APPIMAGE")
    if not bundle or os.path.realpath(exe) != os.path.realpath(bundle):
        return exe

    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    for prefix in (sys.prefix, sys.base_prefix):
        candidate = os.path.join(prefix, "bin", version)
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def hlr_worker_command() -> list[str] | None:
    """The argv that starts the hidden-line worker, or None if nothing can.

    A frozen bundle contains no python to call, so the app re-runs itself
    with `HLR_WORKER_FLAG` instead. Anywhere else the interpreter runs the
    worker module directly, which is cheaper: no second AppImage to mount, no
    Qt to import.
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, HLR_WORKER_FLAG]
    exe = spawn_executable()
    return None if exe is None else [exe, "-m", HLR_MODULE]
