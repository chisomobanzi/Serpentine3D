"""Guards on the AppImage build script.

The bug these exist for: pip caches wheels it builds from a local directory
under name+version. The version in pyproject.toml only moves at release time,
so every build between releases silently reused the wheel from the first one
and shipped stale code — twice in a row, with the source on disk correct and
the bundle a day behind.
"""

from pathlib import Path

SCRIPT = (Path(__file__).resolve().parent.parent
          / "packaging" / "appimage" / "build-appimage.sh")


def _text():
    return SCRIPT.read_text()


def test_the_script_exists():
    assert SCRIPT.is_file()


def test_drops_its_own_cached_wheel_before_building():
    """Otherwise pip serves a wheel built from an older checkout."""
    text = _text()
    assert "serpentine3d-*.whl" in text or "pip cache remove" in text, (
        "build-appimage.sh must clear the cached serpentine3d wheel, or a "
        "rebuild at the same version reuses the previous build's code")


def test_the_entrypoint_keeps_the_working_directory_off_sys_path():
    """`python -m pkg` puts the CWD first on sys.path. Launch the AppImage
    from a directory that happens to contain a serpentine3d/ folder — a
    checkout, say — and it silently runs that code instead of the bundle."""
    text = _text()
    assert "-P -m serpentine3d" in text or "PYTHONSAFEPATH" in text, (
        "the AppImage entrypoint must not put the launch directory on "
        "sys.path ahead of the bundled package")


def test_clears_the_cache_before_the_build_runs_not_after():
    text = _text()
    purge = text.find("serpentine3d-*.whl")
    build = text.find("build app --python-version")
    assert purge != -1 and build != -1
    assert purge < build, "clearing the wheel cache after the build is useless"
