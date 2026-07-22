# PyInstaller spec for the macOS .app bundle (Apple Silicon / arm64).
# Build (from this directory, in a venv with serpentine3d + pyinstaller):
#   pyinstaller --clean -y serp3d.spec
# Produces dist/Serpentine3D.app.  See build-dmg.sh for the full flow.
from PyInstaller.utils.hooks import collect_dynamic_libs

# OCP.so links the OCCT runtime via @loader_path/.dylibs/libTK*.dylib, and
# that runtime in turn pulls in the VTK dylibs from the vtkmodules wheel.
# Nothing imports either from Python, so collect both explicitly.
binaries = collect_dynamic_libs("OCP") + collect_dynamic_libs("vtkmodules")

a = Analysis(
    ["serp3d_entry.py"],
    pathex=[],
    binaries=binaries,
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
    console=False,               # GUI app: no terminal
    upx=False,                   # UPX corrupts Qt/OCCT libraries
    target_arch=None,            # native (arm64 on Apple Silicon)
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="serp3d",
    upx=False,
)
app = BUNDLE(
    coll,
    name="Serpentine3D.app",
    icon="serp3d.icns",
    bundle_identifier="com.chisomobanzi.serpentine3d",
    version="0.5.0",
    info_plist={
        "CFBundleName": "Serpentine3D",
        "CFBundleDisplayName": "Serpentine3D",
        "CFBundleShortVersionString": "0.5.0",
        "CFBundleVersion": "0.5.0",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "LSApplicationCategoryType": "public.app-category.graphics-design",
        "NSHumanReadableCopyright": "MIT License · Chisomo Banzi",
    },
)
