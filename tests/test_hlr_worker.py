"""The HLR worker has to be a worker, not another copy of the app.

From a bug report: "it crashed when i tried to make a detail view on a layout
/ actually it had opened another copy of the software for some reason. does
that everytime i click the viewport". Both halves are the same line —
`Popen([sys.executable, "-m", "serpentine3d.core.hlr"])`. In an installed
build sys.executable is the app rather than python, `-m ...` is argv the app
ignores, so every hidden-line pass opened a window, none of them answered,
and the caller sat on readline() forever while the copies piled up.
"""

from __future__ import annotations

import io
import sys
import threading
import time

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core import hlr
from serpentine3d.utils import spawn

# ------------------------------------------------- which command to spawn

def _fake_frozen(monkeypatch, exe="/opt/Serpentine3D/serp3d"):
    """A PyInstaller bundle's idea of itself: no python anywhere in it."""
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", exe)
    return exe


def _fake_appimage(tmp_path, monkeypatch, with_interpreter=True):
    """An AppImage's idea of itself: sys.executable is the bundle, not python."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    appimage = tmp_path / "Serpentine3D.AppImage"
    appimage.write_text("")
    monkeypatch.setenv("APPIMAGE", str(appimage))
    monkeypatch.setattr(sys, "executable", str(appimage))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "mount"))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "mount"))
    if not with_interpreter:
        return None
    real = (tmp_path / "mount" / "bin"
            / f"python{sys.version_info.major}.{sys.version_info.minor}")
    real.parent.mkdir(parents=True)
    real.write_text("")
    real.chmod(0o755)
    return real


def test_an_installed_build_never_asks_the_app_to_run_dash_m(monkeypatch):
    """This is the bug. The app takes `-m serpentine3d.core.hlr` for junk
    arguments and shows a window; a flag it answers itself is the only way
    back into the worker."""
    exe = _fake_frozen(monkeypatch)
    cmd = spawn.hlr_worker_command()
    assert "-m" not in cmd
    assert cmd == [exe, spawn.HLR_WORKER_FLAG]


def test_an_appimage_runs_the_python_inside_it(tmp_path, monkeypatch):
    real = _fake_appimage(tmp_path, monkeypatch)
    assert spawn.hlr_worker_command() == [str(real), "-m",
                                          "serpentine3d.core.hlr"]


def test_the_ordinary_case_runs_the_interpreter_already_running(monkeypatch):
    monkeypatch.delenv("APPIMAGE", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert spawn.hlr_worker_command() == [sys.executable, "-m",
                                          "serpentine3d.core.hlr"]


def test_no_interpreter_at_all_is_said_rather_than_guessed(tmp_path,
                                                          monkeypatch):
    _fake_appimage(tmp_path, monkeypatch, with_interpreter=False)
    assert spawn.hlr_worker_command() is None


def test_the_app_answers_the_worker_flag_before_it_loads_qt(monkeypatch):
    """The flag is how an installed build reaches the worker at all, so it
    has to be answered before the launcher starts importing 150 MB of
    geometry kernel — and before it puts a window on screen."""
    from serpentine3d import launcher

    monkeypatch.setattr(sys, "argv", ["serp3d", spawn.HLR_WORKER_FLAG])
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    monkeypatch.setitem(sys.modules, "PySide6.QtGui", None)
    assert launcher.main() == 0


# ------------------------------------------------------ falling back safely

class _Forbidden:
    def __call__(self, *a, **kw):
        raise AssertionError(f"spawned a process: {a!r}")


def test_no_interpreter_means_hlr_runs_in_process(monkeypatch):
    """Worse than crash isolation, better than a window per click."""
    monkeypatch.setattr(spawn, "hlr_worker_command", lambda: None)
    monkeypatch.setattr(hlr._subprocess, "Popen", _Forbidden())
    box = g.make_box((0, 0, 0), 10, 10, 10)
    out = hlr._HlrWorker().project([box], (0, 0, 0), (0, -1, 0), (1, 0, 0))
    assert out["visible"], "no edges came back from the in-process pass"
    assert len(out["visible_by_shape"]) == 1


def test_the_in_process_pass_keeps_the_edges_of_each_shape_apart():
    """One HLR pass over everything, so occlusion is right, but the visible
    edges come back per input shape — that is what lets each object keep its
    own linetype."""
    a = g.make_box((0, 0, 0), 10, 10, 10)
    b = g.make_box((20, 0, 0), 10, 10, 10)
    out = hlr.project_by_shape([a, b], (0, 0, 0), (0, -1, 0), (1, 0, 0))
    assert len(out["visible_by_shape"]) == 2
    assert all(out["visible_by_shape"]), out["visible_by_shape"]
    assert len(out["visible"]) == sum(len(grp)
                                      for grp in out["visible_by_shape"])


def test_the_worker_talks_on_its_pipes_with_no_console_to_use(monkeypatch):
    """An installed build is windowed, so PyInstaller hands it sys.stdout of
    None — but the parent did open a pipe, and fd 1 is it."""
    monkeypatch.setattr(sys, "stdin", None)
    monkeypatch.setattr(sys, "stdout", None)
    stdin, stdout = hlr._worker_streams()
    assert stdin.fileno() == 0
    assert stdout.fileno() == 1


# --------------------------------------------------- a worker that went quiet

class _Deaf:
    """A worker that took the request and never answered — which is what a
    segfaulted OCCT looks like from the other end of the pipe."""

    def __init__(self):
        self.stdin = io.StringIO()
        self.killed = False
        self.stdout = self

    def readline(self):
        threading.Event().wait()        # forever

    def poll(self):
        return None

    def kill(self):
        self.killed = True


def test_a_worker_that_stops_answering_does_not_hang_the_app(monkeypatch):
    """`project` has always declared a timeout and never used one: the GUI
    froze on readline() with nothing left to wake it."""
    worker = hlr._HlrWorker()
    worker.proc = deaf = _Deaf()
    box = g.make_box((0, 0, 0), 10, 10, 10)

    start = time.monotonic()
    out = worker.project([box], (0, 0, 0), (0, -1, 0), (1, 0, 0),
                         timeout=0.3)
    elapsed = time.monotonic() - start

    assert elapsed < 10, f"waited {elapsed:.1f}s on a worker that never spoke"
    assert out["visible"] == []
    assert deaf.killed, "the silent worker was left running"
    assert worker.proc is None, "the next call would talk to a dead worker"


class _Mute:
    """A worker that answers, so the spawn arguments can be inspected."""

    def __init__(self, *a, **kw):
        self.args = a
        self.kwargs = kw
        self.stdin = io.StringIO()
        self.stdout = io.StringIO("ok 0\n")

    def poll(self):
        return None

    def kill(self):
        pass


def test_the_worker_is_not_handed_the_rpc_port(monkeypatch):
    """A helper is not the app and must not answer for it: if one ever does
    re-enter the app it would bind the RPC port and write the port file,
    pointing the MCP bridge at a process with no scene in it."""
    spawned = []

    def fake_popen(cmd, **kw):
        proc = _Mute(cmd, **kw)
        spawned.append(proc)
        return proc

    monkeypatch.setattr(hlr._subprocess, "Popen", fake_popen)
    monkeypatch.delenv("SERP3D_NO_RPC", raising=False)
    box = g.make_box((0, 0, 0), 10, 10, 10)
    hlr._HlrWorker().project([box], (0, 0, 0), (0, -1, 0), (1, 0, 0))

    assert spawned, "no worker was started"
    assert spawned[0].kwargs["env"]["SERP3D_NO_RPC"] == "1"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
