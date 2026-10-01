"""Keep native crash traces when a packaged GUI has no terminal."""

from __future__ import annotations

import faulthandler
import os
from pathlib import Path
import sys
import time
import traceback

_stream = None  # faulthandler holds the fd, so keep it open for the process


def enable() -> Path | None:
    global _stream
    if _stream is not None:
        return Path(_stream.name)
    stream = None
    try:
        settings = os.environ.get("SERP3D_CONFIG")
        directory = (Path(settings).expanduser().resolve().parent if settings
                     else Path.home() / ".serpentine3d")
        path = directory / "crash.log"
        directory.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 1024 * 1024:
            path.replace(path.with_suffix(".log.1"))
        stream = path.open("a", encoding="utf-8", buffering=1)
        from .. import version_line
        stream.write(f"\n{time.strftime('%Y-%m-%d %H:%M:%S')} "
                     f"{version_line()} pid={os.getpid()} {sys.platform}\n")
        stream.flush()
        faulthandler.enable(file=stream, all_threads=True)
    except (OSError, RuntimeError, ValueError):
        if stream is not None:
            stream.close()
        return None  # diagnostics must never prevent the app from starting
    _stream = stream
    return path


def record_exception():
    """Save a caught paint failure as well as printing it to stderr."""
    if _stream is not None:
        try:
            traceback.print_exc(file=_stream)
            _stream.flush()
        except OSError:
            pass
