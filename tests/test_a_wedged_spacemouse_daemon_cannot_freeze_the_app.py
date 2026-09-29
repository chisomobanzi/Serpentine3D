"""A SpaceMouse daemon that stops answering cannot freeze the program.

Found cutting 0.10.4: the whole test suite hung at its first window, and
so did the release candidate. spacenavd was running but wedged, with nine
connections queued against a backlog of eight and none being accepted.
Connecting to a Unix socket in that state blocks, and the navigator
connected with no timeout, on startup and again on a five second retry.
So anyone whose daemon got into that state saw Serpentine3D freeze at
launch with no error, and no SpaceMouse involved.

The connection now gives up after a moment and the program carries on
without the SpaceMouse, trying again later as it always did.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(not hasattr(socket, "AF_UNIX"),
                                reason="spacenavd is a Unix socket")


@pytest.fixture
def wedged(tmp_path):
    """A listening socket that never accepts, with its queue already full,
    which is exactly the state the real daemon was found in."""
    path = str(tmp_path / "spnav.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(0)
    queued = []
    while True:                      # fill the backlog until it refuses
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.setblocking(False)
        try:
            c.connect(path)
        except (BlockingIOError, OSError):
            c.close()
            break
        queued.append(c)
        if len(queued) > 64:
            break
    # the premise: a plain blocking connect now blocks
    probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    probe.settimeout(0.3)
    with pytest.raises(OSError):      # socket.timeout is an OSError
        probe.connect(path)
    probe.close()
    yield path
    for c in queued:
        c.close()
    server.close()


def _within(seconds, fn):
    """Run `fn` in a thread; what it returned, or fail if it is still
    running when the time is up. A daemon thread, so a hang fails the
    test rather than hanging the suite."""
    out = {}
    t = threading.Thread(target=lambda: out.setdefault("v", fn()),
                         daemon=True)
    t.start()
    t.join(seconds)
    assert not t.is_alive(), f"still connecting after {seconds}s"
    return out.get("v")


def test_dialling_a_wedged_daemon_gives_up(wedged):
    from serpentine3d.ui.spacemouse import _dial_spacenavd

    start = time.monotonic()
    got = _within(5, lambda: _dial_spacenavd(wedged))

    assert got is None, "a daemon that never answers is no daemon"
    assert time.monotonic() - start < 3


def test_dialling_a_daemon_that_answers_connects(tmp_path):
    from serpentine3d.ui.spacemouse import _dial_spacenavd
    path = str(tmp_path / "spnav.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(4)
    try:
        got = _within(5, lambda: _dial_spacenavd(path))
        assert got is not None
        assert got.getblocking() is False, "the notifier reads it without blocking"
        got.close()
    finally:
        server.close()


def test_no_daemon_at_all_is_still_quiet(tmp_path):
    from serpentine3d.ui.spacemouse import _dial_spacenavd

    assert _dial_spacenavd(str(tmp_path / "absent.sock")) is None


def test_the_program_starts_with_the_daemon_wedged(wedged, tmp_path):
    """The whole window, in its own process, so that if it hangs the
    test fails on a timeout instead of taking the suite down with it."""
    env = dict(os.environ,
               SPNAV_SOCKET=wedged,
               QT_QPA_PLATFORM="offscreen",
               SERP3D_CONFIG=str(tmp_path / "cfg.json"),
               SERP3D_AUTOSAVE_DIR=str(tmp_path / "as"),
               SERP3D_NO_RECOVER="1", SERP3D_NO_WELCOME="1")
    code = (
        "import sys\n"
        "from PySide6.QtWidgets import QApplication\n"
        "app = QApplication(sys.argv)\n"
        "from serpentine3d.app import MainWindow\n"
        "w = MainWindow()\n"
        "print('started', w.spacemouse.source)\n"
        "w._saved_revision = w.scene.revision\n"
        "w.close()\n")
    run = subprocess.run([sys.executable, "-c", code], env=env,
                         capture_output=True, text=True, timeout=90)

    assert "started" in run.stdout, run.stderr[-2000:]
