"""The patterns a drawing starts with, and the ones it loads (#92).

Like Rhino, a drawing always has a few patterns: one of each basic form,
and none that is another turned or scaled. `hatchpatterns` loads more from
a .pat file, deletes one that was loaded and purges the loaded ones
nothing uses. Load patterns… in a pattern list keeps what is picked and
switches it to the first pattern the file brought.
"""

from __future__ import annotations

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.hatch import HatchShape
from serpentine3d.core.hatch_patterns import (BUILTIN, BUILTIN_NAMES,
                                              merge_into, parse_pat,
                                              same_pattern)
from serpentine3d.core.layers import DEFAULT_LAYER_ID, section_fill_dict
from serpentine3d.core.layout import HATCH_PATTERNS, Hatch, Layout

PAT = "*ANSI31, Iron\n45, 0,0, 0,.125\n*ZIGZAG\n45, 0,0, 0,.25, .25,-.25\n"


def _square(size=10.0):
    return g.make_polyline([(0, 0, 0), (size, 0, 0), (size, size, 0),
                            (0, size, 0)], closed=True)


def _face():
    (face,) = g.planar_regions([_square()])
    return face


# --- the app's own ------------------------------------------------------------

def test_a_drawing_starts_with_one_of_each_basic_form():
    assert HATCH_PATTERNS == BUILTIN_NAMES == (
        "lines", "cross", "solid", "dash", "dots", "plus", "squares",
        "triangles", "brick")


def test_none_of_the_app_s_own_is_another_turned_or_scaled():
    from serpentine3d.core.hatch_patterns import HatchPattern, PatternLine
    for i, a in enumerate(BUILTIN_NAMES):
        for b in BUILTIN_NAMES[i + 1:]:
            for turn in (0.0, 45.0, 90.0, 180.0):
                turned = HatchPattern("t", "", tuple(
                    PatternLine(ln.angle + turn, ln.origin, ln.offset,
                                ln.dashes) for ln in BUILTIN[a].lines),
                    BUILTIN[a].solid)
                assert not (same_pattern(turned, BUILTIN[b])
                            and not BUILTIN[a].solid), (a, b, turn)


@pytest.mark.parametrize("name", [n for n in BUILTIN_NAMES
                                  if n not in ("lines", "cross", "solid")])
def test_every_one_of_them_hatches_in_the_model(name):
    hatch = HatchShape(_face(), name.capitalize(), spacing=1.0)
    assert hatch.pattern == name
    assert hatch.definition == BUILTIN[name]
    segs = hatch.pattern_segments()
    assert segs and all(-1e-9 <= c <= 10 + 1e-9 for s in segs for p in s
                        for c in p[:2])


def test_they_are_offered_with_the_loaded_ones(env):
    scene, _sel, _hist, _ctx, proc = env
    merge_into(scene.hatch_patterns, parse_pat(PAT))
    outline = scene.add(_square(), name="Outline")
    proc.run("hatch")
    proc.click_object(outline.id)
    proc.finish_selection()

    assert proc.form.fields[0].req.options == [
        "Lines", "Cross", "Solid", "Dash", "Dots", "Plus", "Squares",
        "Triangles", "Brick", "ANSI31", "ZIGZAG"]


def test_a_cut_through_a_layer_set_to_one_is_drawn_with_it():
    from serpentine3d.core.layout import section_drawing
    from serpentine3d.core.scene import Scene
    scene = Scene()
    box = scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    scene.layers.set_hatch(DEFAULT_LAYER_ID, "Brick")
    fill = scene.section_fill_of(scene.get(box.id))
    assert fill.pattern == "brick" and fill.definition == BUILTIN["brick"]
    (_color, segs), = section_drawing(
        [[[(0, 0), (10, 0), (10, 10), (0, 10)]]], 0, 0, 1.0, [fill])[0]
    assert len({round(abs(b[0] - a[0]), 6) for a, b in segs}) > 1, \
        "courses and joints"


def test_a_cap_draws_one_from_its_families():
    from serpentine3d.core.layout import SectionFill
    from serpentine3d.ui import section_caps as caps
    style = caps.cap_style(SectionFill("brick", definition=BUILTIN["brick"]),
                           (1, 1, 1))
    assert style.pattern == caps.FAMILIES and len(style.families) == 2


# --- the command ------------------------------------------------------------

def _loaded(env, tmp_path):
    scene, _sel, _hist, ctx, proc = env
    path = tmp_path / "mine.pat"
    path.write_text(PAT, encoding="utf-8")
    said = []
    ctx.echo = said.append
    proc.run("hatchpatterns Load")
    proc.provide_text(str(path))
    return scene, proc, said


def test_load_says_what_it_brought(env, tmp_path):
    scene, _proc, said = _loaded(env, tmp_path)
    assert list(scene.hatch_patterns) == ["ANSI31", "ZIGZAG"]
    assert scene.loaded_patterns == ["ANSI31", "ZIGZAG"]
    assert any("Loaded 2 hatch patterns" in line for line in said)


