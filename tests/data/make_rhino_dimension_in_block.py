"""Write tests/data/rhino_dimension_in_scaled_blocks.3dm.

The 40.00 linear dimension from rhino_linear_dimensions_v8.3dm (which came
from McNeel's openNURBS examples, see make_rhino_dimensions.py), put inside
a block definition and placed twice: at 1/25, as a drawing sheet scaled
into a model is, and at 2. Rhino shows 40.00 on both, since a dimension in
a block says what it measures in the block.
"""
from pathlib import Path

import rhino3dm as r3

HERE = Path(__file__).resolve().parent
model = r3.File3dm.Read(str(HERE / "rhino_linear_dimensions_v8.3dm"))
dims = [o for o in model.Objects if o.Geometry.PlainText == "40.00"]
assert len(dims) == 1
keep = dims[0]
for obj in list(model.Objects):
    model.Objects.Delete(obj.Attributes.Id)
index = model.InstanceDefinitions.Add(
    "DIMMED", "a dimension in a block", "", "", r3.Point3d(0, 0, 0),
    (keep.Geometry,), (keep.Attributes,))
assert index >= 0
for at, scale in (((500.0, 0.0, 0.0), 1.0 / 25.0), ((0.0, 500.0, 0.0), 2.0)):
    xform = r3.Transform.Scale(r3.Point3d(0, 0, 0), scale)
    xform.M03, xform.M13, xform.M23 = at
    definition = model.InstanceDefinitions.FindIndex(index)
    model.Objects.AddInstanceObject(
        r3.InstanceReference(definition.Id, xform))
path = HERE / "rhino_dimension_in_scaled_blocks.3dm"
assert model.Write(str(path), 8)
back = r3.File3dm.Read(str(path))
print(path.name, len(back.Objects), "objects,",
      len(back.InstanceDefinitions), "definition")
