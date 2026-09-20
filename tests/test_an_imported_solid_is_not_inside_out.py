"""A solid built from an imported brep faces outward.

Properties showed `Volume: -0.041 mm³` on objects imported from Rhino
files. A negative volume is what OpenCascade reports for a solid whose
faces all point inward, and it is not only a display oddity: outward is
what booleans, offsets and shading all read to tell inside from outside.

It was widespread rather than exotic. Of the openNURBS samples, 58 of the
61 solids in `v5_disk_brake.3dm` came in inverted, 6 of 14 in
`v4_RhinoPhone.3dm`, 4 of 10 in `v5_clip.3dm`, and the single solid in
`v5_ring.3dm`. Faces are rebuilt one at a time and each is oriented on its
own evidence, so a whole sewn shell can come out consistently inside out.
Promoting a shell to a solid is the place that knows, and it was the one
step not checking.
"""

from __future__ import annotations

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.fileio import rhino as R


def _box_faces(reverse: bool):
    """The six faces of a box, optionally each turned inside out."""
    faces = g.faces_of(g.make_box((0, 0, 0), 10, 20, 30))
    if not reverse:
        return faces
    from OCP.TopoDS import TopoDS
    return [TopoDS.Face_s(f.Reversed()) for f in faces]


def _sewn(faces):
    from serpentine3d.core.occ import BRepBuilderAPI_Sewing
    sew = BRepBuilderAPI_Sewing(1e-4)
    for f in faces:
        sew.Add(f)
    sew.Perform()
    return sew.SewedShape()


def test_the_fixture_really_is_inside_out():
    """Without this the test below could pass on a shell that was never
    inverted in the first place."""
    solid = R._shell_to_solid(_sewn(_box_faces(reverse=False)))
    inverted = _sewn(_box_faces(reverse=True))
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeSolid
    from serpentine3d.core import occ
    raw = BRepBuilderAPI_MakeSolid(occ.to_shell(inverted)).Solid()

    assert g.volume(solid) > 0
    assert g.volume(raw) < 0, "the reversed faces have to make a negative solid"


def test_an_inside_out_shell_becomes_an_outward_solid():
    solid = R._shell_to_solid(_sewn(_box_faces(reverse=True)))

    assert g.volume(solid) == pytest.approx(6000.0, rel=1e-6), (
        "a box is 6000 units of material, not minus 6000 of it")
    assert g.is_valid(solid)


def test_a_shell_that_was_already_right_is_left_alone():
    solid = R._shell_to_solid(_sewn(_box_faces(reverse=False)))

    assert g.volume(solid) == pytest.approx(6000.0, rel=1e-6)
    assert g.is_valid(solid)


def test_an_open_shell_is_handed_back_as_it_was():
    """Only a closed shell can say which side is inside, so an open one
    must come through untouched rather than guessed at."""
    open_shell = _sewn(_box_faces(reverse=False)[:4])

    out = R._shell_to_solid(open_shell)

    assert out is not None
    assert g.shape_kind(out) != "solid", "four faces do not enclose anything"


def test_nothing_survives_being_nothing():
    assert R._shell_to_solid(None) is None
