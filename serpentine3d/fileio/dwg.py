"""Read DWG with the packaged LibreDWG converter and the shared DXF reader.

Conversion runs in its own process: malformed native files cannot crash the
application, and Cancel can stop the reader. Neither a system converter nor
a network connection is needed.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import time

from ..core.scene import Scene
from . import dxf
from .progress import Progress


_CONVERSION_TIMEOUT = 300.0


def _converter_path() -> Path:
    name = "dwg2dxf.exe" if os.name == "nt" else "dwg2dxf"
    return Path(__file__).resolve().parents[1] / "_vendor" / "libredwg" / name


def _convert(directory: str, report: Progress) -> None:
    converter = _converter_path()
    if not converter.is_file():
        raise RuntimeError(
            "The bundled DWG reader is missing. Reinstall Serpentine3D "
            "or rebuild its package to restore DWG import.")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        process = subprocess.Popen(
            [str(converter), "-v0", "-o", "drawing.dxf", "drawing.dwg"],
            cwd=directory, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, creationflags=flags)
    except OSError as exc:
        raise RuntimeError(
            "The bundled DWG reader could not start. Reinstall Serpentine3D "
            "or rebuild its package for this computer.") from exc
    started = time.monotonic()
    try:
        while True:
            report(0.1, "Reading DWG…")
            try:
                result = process.wait(timeout=0.05)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() - started >= _CONVERSION_TIMEOUT:
                    raise ValueError("DWG import timed out after five minutes.")
        if result != 0 or not (Path(directory) / "drawing.dxf").is_file():
            raise ValueError(
                "Could not read this DWG. It may be damaged or use a DWG "
                "version the bundled reader does not support.")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()


def import_dwg(scene, path: str, progress=None) -> int:
    report = progress if isinstance(progress, Progress) else Progress(progress)
    with tempfile.TemporaryDirectory(prefix="serp-dwg-") as directory:
        # The converter sees only ASCII relative names, including on Windows
        # where the original drawing or the user's temp directory is Unicode.
        with open(path, "rb") as source, open(
                Path(directory) / "drawing.dwg", "wb") as target:
            while chunk := source.read(1024 * 1024):
                report(0.0, "Preparing DWG…")
                target.write(chunk)
        _convert(directory, report)
        report(0.8, "Creating DWG geometry…")
        # Keep parsing failures and cancellation from leaving partial objects
        # or layers behind in the user's drawing.
        imported = Scene()
        imported.units = scene.units
        try:
            count = dxf.import_dxf(imported, str(Path(directory) / "drawing.dxf"))
        except Exception as exc:
            raise ValueError("Could not read geometry from this DWG.") from exc
        report(0.95, "Adding DWG geometry…")
        layer_map = {}
        for obj in imported.all():
            layer = imported.layers.get(obj.layer_id)
            if layer.name == "Default":
                layer_id = None
            else:
                if layer.id not in layer_map:
                    dest = (scene.layers.find_by_name(layer.name)
                            or scene.layers.create(layer.name))
                    layer_map[layer.id] = dest.id
                layer_id = layer_map[layer.id]
            scene.add(obj.shape, layer_id=layer_id)
        return count
