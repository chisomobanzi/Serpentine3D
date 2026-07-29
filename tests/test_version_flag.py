"""``--version`` on the entry points people actually run.

Without it there is no way to ask a build what it is. An AppImage or a .dmg
is one opaque file that someone may have downloaded weeks ago, and the only
place the version appeared was the splash screen — which means launching the
whole app, and which is exactly what you cannot do when the question is
"which build is this, and is that why it is behaving like that?".

It has to answer without loading Qt or the geometry kernel. That is not
tidiness: `--version` is what you reach for when a build is broken, and a
build broken enough to be worth asking about is one that may not survive
importing 150 MB of OpenCASCADE.
"""

import os
import re
import subprocess
import sys
import tomllib

from serpentine3d import __version__

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_launcher_reports_its_version(capsys, monkeypatch):
    from serpentine3d import launcher
    monkeypatch.setattr(sys, "argv", ["serp3d", "--version"])
    assert launcher.main() == 0
    assert capsys.readouterr().out.strip() == f"Serpentine3D {__version__}"


def test_the_short_form_works_too(capsys, monkeypatch):
    from serpentine3d import launcher
    monkeypatch.setattr(sys, "argv", ["serp3d", "-V"])
    assert launcher.main() == 0
    assert __version__ in capsys.readouterr().out


def test_batch_reports_its_version(capsys):
    from serpentine3d import batch
    assert batch.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"Serpentine3D {__version__}"


def test_the_mcp_server_reports_its_version(capsys, monkeypatch):
    """Not cheap here — the tools register at import — but an assistant's
    config is exactly where you want to check which build you wired up."""
    from serpentine3d.mcp_server import server
    monkeypatch.setattr(sys, "argv", ["serp3d-mcp", "--version"])
    assert server.main() == 0
    assert capsys.readouterr().out.strip() == f"Serpentine3D {__version__}"


def test_every_console_script_answers_the_same_way():
    """A flag that works on two of four entry points is worse than none:
    you cannot trust the answer you get from the one you happened to try."""
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as fh:
        scripts = tomllib.load(fh)["project"]["scripts"]
    modules = {re.sub(r":.*", "", t) for t in scripts.values()}
    for mod in sorted(modules):
        with open(os.path.join(ROOT, mod.replace(".", "/") + ".py")) as fh:
            src = fh.read()
        assert "--version" in src, (
            f"{mod} backs a console script but has no --version")


def test_asking_the_version_loads_neither_qt_nor_the_kernel():
    """A separate interpreter, because the test session has both loaded
    long before this file runs."""
    code = (
        "import sys, serpentine3d.launcher as L;"
        "sys.argv = ['serp3d', '--version'];"
        "rc = L.main();"
        "heavy = [m for m in ('PySide6.QtWidgets', 'OCP', 'serpentine3d.app')"
        " if m in sys.modules];"
        "print('rc', rc);"
        "print('heavy', heavy)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, timeout=120, check=False)
    assert out.returncode == 0, out.stderr
    assert "rc 0" in out.stdout
    assert "heavy []" in out.stdout, (
        f"--version dragged in heavy modules: {out.stdout}")
