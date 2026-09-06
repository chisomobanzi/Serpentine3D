"""Regression for issue #8: nested profiles describe material and a bore."""

import math

import pytest

from serpentine3d.core import geometry as g


def test_extruding_concentric_curves_makes_one_hollow_solid(env):
    scene, _sel, _hist, _ctx, proc = env
    scene.record_history = True
    outer = scene.add(g.make_circle((0, 0, 0), 50))
    inner = scene.add(g.make_circle((0, 0, 0), 30))

    proc.run("extrude")
    proc.click_object(outer.id)
    proc.click_object(inner.id)
    proc.finish_selection()
    proc.provide_text("10")

    solids = [obj for obj in scene.all() if obj.kind == "solid"]
    assert len(solids) == 1
    assert g.volume(solids[0].shape) == pytest.approx(
        math.pi * (50 ** 2 - 30 ** 2) * 10, rel=1e-4)
    assert g.is_valid(solids[0].shape)

    assert scene.history_records[0]["inputs"] == [outer.id, inner.id]
    scene.replace_shape(inner.id, g.make_circle((0, 0, 0), 20))
    assert g.volume(scene.get(solids[0].id).shape) == pytest.approx(
        math.pi * (50 ** 2 - 20 ** 2) * 10, rel=1e-4)
