"""Write tests/data/rhino_layout_page.3dm, the fixture for Rhino layout
pages coming in as sheets.

The base is rhino_v5_layout_page.3dm, McNeel's openNURBS
V5/v5_example_file.3dm (see OPENNURBS-LICENSE.txt): 30 model objects and a
Letter page "Page 1" with a top-view detail and four leaders. rhino3dm can
mark objects as on a page but cannot make text, hatches or dimensions, so
those are copies of ones Rhino made: the example's own model text, the
first hatch of rhino_hatches.3dm and the 40.00 dimension of
rhino_linear_dimensions_v8.3dm. Added on Page 1, in paper millimetres:

- a border line from (5, 5) to (210.9, 5), red
- a polyline box (150, 15)-(200, 35), a title box
- the text, moved to (155, 25)
- the hatch, moved to sit near (40, 220)
- the dimension, moved so its first point is at (20, 240)
"""
from pathlib import Path

import rhino3dm as r3

HERE = Path(__file__).resolve().parent
model = r3.File3dm.Read(str(HERE / "rhino_v5_layout_page.3dm"))
page = next(v for v in model.Views if v.Name == "Page 1")


def on_page(layer=0):
    a = r3.ObjectAttributes()
    a.LayerIndex = layer
    a.ActiveSpace = r3.ActiveSpace.PageSpace
    a.ViewportId = page.Viewport.Id
    return a


def moved(geo, x, y):
    """`geo` duplicated with its bounding box's corner moved to (x, y)."""
    copy = geo.Duplicate()
    box = copy.GetBoundingBox()
    copy.Translate(r3.Vector3d(x - box.Min.X, y - box.Min.Y, -box.Min.Z))
    return copy


red = on_page()
red.ColorSource = r3.ObjectColorSource.ColorFromObject
red.ObjectColor = (255, 0, 0, 255)
model.Objects.AddLine(r3.Point3d(5, 5, 0), r3.Point3d(210.9, 5, 0), red)
box = r3.Polyline(5)
for x, y in ((150, 15), (200, 15), (200, 35), (150, 35), (150, 15)):
    box.Add(x, y, 0)
model.Objects.AddPolyline(box, on_page())
text = next(o for o in model.Objects if isinstance(o.Geometry, r3.Text))
model.Objects.Add(moved(text.Geometry, 155, 25),
                  on_page(text.Attributes.LayerIndex))
hatches = r3.File3dm.Read(str(HERE / "rhino_hatches.3dm"))
hatch = next(o for o in hatches.Objects if isinstance(o.Geometry, r3.Hatch))
model.Objects.Add(moved(hatch.Geometry, 40, 220), on_page())
dims = r3.File3dm.Read(str(HERE / "rhino_linear_dimensions_v8.3dm"))
dim = next(o for o in dims.Objects if o.Geometry.PlainText == "40.00")
model.Objects.Add(moved(dim.Geometry, 20, 240), on_page())
path = HERE / "rhino_layout_page.3dm"
assert model.Write(str(path), 7)
back = r3.File3dm.Read(str(path))
on = [o for o in back.Objects
      if str(o.Attributes.ActiveSpace).endswith("PageSpace")]
print(path.name, len(back.Objects), "objects,", len(on), "on pages:",
      sorted(type(o.Geometry).__name__ for o in on))
