"""Write tests/data/rhino_hatches.3dm and rhino_hatch_lines.json, the
fixture the Rhino hatch import tests read (#92).

Run it inside Rhino 7 or later, which is the point of it: Rhino draws the
hatches, and Explode hands back the lines it draws them with, so the
test compares what the import draws against Rhino itself.

    Rhino.exe /nosplash /runscript="-_RunPythonScript tests\data\make_rhino_hatches.py"

The hatches cover Rhino's own patterns and two from rhino_hatches.pat,
scaled and turned, with base points moved, a circle with a hole in it
and one off the world's XY plane.
"""
import json
import os
import Rhino
import rhinoscriptsyntax as rs
import scriptcontext as sc

OUT = os.path.dirname(os.path.abspath(__file__))
doc = sc.doc
for p in Rhino.DocObjects.HatchPattern.ReadFromFile(
        os.path.join(OUT, "rhino_hatches.pat"), True):
    doc.HatchPatterns.Add(p)


def square(x, y, s):
    return rs.AddPolyline([(x, y, 0), (x + s, y, 0), (x + s, y + s, 0),
                           (x, y + s, 0), (x, y, 0)])


specs = [("Hatch2", 8.0, 0.0, None), ("HatchDash", 6.0, 30.0, None),
         ("Plus", 3.0, 0.0, (1.0, 0.5)), ("BRICK", 12.0, 20.0, (3.0, 2.0)),
         ("DASHDOT", 15.0, 35.0, (-2.0, 1.5)), ("Grid60", 8.0, 15.0, None),
         ("Solid", 1.0, 0.0, None)]
made = []
for i, (name, scale, rot, base) in enumerate(specs):
    x = i * 30
    c = square(x, 0, 20)
    hid = rs.AddHatch(c, name, scale, rot)
    rs.DeleteObject(c)
    if base is not None:
        h = rs.coercegeometry(hid)
        h.BasePoint = Rhino.Geometry.Point3d(x + base[0], base[1], 0)
        sc.doc.Objects.Replace(hid, h)
    made.append(hid)

outer = rs.AddCircle((0, 40, 0), 10)
hole = rs.AddRectangle(rs.PlaneFromNormal((-3, 37, 0), (0, 0, 1)), 6, 6)
hid = rs.AddHatches([outer, hole], "Hatch1", 6.0, 10.0)[0]
h = rs.coercegeometry(hid)
h.BasePoint = Rhino.Geometry.Point3d(3, 2, 0)
sc.doc.Objects.Replace(hid, h)
rs.DeleteObjects([outer, hole])
made.append(hid)

t = rs.AddPolyline([(40, 40, 0), (60, 40, 0), (60, 40, 15), (40, 40, 15),
                    (40, 40, 0)])
made.append(rs.AddHatch(t, "Grid", 5.0, 30.0))
rs.DeleteObject(t)

for k, hid in enumerate(made):
    rs.ObjectName(hid, "H%d" % k)
rs.Command('-_SaveAs "%s" _Enter' % os.path.join(OUT, "rhino_hatches.3dm"),
           False)

lines = {}
for k, hid in enumerate(made):
    h = rs.coercegeometry(hid)
    segs = []
    for part in h.Explode():
        if isinstance(part, Rhino.Geometry.LineCurve):
            a, b = part.PointAtStart, part.PointAtEnd
            segs.append([[round(a.X, 9), round(a.Y, 9), round(a.Z, 9)],
                         [round(b.X, 9), round(b.Y, 9), round(b.Z, 9)]])
    lines["H%d" % k] = segs
# bytes, which IronPython 2.7 and Rhino 8's Python 3 both write the same
with open(os.path.join(OUT, "rhino_hatch_lines.json"), "wb") as fh:
    fh.write(json.dumps(lines).encode("utf-8"))
rs.DocumentModified(False)
rs.Command("_-Exit _No", False)
