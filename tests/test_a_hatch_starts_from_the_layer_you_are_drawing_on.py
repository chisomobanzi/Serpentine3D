"""The hatch command opens on the pattern the current layer is drawn with.

Setting a layer's hatch is only worth doing if something reads it, and
the thing that reads it is the prompt: draw on Concrete and Pattern comes
up already saying Cross, so hatching a wall is a click and an Enter
rather than a decision taken again on every region. It stays a prompt, so
the one region that wants something else still gets it.

A layer with nothing to say leaves the command as it was, offering Lines.
"""

from __future__ import annotations

from types import SimpleNamespace

from serpentine3d.commands import drafting
from serpentine3d.core.layers import DEFAULT_LAYER_ID
from serpentine3d.core.layout import DetailView, Layout
from tests.conftest import StubViewport


SQUARE = [(-20.0, -20.0), (20.0, -20.0), (20.0, 20.0), (-20.0, 20.0),
          (-20.0, -20.0)]


def _paper(env, monkeypatch=None):
    """A sheet with one 1:1 detail on it, made current."""
    scene, _sel, _hist, ctx, proc = env
    lay = Layout(name="Sheet 1")
    lay.details.append(DetailView(x=0.0, y=0.0, w=100.0, h=100.0,
                                  scale_denom=1.0))
    scene.layouts.append(lay)
    ctx.viewport = StubViewport(lay.id)
    if monkeypatch is not None:
        view = SimpleNamespace(_detail_hlr=lambda d: {
            "visible": [SQUARE], "hidden": [], "cut": []})
        monkeypatch.setattr(drafting, "_layout_view", lambda ctx: view)
    return scene, lay, proc


def _corners(proc):
    """Three corners and the Enter that closes them, leaving Pattern up."""
    proc.run("hatch")
    for point in ("10,10", "30,10", "30,30"):
        proc.provide_text(point)
    proc.provide_text("")


# -- what the prompt opens on --

def test_the_pattern_prompt_opens_on_the_current_layer_s_hatch(env):
    scene, _lay, proc = _paper(env)
    scene.layers.set_hatch(DEFAULT_LAYER_ID, "cross")
    _corners(proc)
    assert proc.request.default == "Cross", \
        "the layer says cross and the prompt still opened on lines"


def test_the_prompt_offers_every_fill_a_layer_can_be_set_to(env):
    """One list, so a layer cannot be set to a fill the prompt has lost."""
    from serpentine3d.core.layout import HATCH_PATTERNS
    _scene, _lay, proc = _paper(env)
    _corners(proc)
    assert proc.request.options == [p.capitalize() for p in HATCH_PATTERNS]


def test_a_layer_with_no_hatch_leaves_the_prompt_where_it_was(env):
    _scene, _lay, proc = _paper(env)
    _corners(proc)
    assert proc.request.default == "Lines"


def test_pressing_enter_takes_the_layer_s_hatch(env):
    scene, lay, proc = _paper(env)
    scene.layers.set_hatch(DEFAULT_LAYER_ID, "solid")
    _corners(proc)
    proc.provide_text("")               # accept the pattern offered
    assert not proc.busy, "solid asked for a spacing it has no use for"
    assert lay.hatches[0].pattern == "solid"


def test_the_region_you_click_in_is_hatched_the_layer_s_way(env,
                                                            monkeypatch):
    scene, lay, proc = _paper(env, monkeypatch)
    scene.layers.set_hatch(DEFAULT_LAYER_ID, "cross")
    proc.run("hatch")
    proc.provide_text("Mode=Region")
    proc.provide_text("50,50")          # inside the square on the paper
    assert proc.request.default == "Cross"
    proc.provide_text("")
    assert lay.hatches[0].pattern == "cross"


def test_the_layer_offers_a_pattern_and_does_not_impose_one(env):
    """It is a default, not a rule: one region in another material still
    gets what you type."""
    scene, lay, proc = _paper(env)
    scene.layers.set_hatch(DEFAULT_LAYER_ID, "cross")
    _corners(proc)
    proc.provide_text("Solid")
    assert lay.hatches[0].pattern == "solid"


# -- and the command that sets it --

def test_the_layer_command_sets_a_layer_s_hatch(env):
    scene, _sel, _hist, _ctx, proc = env
    scene.layers.create("Concrete")
    proc.run("layer")
    proc.provide_text("Hatch")
    proc.provide_text("Concrete")
    proc.provide_text("Cross")
    assert scene.layers.find_by_name("Concrete").hatch == "cross"


def test_the_layer_command_opens_on_the_hatch_the_layer_already_has(env):
    scene, _sel, _hist, _ctx, proc = env
    layer = scene.layers.create("Concrete")
    scene.layers.set_hatch(layer.id, "solid")
    proc.run("layer")
    proc.provide_text("Hatch")
    proc.provide_text("Concrete")
    assert proc.request.default == "Solid"


def test_the_layer_command_can_take_a_hatch_back_off_a_layer(env):
    scene, _sel, _hist, _ctx, proc = env
    layer = scene.layers.create("Concrete")
    scene.layers.set_hatch(layer.id, "solid")
    proc.run("layer")
    proc.provide_text("Hatch")
    proc.provide_text("Concrete")
    proc.provide_text("None")
    assert scene.layers.get(layer.id).hatch == ""
