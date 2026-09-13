# Bundled DWG reader

Application builds stage GNU LibreDWG 0.14's `dwg2dxf` executable before
installing the Python package. It runs as a separate process over temporary
files. There are no runtime downloads and no dependency on a converter in PATH.

For a source checkout, run `python3 packaging/prepare_dwg.py` before testing DWG
imports. This requires Python 3.12 or newer; Linux/macOS builders also need a
C compiler and GNU make. Windows uses the pinned upstream x86_64 binaries.
The AppImage, Windows installer and macOS DMG scripts run this step themselves.

The script verifies SHA-256 digests for downloads, caches builds outside the
repository, and stages generated files under `serpentine3d/_vendor/libredwg/`.
That directory is ignored by Git and included as package data for bundles.
Do not publish the locally staged wheel as a platform-independent PyPI wheel:
it contains a converter for the build platform. For a different target, rerun
the preparation script on that target before building the package.

LibreDWG is GPL-3.0-or-later. Each bundle includes its licence, README, the
unmodified corresponding source archive (including upstream build recipes),
and our preparation script beside the executable. Windows includes only
`dwg2dxf.exe` and `libredwg-0.dll`; these depend on Windows system DLLs, not
the unrelated iconv or PCRE DLLs in the upstream download. Linux/macOS link
LibreDWG statically into the standalone executable. Linux also builds against
musl 1.2.5 statically, so a new build host cannot silently raise the AppImage's
minimum glibc version. The musl source and copyright notice are bundled too.

DWG imports have the existing DXF geometry coverage. This does not implement
AutoCAD document fidelity or DWG export. See the file-format reference for
unsupported entity categories.
