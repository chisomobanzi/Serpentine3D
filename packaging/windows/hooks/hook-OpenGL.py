# Stands in for pyinstaller-hooks-contrib's hook-OpenGL.py, which a hook of the
# same name in the spec's hookspath replaces outright, so this one must do all
# it does. It was checked against contrib 2026.9; compare the two whenever
# PyInstaller or its contrib hooks are bumped.
#
# PyOpenGL ships freeglut and GLE built against three Visual C++ runtimes:
# 2008 (vc9), 2010 (vc10) and 2015 (vc14). From Python 3.5 on,
# OpenGL/platform/win32.py loads only vc14. The contrib hook collects all
# three, so the installer carried two sets nothing loads, and every build
# warned that MSVCR90.dll and MSVCR100.dll, which they link against, could not
# be found. That check runs inside Analysis(), so the only way to stop it is to
# leave those files out here (#77).
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# PyOpenGL imports its platform module and array handlers by name at run time,
# where PyInstaller cannot follow.
hiddenimports = ["OpenGL.platform.win32", *collect_submodules("OpenGL.arrays")]

# It opens its DLLs with ctypes, so they go in as data files.
_NEVER_LOADED = (".vc9.dll", ".vc10.dll")
datas = [(src, dest) for src, dest in collect_data_files("OpenGL")
         if not src.lower().endswith(_NEVER_LOADED)]