def test_delete_takes_a_loaded_pattern_out(env, tmp_path):
    scene, proc, said = _loaded(env, tmp_path)
    scene.layers.set_hatch(DEFAULT_LAYER_ID, "ANSI31")
    lay = Layout(name="Sheet")
    lay.hatches.append(Hatch(points=[[0, 0], [5, 0], [5, 5]],
                             pattern="ANSI31"))
    scene.layouts.append(lay)
    scene.add(HatchShape(_face(), "ANSI31", spacing=1.0,
                         definition=scene.hatch_patterns["ANSI31"]))

    proc.run("hatchpatterns Delete")
    assert proc.request.options == ["ANSI31", "ZIGZAG"]
    proc.provide_text("ANSI31")

    assert list(scene.hatch_patterns) == ["ZIGZAG"]
    assert any("1 layer and 1 sheet hatch named it" in line for line in said)
    assert any("1 hatch in the model keep" in line for line in said)
    assert scene.layers.get(DEFAULT_LAYER_ID).hatch == "ANSI31", \
        "the name stays, and draws as lines until it is loaded again"
    (hatch,) = [o for o in scene.all() if o.kind == "hatch"]
    assert hatch.shape.definition is not None


def test_delete_can_be_undone(env, tmp_path):
    scene, proc, _said = _loaded(env, tmp_path)
    history = env[2]
    proc.run("hatchpatterns Delete")
    proc.provide_text("ZIGZAG")
    history.undo()
    assert "ZIGZAG" in scene.hatch_patterns


def test_the_app_s_own_cannot_be_deleted(env):
    scene, _sel, _hist, ctx, proc = env
    said = []
    ctx.echo = said.append
    proc.run("hatchpatterns Delete")
    assert any("always stay" in line for line in said)
    assert not proc.busy


def test_purge_takes_out_only_what_nothing_uses(env, tmp_path):
    scene, proc, said = _loaded(env, tmp_path)
    box = scene.add(g.make_box((0, 0, 0), 5, 5, 5))
    scene.update(box.id, section_fill=section_fill_dict("ZIGZAG"))

    proc.run("hatchpatterns Purge")

    assert list(scene.hatch_patterns) == ["ZIGZAG"]
    assert any("Purged 1 unused hatch pattern: ANSI31" in line
               for line in said)


def test_loading_keeps_what_was_picked(env, tmp_path):
    scene, sel, _hist, _ctx, proc = env
    held = scene.add(HatchShape(_face(), "lines", spacing=1.0))
    sel.set([held.id])
    path = tmp_path / "mine.pat"
    path.write_text(PAT, encoding="utf-8")

    proc.run("hatchpatterns Load")
    proc.provide_text(str(path))

    assert sel.ids == [held.id]


# --- in the window ----------------------------------------------------------

@pytest.fixture
def window(_qapp, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication

    from serpentine3d.app import MainWindow
    path = tmp_path / "mine.pat"
    path.write_text(PAT, encoding="utf-8")
    w = MainWindow()
    monkeypatch.setattr(w, "_pick_file", lambda **_kw: str(path))
    yield w
    w.mark_saved()
    w.close()
    QApplication.processEvents()


def test_load_patterns_in_a_hatch_s_list_switches_it_to_the_first(window):
    from PySide6.QtWidgets import QApplication

    w = window
    obj = w.scene.add(HatchShape(_face(), "lines", spacing=1.0),
                      name="Hatch")
    w.selection.set([obj.id])
    QApplication.processEvents()
    combo = w.properties.hatch_pattern
    combo.setCurrentIndex(combo.findData("load-patterns"))
    QApplication.processEvents()

    assert "ANSI31" in w.scene.hatch_patterns
    assert w.selection.ids == [obj.id], "the pick was let go"
    assert w.scene.get(obj.id).shape.pattern == "ANSI31"
    assert combo.currentData() == "ANSI31"


def test_a_solid_hatch_is_ghosted_as_strongly_as_lines(window):
    w = window
    w.viewport.set_ghost(HatchShape(_face(), "solid"))
    assert w.viewport._ghost_solid
    w.viewport.set_ghost(HatchShape(_face(), "lines", spacing=1.0))
    assert not w.viewport._ghost_solid


def test_a_solid_on_paper_is_not_see_through():
    from serpentine3d.ui.annot_paint import HATCH_INK, SOLID_FILL
    assert SOLID_FILL.alpha() == 255
    assert SOLID_FILL == HATCH_INK


# --- no edge of its own -------------------------------------------------------

@pytest.mark.parametrize("pattern", ["lines", "brick", "solid"])
def test_a_hatch_draws_its_fill_and_not_its_edge(pattern):
    """As in Rhino and AutoCAD, a hatch's boundary is the curves drawn
    round it; the hatch itself is only its fill."""
    from serpentine3d.core.tessellate import tessellate
    hatch = HatchShape(_face(), pattern, spacing=1.0)
    mesh = tessellate(hatch)
    assert len(mesh.edge_segments) == len(hatch.pattern_segments())
    if pattern == "solid":
        assert mesh.has_faces and not len(mesh.edge_segments)


def test_its_edge_is_still_there_to_snap_to():
    hatch = HatchShape(_face(), "lines", spacing=1.0)
    kinds = {kind for _p, kind in hatch.snap_points()}
    assert {"end", "mid", "center"} <= kinds
    assert hatch.drawn() is not hatch
    edges = g.edges_of(hatch.drawn())
    assert len(edges) == len(hatch.pattern_segments())
