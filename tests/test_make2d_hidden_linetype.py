"""Make2D's hidden curves start dashed and remain controlled by their layer."""

import math

import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401
from serpentine3d.commands.base import SelectReq
from serpentine3d.core import geometry as g, linetype
from serpentine3d.ui.camera import Camera
from tests.conftest import StubViewport


@pytest.fixture
def projection_env(env):
    scene, selection, history, ctx, proc = env
    scene.add(g.make_box((0, 0, 0), 30, 20, 10), name="Input box")
    ctx.viewport = StubViewport("model")
    ctx.viewport.camera = Camera()
    ctx.viewport.camera.azimuth = -math.pi / 4
    ctx.viewport.camera.elevation = math.asin(1 / math.sqrt(3))
    return env


def _project(env):
    scene, selection, history, ctx, proc = env
    before_ids = {obj.id for obj in scene.all()}
    current_layer = scene.layers.current_id
    assert proc.run("make2d")
    assert isinstance(proc.request, SelectReq)
    proc.finish_selection()  # Enter projects all visible source geometry.
    assert not proc.busy

    made = [obj for obj in scene.all() if obj.id not in before_ids]
    assert len(made) == 2
    drawings = {scene.layers.get(obj.layer_id).name: obj for obj in made}
    assert set(drawings) == {"Make2D visible", "Make2D hidden"}
    assert scene.layers.current_id == current_layer
    source = scene.find_by_name("Input box")
    assert source.visible and source.kind == "solid"
    assert g.volume(source.shape) == pytest.approx(6000)

    # An isometric box keeps nine visible and three hidden projected edges.
    # Each axis projects to sqrt(2/3) of its world length, on world XY.
    for name, count, length in (
            ("Make2D visible", 9, 180 * math.sqrt(2 / 3)),
            ("Make2D hidden", 3, 60 * math.sqrt(2 / 3))):
        obj = drawings[name]
        assert obj.kind == "curve" and obj.visible
        assert len(g.edges_of(obj.shape)) == count
        assert g.curve_length(obj.shape) == pytest.approx(length)
        low, high = obj.bbox()
        assert low[2] == pytest.approx(0, abs=1e-6)
        assert high[2] == pytest.approx(0, abs=1e-6)
    return drawings


def test_new_make2d_layers_use_hidden_and_continuous_linetypes(projection_env):
    scene = projection_env[0]
    drawings = _project(projection_env)
    visible = scene.layers.get(drawings["Make2D visible"].layer_id)
    hidden = scene.layers.get(drawings["Make2D hidden"].layer_id)

    assert visible.linetype == "Continuous"
    assert hidden.linetype == "Hidden"
    assert visible.visible and hidden.visible
    assert linetype.pattern_for(hidden.linetype) == linetype.LINETYPES["Hidden"]
    assert linetype.pattern_for(hidden.linetype), "Hidden lines need dash gaps"


def test_make2d_curves_inherit_later_layer_linetype_changes(projection_env):
    scene = projection_env[0]
    drawings = _project(projection_env)

    for name, style in (("Make2D visible", "Center"),
                        ("Make2D hidden", "Phantom")):
        obj = drawings[name]
        assert obj.linetype == "ByLayer"
        scene.layers.set_linetype(obj.layer_id, style)
        layer = scene.layers.get(obj.layer_id)
        assert linetype.resolve(obj.linetype, layer.linetype) == style


@pytest.mark.parametrize("hidden_style", ["Continuous", "Dotted"])
def test_reusing_make2d_layers_preserves_user_styles_and_visibility(
        projection_env, hidden_style):
    scene = projection_env[0]
    visible = scene.layers.create("Make2D visible", (0.2, 0.4, 0.6))
    hidden = scene.layers.create("Make2D hidden", (0.6, 0.4, 0.2))
    scene.layers.set_linetype(visible.id, "Center")
    scene.layers.set_linetype(hidden.id, hidden_style)
    scene.layers.set_visible(hidden.id, False)
    before = scene.layers.snapshot()

    drawings = _project(projection_env)

    assert scene.layers.snapshot() == before
    for name, layer_id, style in (
            ("Make2D visible", visible.id, "Center"),
            ("Make2D hidden", hidden.id, hidden_style)):
        obj = drawings[name]
        assert obj.layer_id == layer_id
        assert obj.linetype == "ByLayer"
        layer = scene.layers.get(layer_id)
        assert linetype.resolve(obj.linetype, layer.linetype) == style
    assert drawings["Make2D visible"] in scene.visible_objects()
    assert drawings["Make2D hidden"] not in scene.visible_objects()
