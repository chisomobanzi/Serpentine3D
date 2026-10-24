"""STEP import/export via OCCT."""

from __future__ import annotations

from ..core import occ
from ..core.occ import (
    IFSelect_ReturnStatus, STEPControl_Reader, STEPControl_StepModelType,
    STEPControl_Writer, TopExp_Explorer,
)
from ..utils.units import TO_MM, converted_note

# The unit a STEP file is written in, by document unit; OCCT's own names.
_WRITE_UNIT = {"mm": "MM", "cm": "CM", "m": "M", "in": "INCH", "ft": "FT"}

# What a file says its lengths are in, as OCCT reads it back: SI units by
# their full name, the rest by the name the file gives them.
_FILE_UNIT = {"millimetre": "mm", "centimetre": "cm", "metre": "m",
              "inch": "in", "foot": "ft", "feet": "ft"}


def export_step(shapes: list, path: str, units: str = "mm") -> int:
    """Write `shapes` as STEP; returns how many meshes it had to leave out.

    The file is written in the drawing's unit and says so. Writing an inch
    drawing's numbers under the default millimetre label made a 1 in cube a
    1 mm one everywhere else (#101).

    STEP carries BREP and nothing else, so an imported mesh cannot go
    in one. Handing the writer a mesh anyway raised a pybind overload
    TypeError, which reached the user as a wall of OCP signatures.
    """
    from OCP.Interface import Interface_Static
    from ..core.mesh import MeshShape
    writer = STEPControl_Writer()
    writer.Model().SetLocalLengthUnit(TO_MM[units])
    # The unit the file is written in is a session setting in OCCT, not the
    # writer's, so it is put back for whatever writes next.
    before = Interface_Static.CVal_s("write.step.unit")
    Interface_Static.SetCVal_s("write.step.unit", _WRITE_UNIT[units])
    try:
        skipped = 0
        for shape in shapes:
            if isinstance(shape, MeshShape):
                skipped += 1
                continue
            status = writer.Transfer(
                shape, STEPControl_StepModelType.STEPControl_AsIs)
            if status != IFSelect_ReturnStatus.IFSelect_RetDone:
                raise IOError("STEP transfer failed for a shape")
        if skipped == len(shapes):
            raise ValueError(
                "STEP cannot carry mesh objects, and every object here is "
                "one. Export to OBJ, STL or 3MF instead.")
        if writer.Write(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
            raise IOError(f"Could not write STEP file: {path}")
    finally:
        Interface_Static.SetCVal_s("write.step.unit", before or "MM")
    return skipped


def _file_unit(reader) -> str | None:
    """The unit the file's lengths are in, as one of ours where it is one."""
    from OCP.TColStd import TColStd_SequenceOfAsciiString
    lengths = TColStd_SequenceOfAsciiString()
    reader.FileUnits(lengths, TColStd_SequenceOfAsciiString(),
                     TColStd_SequenceOfAsciiString())
    if not lengths.Length():
        return None
    name = lengths.Value(1).ToCString().strip().lower()
    return _FILE_UNIT.get(name, name)


def import_step(path: str, units: str = "mm",
                notes: list | None = None) -> list:
    """Returns a list of top-level TopoDS_Shapes from the file, in `units`.

    OCCT converts from whatever unit the file declares; `notes` hears when
    that was not the drawing's own."""
    reader = STEPControl_Reader()
    if reader.ReadFile(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise IOError(f"Could not read STEP file: {path}")
    # After ReadFile, which sets it back to the session's millimetres.
    reader.SetSystemLengthUnit(TO_MM[units])
    source = _file_unit(reader)
    if notes is not None and source and source != units:
        notes.append(converted_note(source, units))
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
