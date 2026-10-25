"""The Windows build leaves out the OpenGL DLLs that nothing loads (#77).

PyOpenGL ships freeglut and GLE built against three Visual C++ runtimes and
loads one of them. The other two went into the installer unused, and every
build warned that their runtimes could not be found. packaging/windows/hooks
holds a hook that replaces pyinstaller-hooks-contrib's hook-OpenGL.py to keep
them out. PyInstaller is not installed here, so the hook runs against a
stand-in for the two PyInstaller helpers it calls, fed with the files the
installed PyOpenGL really carries.
"""

import ast
import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOKS = ROOT / "packaging" / "windows" / "hooks"
SPEC = ROOT / "packaging" / "windows" / "serp3d.spec"

OpenGL = pytest.importorskip("OpenGL")
OPENGL_DIR = Path(OpenGL.__file__).parent
DLLS = OPENGL_DIR / "DLLS"


def _loaded_build() -> str:
    """The vc tag OpenGL/platform/win32.py picks for this Python.

    The module loads Windows' opengl32 on import, so its top-level choice is
    run on its own instead."""
    tree = ast.parse((OPENGL_DIR / "platform" / "win32.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.If) and any(
                isinstance(t, ast.Name) and t.id == "vc"
                for stmt in node.body if isinstance(stmt, ast.Assign)
                for t in stmt.targets):
            scope = {"sys": sys}
            exec(compile(ast.Module([node], []), "win32.py", "exec"), scope)
            return scope["vc"]
    pytest.fail("PyOpenGL no longer chooses its DLL build the way it did")


def _run_hook(monkeypatch):
    if not DLLS.is_dir():
        pytest.skip("this PyOpenGL carries no Windows DLLs")
    collected = [(str(path), "OpenGL/DLLS") for path in sorted(DLLS.iterdir())]
    helpers = types.ModuleType("PyInstaller.utils.hooks")
    helpers.collect_data_files = lambda package: (
        collected if package == "OpenGL" else [])
    helpers.collect_submodules = lambda package: (
        ["OpenGL.arrays.numpymodule"] if package == "OpenGL.arrays" else [])
    compat = types.ModuleType("PyInstaller.compat")
    compat.is_win, compat.is_darwin = True, False
    for name, module in (("PyInstaller", types.ModuleType("PyInstaller")),
                         ("PyInstaller.utils", types.ModuleType("PyInstaller.utils")),
                         ("PyInstaller.utils.hooks", helpers),
                         ("PyInstaller.compat", compat)):
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location(
        "hook_opengl", HOOKS / "hook-OpenGL.py")
    hook = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(hook)
    return hook


def _names(datas):
    return {Path(src).name for src, _dest in datas}


def test_no_dll_build_goes_in_that_this_python_never_loads(monkeypatch):
    hook = _run_hook(monkeypatch)
    loaded = _loaded_build()
    shipped = {name for name in _names(hook.datas) if name.endswith(".dll")}
    assert shipped, "the hook collects no DLLs at all"
    assert all(name.endswith(f".{loaded}.dll") for name in shipped), sorted(
        name for name in shipped if not name.endswith(f".{loaded}.dll"))


def test_the_build_pyopengl_loads_still_goes_in(monkeypatch):
    hook = _run_hook(monkeypatch)
    loaded = _loaded_build()
    wanted = {p.name for p in DLLS.glob(f"*.{loaded}.dll")}
    assert wanted, f"PyOpenGL ships no {loaded} DLLs to load"
    assert wanted <= _names(hook.datas)


def test_everything_else_the_contrib_hook_does_still_happens(monkeypatch):
    hook = _run_hook(monkeypatch)
    licences = {p.name for p in DLLS.iterdir() if not p.name.endswith(".dll")}
    assert licences <= _names(hook.datas), "the DLLs' licence files went missing"
    assert "OpenGL.platform.win32" in hook.hiddenimports
    assert "OpenGL.arrays.numpymodule" in hook.hiddenimports


def test_the_windows_spec_uses_the_hooks_folder():
    assert 'hookspath=[str(Path(SPECPATH) / "hooks")]' in SPEC.read_text()


def test_no_local_hook_keeps_time_zone_data_out():
    # Python on Windows has no time zone database of its own. tzdata arrives
    # with python-dateutil, and contrib's zoneinfo hook bundles it.
    assert not (HOOKS / "hook-zoneinfo.py").exists()
