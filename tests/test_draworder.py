"""Draw order — bring-to-front / send-to-back (Rhino parity). TDD on the
command effect, the front-first render sort, and persistence.
"""

from serpentine3d import fileio
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.scripting import Document


def test_bringtofront_raises_draw_order():
    doc = Document()
    doc.add(g.make_circle((0, 0, 0), 5), name="a")
    doc.add(g.make_circle((0, 0, 0), 5), name="b")
    doc.run("bringtofront", ["a", ""])
    assert doc.get("a").draw_order > doc.get("b").draw_order


def test_sendtoback_lowers_draw_order():
    doc = Document()
    doc.add(g.make_circle((0, 0, 0), 5), name="a")
    doc.add(g.make_circle((0, 0, 0), 5), name="b")
    doc.run("sendtoback", ["b", ""])
    assert doc.get("b").draw_order < doc.get("a").draw_order


def test_forward_backward_are_relative():
    doc = Document()
    doc.add(g.make_circle((0, 0, 0), 5), name="a")
    before = doc.get("a").draw_order
    doc.run("bringforward", ["a", ""])
    assert doc.get("a").draw_order == before + 1
    doc.run("sendbackward", ["a", ""])
    doc.run("sendbackward", ["a", ""])
    assert doc.get("a").draw_order == before - 1


def test_render_sort_is_front_first():
    # the viewport draws highest draw_order first (wins the GL_LESS depth tie);
    # replicate that sort here to lock the ordering contract.
    sc = Scene()
    a = sc.add(g.make_circle((0, 0, 0), 5), name="a")
    b = sc.add(g.make_circle((0, 0, 0), 5), name="b")
    sc.update(a.id, draw_order=5)                     # a is on top
    order = sorted(sc.visible_objects(), key=lambda o: -o.draw_order)
    assert order[0].name == "a"                       # front-most drawn first


def test_draw_order_persists_through_serp(tmp_path):
    sc = Scene()
    o = sc.add(g.make_circle((0, 0, 0), 5), name="c")
    sc.update(o.id, draw_order=7)
    p = str(tmp_path / "x.serp")
    fileio.export_file(sc, p)
    sc2 = Scene()
    fileio.import_file(sc2, p)
    assert sc2.find_by_name("c").draw_order == 7
