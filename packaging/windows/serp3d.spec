# PyInstaller spec for the Windows build.
# Build (from this directory, in a venv with serpentine3d + pyinstaller):
#   pyinstaller --clean -y serp3d.spec
import importlib.util
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

# OCP.pyd links against the VTK runtime shipped in the vtkmodules wheel;
# nothing imports vtk from Python, so collect the DLLs explicitly.
vtk_bins = collect_dynamic_libs("vtkmodules")

# ProductName/ProductVersion on the .exe, generated from the package version.
# SignPath enforces both at signing time; Windows shows them in Properties.
_mvi_path = Path(SPECPATH) / "make_version_info.py"
_mvi_spec = importlib.util.spec_from_file_location("make_version_info", _mvi_path)
make_version_info = importlib.util.module_from_spec(_mvi_spec)
_mvi_spec.loader.exec_module(make_version_info)
version_file = str(make_version_info.main())

a = Analysis(
    ["serp3d_entry.py"],
    pathex=[],
    binaries=vtk_bins,
    datas=[],
    hiddenimports=[],
    excludes=[
        "tkinter",
        "matplotlib.backends.backend_tkagg",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtQuick3D",
        "PySide6.QtPdf",
        "PySide6.QtCharts",
        "PySide6.QtMultimedia",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="serp3d",
    icon="serp3d.ico",
    version=version_file,        # ProductName/ProductVersion resource
    console=False,               # GUI app: no console window
    upx=False,                   # UPX corrupts Qt/OCCT DLLs
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="serp3d",
    upx=False,
)
