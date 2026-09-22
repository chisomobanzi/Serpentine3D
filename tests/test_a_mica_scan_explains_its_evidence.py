from serpentine3d.core.pointcloud import PointCloudShape
from serpentine3d.core.scene import Scene
from serpentine3d.ui.properties import cloud_measures


def _properties_summary(cloud):
    obj = Scene().add(cloud)
    return cloud_measures(obj, lambda value: f"{value:g} m")


def test_a_mica_scan_properties_explain_the_evidence_behind_its_surface():
    cloud = PointCloudShape(
        [[0, 0, 0], [2, 3, 4]],
        conf=[0.25, 0.75],
        provenance={
            "backbone": "lingbot-map",
            "pose_source": "image_only",
            "scale": "model_estimated_metric",
            "scale_source": "multi-window depth consensus",
            "limitations": "Blank walls can weaken camera tracking.",
        },
    )

    summary = _properties_summary(cloud)
    lower = summary.lower()

    assert "Points: 2" in summary
    assert "Size: 2 m × 3 m × 4 m" in summary
    support_line, = [line for line in summary.splitlines()
                     if "heuristic surface support (mean)" in line.lower()]
    assert "50" in support_line
    assert "camera-only" in lower and "image-only" in lower
    assert "model-estimated metric" in lower
    assert "Backbone: lingbot-map" in summary
    assert "multi-window depth consensus" in lower
    assert "Blank walls can weaken camera tracking." in summary
    assert all(term not in lower
               for term in ("probability", "surveyed", "calibrated", "accuracy"))


def test_a_legacy_scan_without_evidence_keeps_its_plain_properties_summary():
    cloud = PointCloudShape([[0, 0, 0], [1, 2, 3]])

    assert _properties_summary(cloud) == (
        "Points: 2\n"
        "Size: 1 m × 2 m × 3 m\n"
        "No colour: drawn in the layer colour"
    )
