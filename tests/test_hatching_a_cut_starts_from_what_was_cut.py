"""Region mode opens on the material of the face you clicked.

A section cut already draws itself in the fill of the layer it was cut
from. Dropping a real hatch into that face is how a cut face stops being
a picture and becomes something on the sheet, and it would be a strange
drawing where doing so changed what the face is made of. So the prompt
comes up on the material under the pointer, and falls back to the layer
being drawn on only when the click landed on linework that is no cut.
"""

from __future__ import annotations

from types import SimpleNamespace

from serpentine3d.commands import drafting
from serpentine3d.core.layers import DEFAULT_LAYER_ID
from serpentine3d.core.layout import DetailView, Layout
from tests.conftest import StubViewport


SQUARE = [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0),
          (-10.0, -10.0)]
HOLE = [(-4.0, -4.0), (4.0, -4.0), (4.0, 4.0), (-4.0, 4.0), (-4.0, -4.0)]
FAR = [(20.0, -10.0), (40.0, -10.0), (40.0, 10.0), (20.0, 10.0),
       (20.0, -10.0)]


def _view(monkeypatch, cut, patterns, visible):
    """A detail that has been cut, and knows what it cut."""
    data = {"visible": list(visible), "hidden": [], "cut": list(cut),
            "cut_by_obj": [(i, p, r) for i, (p, r)
                           in enumerate(zip(patterns, cut))]}
    view = SimpleNamespace(_detail_hlr=lambda d: data)
    monkeypatch.setattr(drafting, "_layout_view", lambda ctx: view)


def _layout(monkeypatch, *, cut=(), patterns=(), visible=()):
    """A layout with one 1:1 detail in the middle of the sheet."""
    lay = Layout()
    lay.details.append(DetailView(x=0.0, y=0.0, w=100.0, h=100.0,
                                  scale_denom=1.0))
    _view(monkeypatch, cut, patterns, visible)
    return lay


# -- what the click picks up ----------------------------------------------

def test_a_click_on_a_cut_face_brings_its_material_with_it(monkeypatch):
    lay = _layout(monkeypatch, cut=[[SQUARE, HOLE]], patterns=["cross"])
    _points, _holes, pattern = drafting._region_at(None, lay, 57.0, 50.0)
    assert pattern == "cross"


def test_the_material_follows_the_face_and_not_the_first_one(monkeypatch):
    """Two cuts in one detail are two materials, told apart by the click."""
    lay = _layout(monkeypatch, cut=[[SQUARE], [FAR]],
                  patterns=["cross", "solid"])
    assert drafting._region_at(None, lay, 55.0, 50.0)[2] == "cross"
    assert drafting._region_at(None, lay, 80.0, 50.0)[2] == "solid"


def test_a_cut_whose_layer_says_nothing_asks_for_nothing(monkeypatch):
    lay = _layout(monkeypatch, cut=[[SQUARE, HOLE]], patterns=[""])
    assert drafting._region_at(None, lay, 57.0, 50.0)[2] == ""


def test_linework_that_is_not_a_cut_has_no_material_to_offer(monkeypatch):
    """Ordinary edges are a shape, not a section through anything."""
    lay = _layout(monkeypatch, visible=[SQUARE])
    assert drafting._region_at(None, lay, 50.0, 50.0)[2] == ""


# -- and what the prompt does with it -------------------------------------

def _paper(env, monkeypatch, **kwargs):
    """The hatch command, on a sheet with that detail on it."""
    scene, _sel, _hist, ctx, proc = env
    lay = _layout(monkeypatch, **kwargs)
    scene.layouts.append(lay)
    ctx.viewport = StubViewport(lay.id)
    return scene, lay, proc


def _click(proc, at="57,50"):
    """Region mode, one click, leaving the Pattern prompt up."""
    proc.run("hatch")
    proc.provide_text("Mode=Region")
    proc.provide_text(at)


def test_the_prompt_opens_on_the_material_that_was_cut(env, monkeypatch):
    scene, _lay, proc = _paper(env, monkeypatch, cut=[[SQUARE, HOLE]],
                               patterns=["solid"])
    scene.layers.set_hatch(DEFAULT_LAYER_ID, "cross")
    _click(proc)
    assert proc.request.default == "Solid", \
        "the cut face is steel and the prompt offered the layer's concrete"


def test_a_click_on_plain_linework_still_opens_on_the_layer(env,
                                                            monkeypatch):
    scene, _lay, proc = _paper(env, monkeypatch, visible=[SQUARE])
    scene.layers.set_hatch(DEFAULT_LAYER_ID, "cross")
    _click(proc, "50,50")
    assert proc.request.default == "Cross"


def test_a_cut_from_a_layer_with_nothing_to_say_falls_back(env, monkeypatch):
    scene, _lay, proc = _paper(env, monkeypatch, cut=[[SQUARE, HOLE]],
                               patterns=[""])
    scene.layers.set_hatch(DEFAULT_LAYER_ID, "cross")
    _click(proc)
    assert proc.request.default == "Cross"


def test_the_material_is_offered_and_not_imposed(env, monkeypatch):
    """It is still a prompt: the one face in something else gets it."""
    _scene, lay, proc = _paper(env, monkeypatch, cut=[[SQUARE, HOLE]],
                               patterns=["solid"])
    _click(proc)
    proc.provide_text("Cross")
    assert lay.hatches[0].pattern == "cross"


def test_pressing_enter_takes_the_material_that_was_cut(env, monkeypatch):
    _scene, lay, proc = _paper(env, monkeypatch, cut=[[SQUARE, HOLE]],
                               patterns=["solid"])
    _click(proc)
    proc.provide_text("")
    assert lay.hatches[0].pattern == "solid"
    assert len(lay.hatches[0].holes) == 1, "the bore came out filled in"
