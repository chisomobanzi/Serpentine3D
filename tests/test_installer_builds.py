"""The macOS and Windows installer builds.

Both hand the repo root to pip to get a real (non-editable) install that
PyInstaller can trace. That goes through the same setuptools staging directory
as every other build, and setuptools never takes anything out of it — so a
package that has been renamed or deleted keeps being installed into the build
venv long after it stopped existing in the tree. The AppImage build shipped
`serpentine` for a fortnight after the rename to `serpentine3d` for exactly
this reason.

Neither spec sweeps whole packages in (`hiddenimports=[]`, no `collect_all`),
so PyInstaller drops what nothing imports and the ghost never reached the
finished .exe or .dmg. That is luck, not design: it holds only until someone
adds a `collect_submodules`.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MACOS = ROOT / "packaging" / "macos" / "build-dmg.sh"
WINDOWS = ROOT / "packaging" / "windows" / "build-installer.ps1"


@pytest.mark.parametrize("script", [MACOS, WINDOWS], ids=["macos", "windows"])
def test_the_build_script_is_there(script):
    assert script.is_file(), f"{script} has moved or been renamed"


def test_macos_clears_setuptools_staging_before_installing():
    text = MACOS.read_text()
    purge = text.find("rm -rf ../../build")
    install = text.find("--no-deps ../..")
    assert purge != -1, (
        "build-dmg.sh must clear the repo's build/ staging directory, or a "
        "renamed package keeps being installed into the build venv")
    assert install != -1, "the non-editable install line has changed shape"
    assert purge < install, "clearing staging after the install is useless"


def test_windows_clears_setuptools_staging_before_installing():
    text = WINDOWS.read_text()
    purge = text.find(r"..\..\build")
    install = text.find(r"--no-deps ..\..")
    assert purge != -1, (
        "build-installer.ps1 must clear the repo's build/ staging directory, "
        "or a renamed package keeps being installed into the build venv")
    assert install != -1, "the non-editable install line has changed shape"
    assert purge < install, "clearing staging after the install is useless"


@pytest.mark.parametrize("spec", [
    ROOT / "packaging" / "macos" / "serp3d.spec",
    ROOT / "packaging" / "windows" / "serp3d.spec",
], ids=["macos", "windows"])
def test_the_specs_do_not_sweep_whole_packages_in(spec):
    """What keeps a stale package out of the finished bundle is that
    PyInstaller only takes what the entry script imports. A collect_all or a
    collect_submodules over our own package would hand that guarantee back."""
    text = spec.read_text()
    for sweep in ("collect_all", "collect_submodules"):
        assert f"{sweep}(" not in text or "serpentine" not in text.split(
            f"{sweep}(")[1][:40], (
            f"{spec.name} sweeps packages in with {sweep}; staging must be "
            "clean for that to be safe")
