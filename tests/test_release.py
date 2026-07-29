"""One version number, written in nine places.

Nothing computes the version from `__version__`: the Inno script, the
PyInstaller spec, the dmg builder and three sets of download links each
carry their own copy, because none of them can import Python at the time
they need it. So a release is a hand edit across nine files, and the ones
that go wrong are the quiet ones — a splash screen still claiming the last
version, or a download link pointing at a `.dmg` the new release does not
contain, which reads as a 404 to whoever clicks it.

This test does not check that the version is *right*. It checks that every
copy says the same thing, which is the part a person doing it by hand gets
wrong.
"""

import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Each file with the pattern that finds its version strings. Every pattern
# must match at least once — a file that gets restructured out from under
# one of these should fail the test, not silently stop being checked.
V = r"(\d+(?:\.\d+)+)"          # never trailing punctuation: "0.5.3." is prose

DECLARED = {
    "pyproject.toml": rf'^version = "{V}"',
    "serpentine3d/__init__.py": rf'^__version__ = "{V}"',
    "serpentine3d/ui/splash.py": rf'version: str = "{V}"',
    "packaging/macos/serp3d.spec":
        rf'(?:^\s*version|CFBundleShortVersionString"|CFBundleVersion")'
        rf'\s*[=:]\s*"{V}"',
    "packaging/macos/build-dmg.sh": rf'^VERSION="{V}"',
    "packaging/windows/installer.iss": rf'#define AppVersion "{V}"',
    # the download links have the version baked into the file name, so they
    # rot into 404s rather than into a stale-but-working page
    "README.md": rf'Serpentine3D-{V}-arm64\.dmg',
    "docs/getstarted/install.md": rf'Serpentine3D-{V}-arm64\.dmg',
    "website/index.html":
        rf'Serpentine3D-{V}-arm64\.dmg|version&nbsp;{V}',
}


def _found(rel: str, pattern: str) -> list[str]:
    text = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    hits = re.findall(pattern, text, re.MULTILINE)
    # alternation groups come back as tuples; keep whichever branch matched
    flat = []
    for h in hits:
        flat.extend([p for p in ([h] if isinstance(h, str) else h) if p])
    return flat


def test_every_file_that_names_the_version_agrees():
    from serpentine3d import __version__
    wrong = {}
    for rel, pattern in DECLARED.items():
        hits = _found(rel, pattern)
        assert hits, (
            f"{rel}: nothing matched /{pattern}/ — either the version moved "
            f"or this file stopped being checked. Fix the pattern.")
        odd = sorted({h for h in hits if h != __version__})
        if odd:
            wrong[rel] = odd
    assert not wrong, (
        f"serpentine3d.__version__ is {__version__!r}, but:\n"
        + "\n".join(f"  {rel}: {v}" for rel, v in sorted(wrong.items()))
        + "\n\nEvery copy has to move together, including the .dmg download "
          "links — a link naming a file the release does not contain is a "
          "404 for whoever clicks it.")


def test_the_changelog_leads_with_the_version_being_shipped():
    """The top section is either the release itself or work queued behind
    it; either way an entry for a version we are past is a mistake."""
    from serpentine3d import __version__
    heads = [ln.strip() for ln in
             open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8")
             if ln.startswith("## ")]
    assert heads, "the changelog has no version headings at all"
    top = heads[0]
    assert __version__ in top or "Unreleased" in top, (
        f"the changelog opens with {top!r}, which is neither "
        f"{__version__!r} nor an Unreleased section")
