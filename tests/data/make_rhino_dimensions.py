"""Write tests/data/rhino_linear_dimensions_v7.3dm and _v8.3dm, and
rhino_linear_dimensions.json, the fixture the Rhino dimension import tests
read (#124).

The four linear dimensions are copied, styles and all, out of McNeel's own
openNURBS example files (V7/v7_rhino_logo_annotations.3dm and
V6/V6_annotation.3dm; see OPENNURBS-LICENSE.txt), so they are dimensions
Rhino wrote, not ones drawn here. Needs a checkout of
https://github.com/mcneel/opennurbs at qa/brep-volume/opennurbs/repo.
"""

from pathlib import Path
import json
import math
import subprocess

import rhino3dm as r3


ROOT = Path(__file__).resolve().parents[2]
SDK = ROOT / "qa/brep-volume/opennurbs/repo"
OUT = Path(__file__).resolve().parent
SAMPLES = ["V7/v7_rhino_logo_annotations.3dm", "V6/V6_annotation.3dm"]


def xyz(point):
    return [point.X, point.Y, point.Z]


models = [r3.File3dm.Read(str(SDK / "example_files" / name)) for name in SAMPLES]
manifest = {"source_commit": subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=SDK, text=True).strip(),
    "sources": SAMPLES, "writer": "rhino3dm " + r3.__version__,
    "units": "mm", "dimensions": [], "files": []}

for version in (7, 8):
    model = r3.File3dm()
    model.Settings.ModelUnitSystem = r3.UnitSystem.Millimeters
    layer = r3.Layer()
    layer.Name = "Dimensions"
    model.Layers.Add(layer)
    for sample, source in zip(SAMPLES, models):
        for style in source.DimStyles:
            model.DimStyles.Add(style)
        for index, obj in enumerate(source.Objects):
            geometry = obj.Geometry
            if not isinstance(geometry, r3.DimLinear):
                continue
            geometry = geometry.Duplicate()
            name = sample.split("/")[0] + "_Linear_" + str(index)
            attributes = r3.ObjectAttributes()
            attributes.Name = name
            attributes.LayerIndex = 0
            model.Objects.Add(geometry, attributes)
            if version == 7:
                points = geometry.Points
                arrow1, arrow2 = points["arrowpt1"], points["arrowpt2"]
                length = math.sqrt(sum((a - b) ** 2
                                      for a, b in zip(xyz(arrow1), xyz(arrow2))))
                manifest["dimensions"].append({
                    "name": name, "source": sample,
                    "annotation_type": str(geometry.AnnotationType),
                    "text": geometry.PlainText,
                    "measurement": length,
                    "points": {key: xyz(value) for key, value in points.items()},
                    "plane_origin": xyz(geometry.Plane.Origin),
                    "plane_x": xyz(geometry.Plane.XAxis),
                    "plane_y": xyz(geometry.Plane.YAxis),
                    "style_id": str(geometry.DimensionStyleId),
                })
    path = OUT / ("rhino_linear_dimensions_v%d.3dm" % version)
    assert model.Write(str(path), version)
    restored = r3.File3dm.Read(str(path))
    assert len(restored.Objects) == 4
    assert all(isinstance(obj.Geometry, r3.DimLinear) for obj in restored.Objects)
    for obj, expected in zip(restored.Objects, manifest["dimensions"]):
        assert obj.Attributes.Name == expected["name"]
        points = obj.Geometry.Points
        for key, point in expected["points"].items():
            assert all(abs(a - b) < 1e-9 for a, b in zip(xyz(points[key]), point))
    manifest["files"].append(path.name)

(OUT / "rhino_linear_dimensions.json").write_text(json.dumps(manifest, indent=2))
print(json.dumps(manifest, indent=2))
