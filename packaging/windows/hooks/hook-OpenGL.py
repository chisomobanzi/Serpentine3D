# ------------------------------------------------------------------
# Local override of the contributed hook-opengl.py hook.
#
# Upstream does, on Windows:
#
#     datas = collect_data_files('OpenGL')
#
# which sweeps in every file under OpenGL/DLLS, including the VC9 builds
# (freeglut*.vc9.dll, gle*.vc9.dll). Those link against the MSVC 2008 runtime
# (MSVCR90.dll), which no modern Windows ships, so binary dependency resolution
# inside Analysis() reports:
#
#     WARNING: Library not found: could not resolve 'MSVCR90.dll' ...
#
# Filtering Analysis().binaries afterwards cannot silence that: the scan runs
# during Analysis(), before the spec gets control back. The dead weight has to
# be kept out of the collected files in the first place.
#
# The VC9 files are never loaded anyway: on Python >= 3.5
# OpenGL/platform/win32.py hardcodes vc = 'vc14' (vc10 for 3.3-3.4), so the
# runtime only ever dlopen()s the vc14/vc10 variant.
#
# Everything else here deliberately mirrors upstream so the override only
# removes the dead VC9 files and changes nothing else: the platform plugin
# hidden import, the OpenGL.arrays submodules, and the rest of the OpenGL data
# files. Revisit if PyOpenGL's hook gains new responsibilities.
# ------------------------------------------------------------------

import os

from PyInstaller.compat import is_darwin, is_win
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# PlatformPlugin performs a conditional import based on os.name and
# sys.platform. PyInstaller misses this so let's add it ourselves...
if is_win:
    hiddenimports = ['OpenGL.platform.win32']
elif is_darwin:
    hiddenimports = ['OpenGL.platform.darwin']
# Use glx for other platforms (Linux, ...)
else:
    hiddenimports = ['OpenGL.platform.glx']

# Arrays modules are needed too.
hiddenimports += collect_submodules('OpenGL.arrays')


def _is_dead_vc9(src, dest):
    name = os.path.basename(str(src))
    return name.lower().endswith('.vc9.dll')


# PyOpenGL loads these DLLs through ctypes, so PyInstaller cannot discover
# them by import; they must be shipped as data files.
if is_win:
    datas = [(s, d) for s, d in collect_data_files('OpenGL') if not _is_dead_vc9(s, d)]