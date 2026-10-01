"""A native fault in a terminal-free GUI still leaves a useful traceback."""

import os
from pathlib import Path
import subprocess
import sys

import pytest


def _run(tmp_path, source):
    env = dict(os.environ, SERP3D_CONFIG=str(tmp_path / "settings.json"),
               PYTHONPATH=str(Path(__file__).resolve().parents[1]))
    return subprocess.run([sys.executable, "-c", source], cwd=tmp_path,
                          env=env, capture_output=True, text=True, timeout=30)


@pytest.mark.skipif(sys.platform == "win32", reason="Avoid the OS abort dialog in CI")
def test_a_native_abort_leaves_the_failing_thread_in_the_log(tmp_path):
    result = _run(tmp_path, """
import os, resource
from serpentine3d.utils.crash_log import enable
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
assert enable() is not None
def trigger_native_fault():
    os.abort()
trigger_native_fault()
""")
    assert result.returncode != 0
    text = (tmp_path / "crash.log").read_text()
    assert "Fatal Python error" in text
    assert "trigger_native_fault" in text
    assert "Serpentine3D" in text


def test_a_caught_paint_exception_can_be_saved_without_a_terminal(tmp_path):
    result = _run(tmp_path, """
from serpentine3d.utils.crash_log import enable, record_exception
enable()
try:
    raise RuntimeError("clip uniforms rejected")
except RuntimeError:
    record_exception()
""")
    assert result.returncode == 0, result.stderr
    assert "RuntimeError: clip uniforms rejected" in (tmp_path / "crash.log").read_text()


def test_an_unwritable_crash_log_does_not_prevent_startup(tmp_path):
    (tmp_path / "crash.log").mkdir()
    result = _run(tmp_path, """
from serpentine3d.utils.crash_log import enable
assert enable() is None
print("startup continues")
""")
    assert result.returncode == 0, result.stderr
    assert "startup continues" in result.stdout


def test_the_previous_large_log_is_kept_and_the_new_one_is_usable(tmp_path):
    previous = "previous diagnostics\n" + "x" * (1024 * 1024)
    (tmp_path / "crash.log").write_text(previous)
    result = _run(tmp_path, """
from serpentine3d.utils.crash_log import enable
assert enable() is not None
assert enable() is not None
""")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "crash.log.1").read_text() == previous
    assert (tmp_path / "crash.log").read_text().count("Serpentine3D") == 1
