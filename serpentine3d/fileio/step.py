"""STEP import/export via OCCT."""

from __future__ import annotations

from ..core import occ
from ..core.occ import (
    IFSelect_ReturnStatus, STEPControl_Reader, STEPControl_StepModelType,
    STEPControl_Writer, TopExp_Explorer,
)


def export_step(shapes: list, path: str):
    writer = STEPControl_Writer()
    for shape in shapes:
        status = writer.Transfer(shape,
                                 STEPControl_StepModelType.STEPControl_AsIs)
        if status != IFSelect_ReturnStatus.IFSelect_RetDone:
            raise IOError("STEP transfer failed for a shape")
    if writer.Write(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise IOError(f"Could not write STEP file: {path}")


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
