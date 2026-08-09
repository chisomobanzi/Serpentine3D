"""STEP import/export via OCCT."""

from __future__ import annotations

from ..core import occ
from ..core.occ import (
    IFSelect_ReturnStatus, STEPControl_Reader, STEPControl_StepModelType,
    STEPControl_Writer, TopExp_Explorer,
)


def export_step(shapes: list, path: str) -> int:
    """Write `shapes` as STEP; returns how many meshes it had to leave out.

    STEP carries BREP and nothing else, so an imported mesh cannot go
    in one. Handing the writer a mesh anyway raised a pybind overload
    TypeError, which reached the user as a wall of OCP signatures.
    """
    from ..core.mesh import MeshShape
    writer = STEPControl_Writer()
    skipped = 0
    for shape in shapes:
        if isinstance(shape, MeshShape):
            skipped += 1
            continue
        status = writer.Transfer(shape,
                                 STEPControl_StepModelType.STEPControl_AsIs)
        if status != IFSelect_ReturnStatus.IFSelect_RetDone:
            raise IOError("STEP transfer failed for a shape")
    if skipped == len(shapes):
        raise ValueError(
            "STEP cannot carry mesh objects, and every object here is one. "
            "Export to OBJ, STL or 3MF instead.")
    if writer.Write(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise IOError(f"Could not write STEP file: {path}")
    return skipped


def import_step(path: str) -> list:
    """Returns a list of top-level TopoDS_Shapes from the file."""
    reader = STEPControl_Reader()
    if reader.ReadFile(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise IOError(f"Could not read STEP file: {path}")
    reader.TransferRoots()
    shapes = []
    for i in range(1, reader.NbShapes() + 1):
        shape = reader.Shape(i)
        if shape.IsNull():
            continue
        # unpack top-level compounds into individual objects
        if shape.ShapeType() == occ.COMPOUND:
            it = TopExp_Explorer(shape, occ.SOLID)
            found = False
            while it.More():
                shapes.append(it.Current())
                found = True
                it.Next()
            if not found:
                shapes.append(shape)
        else:
            shapes.append(shape)
    return shapes
