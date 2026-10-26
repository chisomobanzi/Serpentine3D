"""A DXF comes in looking as it was drawn: colours, lineweights, linetypes
and block references.

Until now every object came in on a layer with no colour of its own and
nothing else: a drawing of black lines on a beige layer and twenty
coloured fills came in all in the default grey, and a block reference did
not come in at all. Each layer now brings its colour, lineweight (as its
print width), linetype and whether it is on; each object its own colour,
lineweight and linetype where it overrides its layer's; a hatch its colour
and background colour. A block reference comes in as the pieces its block
is made of, where the reference puts them and grouped, a piece that leaves
its look to the block (BYBLOCK, or layer 0) taking the reference's.
"""

from __future__ import annotations

import math
import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene

ezdxf = pytest.importorskip("ezdxf")


def _imported(tmp_path, build, name="drawing.dxf"):
    from serpentine3d import fileio
    doc = ezdxf.new("R2010", units=ezdxf.units.MM)
    build(doc)
    path = tmp_path / name
    doc.saveas(path)
    scene = Scene()
    fileio.import_file(scene, str(path))
    return scene


def _named(scene, name):
    return next(la for la in scene.layers.all() if la.name == name)


def _rgb(*c):
    return pytest.approx(tuple(v / 255.0 for v in c), abs=1e-6)


# --- layers -----------------------------------------------------------------

def test_a_layer_brings_its_colour_lineweight_linetype_and_switches(tmp_path):
    def build(doc):
        walls = doc.layers.add("Walls", color=1)
        walls.dxf.lineweight = 50
        walls.dxf.linetype = "DASHED"
        doc.layers.add("Glass", true_color=ezdxf.colors.rgb2int((0, 128, 255)))
        off = doc.layers.add("Off", color=3)
        off.off()
        frozen = doc.layers.add("Frozen", color=4)
        frozen.freeze()
        locked = doc.layers.add("Locked", color=5)
        locked.lock()
        msp = doc.modelspace()
        for layer in ("Walls", "Glass", "Off", "Frozen", "Locked"):
            msp.add_line((0, 0), (1, 0), dxfattribs={"layer": layer})

    scene = _imported(tmp_path, build)
    walls = _named(scene, "Walls")
    assert walls.color == _rgb(255, 0, 0)
    assert walls.print_width == pytest.approx(0.5)
    assert walls.linetype == "Dashed"
    assert _named(scene, "Glass").color == _rgb(0, 128, 255)
    assert not _named(scene, "Off").visible
    assert not _named(scene, "Frozen").visible
    assert _named(scene, "Locked").locked


# --- objects ------------------------------------------------------------------

def test_an_object_brings_what_it_overrides_and_leaves_the_rest(tmp_path):
    def build(doc):
        doc.layers.add("Walls", color=1)
        msp = doc.modelspace()
        msp.add_line((0, 0), (1, 0), dxfattribs={"layer": "Walls"})
        msp.add_line((0, 1), (1, 1), dxfattribs={
            "layer": "Walls", "color": 3, "lineweight": 35,
            "linetype": "CENTER"})
        line = msp.add_line((0, 2), (1, 2), dxfattribs={"layer": "Walls"})
        line.rgb = (12, 34, 56)

    scene = _imported(tmp_path, build)
    plain, own, true = sorted(scene.all(), key=lambda o: o.bbox()[0][1])
    assert plain.color is None and plain.print_width is None
    assert plain.linetype == "ByLayer"
    assert own.color == _rgb(0, 255, 0)
    assert own.print_width == pytest.approx(0.35)
    assert own.linetype == "Center"
    assert true.color == _rgb(12, 34, 56)


@pytest.mark.parametrize("name, kind", [
    ("HIDDEN2", "Hidden"), ("VERDECKTX2", "Hidden"), ("MITTE", "Center"),
    ("PHANTOM2", "Phantom"), ("STRICHPUNKT", "DashDot"), ("DOT", "Dotted"),
    ("ACAD_ISO02W100", None),
])
def test_a_linetype_is_read_by_what_its_name_says(name, kind):
    from serpentine3d.fileio.dxf import _linetype
    assert _linetype(name) == kind


def test_a_hatch_keeps_its_colour_and_background(tmp_path):
    def build(doc):
        doc.layers.add("Fill", color=2)
        msp = doc.modelspace()
        own = msp.add_hatch(dxfattribs={"layer": "Fill"})
        own.set_pattern_fill("ANSI31", color=1, scale=0.5)
        own.paths.add_polyline_path([(0, 0), (4, 0), (4, 4), (0, 4)],
                                    is_closed=True)
        own.bgcolor = (255, 255, 0)
        by_layer = msp.add_hatch(color=256, dxfattribs={"layer": "Fill"})
        by_layer.set_solid_fill(color=256)
        by_layer.paths.add_polyline_path([(10, 0), (14, 0), (14, 4)],
                                         is_closed=True)

    scene = _imported(tmp_path, build)
    own, by_layer = sorted((o for o in scene.all() if o.kind == "hatch"),
                           key=lambda o: o.bbox()[0][0])
    assert own.hatch_style == {"color": "#ff0000", "background": "#ffff00"}
    color, ground = scene.hatch_look_of(own)
    assert color == _rgb(255, 0, 0) and ground == _rgb(255, 255, 0)
    assert by_layer.hatch_style == {"color": "layer"}
    assert scene.hatch_look_of(by_layer)[0] == _rgb(255, 255, 0)


# --- block references ---------------------------------------------------------

def _door(doc):
    """A block of a frame on layer 0 in BYBLOCK colour, a leaf on its own
    red layer, and a filled panel that leaves its look to the block."""
    doc.layers.add("Leaf", color=1)
    door = doc.blocks.new("DOOR")
    door.add_lwpolyline([(0, 0), (1, 0), (1, 2), (0, 2)], close=True,
                        dxfattribs={"layer": "0", "color": 0,
                                    "lineweight": -2})
    door.add_line((0, 0), (1, 2), dxfattribs={"layer": "Leaf"})
    panel = door.add_hatch(color=0, dxfattribs={"layer": "0"})
    panel.set_solid_fill(color=0)
    panel.paths.add_polyline_path([(0.2, 0.2), (0.8, 0.2), (0.8, 1.8)],
                                  is_closed=True)
    return door


def test_a_block_reference_comes_in_as_its_pieces_where_it_puts_them(
        tmp_path):
    def build(doc):
        _door(doc)
        doc.layers.add("Doors", color=5)
        doc.modelspace().add_blockref(
            "DOOR", (10, 20), dxfattribs={"layer": "Doors", "color": 3,
                                           "lineweight": 70, "rotation": 90,
                                           "xscale": 2, "yscale": 2})

    scene = _imported(tmp_path, build)
    pieces = scene.all()
    assert len(pieces) == 3
    assert len({o.group_id for o in pieces}) == 1 and pieces[0].group_id, \
        "one reference is one group, picked with one click"
    assert all(o.name == "DOOR" for o in pieces)
    xs = [p for o in pieces for p in (o.bbox()[0][0], o.bbox()[1][0])]
    ys = [p for o in pieces for p in (o.bbox()[0][1], o.bbox()[1][1])]
    # turned a quarter about (10, 20) and doubled: x from 6 to 10, y 20..22
    assert min(xs) == pytest.approx(6.0) and max(xs) == pytest.approx(10.0)
    assert min(ys) == pytest.approx(20.0) and max(ys) == pytest.approx(22.0)


def test_a_piece_takes_from_the_reference_what_it_leaves_to_the_block(
        tmp_path):
    def build(doc):
        _door(doc)
        doc.layers.add("Doors", color=5)
        doc.modelspace().add_blockref(
            "DOOR", (0, 0), dxfattribs={"layer": "Doors", "color": 3,
                                         "lineweight": 70})

    scene = _imported(tmp_path, build)
    frame = next(o for o in scene.all() if o.kind == "curve"
                 and len(g.edges_of(o.shape)) == 4)
    leaf = next(o for o in scene.all() if o.kind == "curve" and o is not frame)
    panel = next(o for o in scene.all() if o.kind == "hatch")
    # layer 0 and BYBLOCK: the reference's layer, colour and lineweight
    assert scene.layers.get(frame.layer_id).name == "Doors"
    assert frame.color == _rgb(0, 255, 0)
    assert frame.print_width == pytest.approx(0.7)
    # its own layer, and that layer's colour
    assert scene.layers.get(leaf.layer_id).name == "Leaf"
    assert leaf.color is None
    assert panel.hatch_style["color"] == "#00ff00"


def test_a_block_inside_a_block_is_opened_up_too(tmp_path):
    def build(doc):
        _door(doc)
        wall = doc.blocks.new("WALL")
        wall.add_line((0, 0), (5, 0))
        wall.add_blockref("DOOR", (2, 0))
        msp = doc.modelspace()
        msp.add_blockref("WALL", (0, 0))
        msp.add_blockref("WALL", (0, 10))

    scene = _imported(tmp_path, build)
    assert len(scene.all()) == 2 * (1 + 3)
    groups = {o.group_id for o in scene.all()}
    assert len(groups) == 2, "each reference at the top is one group"


def test_a_reference_by_colour_bylayer_gives_its_pieces_its_layer_s_colour(
        tmp_path):
    def build(doc):
        _door(doc)
        doc.layers.add("Doors", color=6)
        doc.modelspace().add_blockref("DOOR", (0, 0),
                                      dxfattribs={"layer": "Doors"})

    scene = _imported(tmp_path, build)
    frame = next(o for o in scene.all()
                 if scene.layers.get(o.layer_id).name == "Doors"
                 and o.kind == "curve")
    assert frame.color == _rgb(255, 0, 255)


# --- what this app writes, it reads back --------------------------------------

def test_colours_and_widths_written_out_come_back(tmp_path):
    from serpentine3d.core import geometry as g
    from serpentine3d.fileio.dxf import export_dxf, import_dxf

    scene = Scene()
    walls = scene.layers.create("Walls", (0.2, 0.4, 0.6))
    scene.layers.set_print_width(walls.id, 0.5)
    line = scene.add(g.make_line((0, 0, 0), (5, 0, 0)), layer_id=walls.id)
    scene.update(line.id, color=(1.0, 0.0, 0.0))
    path = str(tmp_path / "round.dxf")
    export_dxf(scene, path)

    back = Scene()
    import_dxf(back, path)
    walls_back = _named(back, "Walls")
    assert walls_back.color == pytest.approx((0.2, 0.4, 0.6), abs=1 / 255)
    assert walls_back.print_width == pytest.approx(0.5)
    (again,) = back.all()
    assert again.color == pytest.approx((1.0, 0.0, 0.0), abs=1 / 255)


# --- a big drawing --------------------------------------------------------------

def test_an_import_says_how_far_it_has_got(tmp_path):
    from serpentine3d import fileio

    doc = ezdxf.new("R2010", units=ezdxf.units.MM)
    msp = doc.modelspace()
    for i in range(2000):
        msp.add_line((i, 0), (i, 1))
    path = tmp_path / "many.dxf"
    doc.saveas(path)
    seen = []
    fileio.import_file(Scene(), str(path),
                       progress=lambda f, m: seen.append(f) or True)
    assert len(seen) > 5 and seen == sorted(seen)
    assert seen[-1] == pytest.approx(1.0)


def test_an_import_can_be_cancelled(tmp_path):
    from serpentine3d import fileio
    from serpentine3d.fileio.progress import Cancelled

    doc = ezdxf.new("R2010", units=ezdxf.units.MM)
    for i in range(2000):
        doc.modelspace().add_line((i, 0), (i, 1))
    path = tmp_path / "many.dxf"
    doc.saveas(path)
    scene = Scene()
    with pytest.raises(Cancelled):
        fileio.import_file(scene, str(path),
                           progress=lambda f, m: f < 0.5)


def test_an_import_is_one_journal_event_not_a_dump_of_every_shape(tmp_path):
    """A file read in was journalled as an edit of every object in it,
    each one written out as an exact BREP, and a drawing of twenty
    thousand lines held the window up for minutes."""
    import json

    from serpentine3d.commands.base import CommandContext, CommandProcessor
    from serpentine3d.core import geometry as g
    from serpentine3d.core.history import History
    from serpentine3d.core.journal import SessionJournal
    from serpentine3d.core.selection import SelectionManager

    scene = Scene()
    history = History(scene)
    proc = CommandProcessor(CommandContext(scene, SelectionManager(scene),
                                           history))
    journal = SessionJournal(str(tmp_path / "session.jsonl"))
    journal.attach(proc, scene, history)
    history.checkpoint("import")
    with journal.pause():
        for i in range(50):
            scene.add(g.make_line((i, 0, 0), (i, 1, 0)))
        journal.flush()                     # what the quiet timer does
    journal.note_import("lines.dxf")
    journal.flush()
    journal.close()
    with open(tmp_path / "session.jsonl", encoding="utf-8") as fh:
        events = [json.loads(line) for line in fh if line.strip()]
    kinds = [e["ev"] for e in events]
    assert "edit" not in kinds
    (imported,) = [e for e in events if e["ev"] == "import"]
    assert imported["path"] == "lines.dxf" and len(imported["made"]) == 50


def test_an_object_s_own_look_and_a_hatch_s_come_back_too(tmp_path):
    from serpentine3d.core.hatch import HatchShape
    from serpentine3d.fileio.dxf import export_dxf, import_dxf

    scene = Scene()
    line = scene.add(g.make_line((0, 0, 0), (5, 0, 0)))
    scene.update(line.id, print_width=0.35, linetype="Hidden")
    (face,) = g.planar_regions([g.make_polyline(
        [(10, 0, 0), (14, 0, 0), (14, 4, 0), (10, 4, 0)], closed=True)])
    hatch = scene.add(HatchShape(face, "lines", spacing=0.5))
    scene.update(hatch.id, hatch_style={"color": "#cc2200",
                                        "background": "#ffee00"})
    path = str(tmp_path / "own.dxf")
    export_dxf(scene, path)

    back = Scene()
    import_dxf(back, path)
    line_back = next(o for o in back.all() if o.kind == "curve")
    assert line_back.print_width == pytest.approx(0.35)
    assert line_back.linetype == "Hidden"
    hatch_back = next(o for o in back.all() if o.kind == "hatch")
    assert hatch_back.hatch_style == {"color": "#cc2200",
                                      "background": "#ffee00"}


# --- text -----------------------------------------------------------------------

def _texts(scene):
    from serpentine3d.core.text_object import TextShape
    return [o for o in scene.all() if isinstance(o.shape, TextShape)]


def test_text_and_mtext_come_in_as_editable_text(tmp_path):
    def build(doc):
        doc.styles.add("ARIAL", font="arial.ttf")
        doc.layers.add("Notes", color=2)
        msp = doc.modelspace()
        msp.add_text("Kitchen", height=2.5, dxfattribs={
            "layer": "Notes", "style": "ARIAL", "insert": (10, 20)})
        msp.add_mtext("Room 1\PFloor 24 m2", dxfattribs={
            "char_height": 3.0, "insert": (50, 60), "attachment_point": 1,
            "color": 1})

    scene = _imported(tmp_path, build)
    kitchen, room = sorted(_texts(scene), key=lambda o: o.bbox()[0][0])
    assert kitchen.shape.text == "Kitchen"
    assert kitchen.shape.height == pytest.approx(2.5)
    assert kitchen.shape.font_family.lower() == "arial"
    assert scene.layers.get(kitchen.layer_id).name == "Notes"
    lo, _hi = kitchen.bbox()
    assert lo[0] == pytest.approx(10.0, abs=0.5), "starts at its insertion"
    assert room.shape.text == "Room 1\nFloor 24 m2"
    assert room.color == _rgb(255, 0, 0)
    _lo, hi = room.bbox()
    assert hi[1] == pytest.approx(60.0, abs=0.6), "hangs from its top left"


def test_a_text_is_turned_and_anchored_as_the_file_says(tmp_path):
    def build(doc):
        msp = doc.modelspace()
        text = msp.add_text("Turned", height=2.0,
                            dxfattribs={"rotation": 90.0})
        text.set_placement((5, 5), align=ezdxf.enums.TextEntityAlignment
                           .MIDDLE_CENTER)
        msp.add_mtext("Right", dxfattribs={
            "char_height": 2.0, "insert": (40, 0),
            "attachment_point": 9})

    scene = _imported(tmp_path, build)
    turned = next(o for o in _texts(scene) if o.shape.text == "Turned")
    lo, hi = turned.bbox()
    assert (hi[1] - lo[1]) > (hi[0] - lo[0]), "it runs up the page"
    assert (lo[0] + hi[0]) / 2 == pytest.approx(5.0, abs=0.3)
    assert (lo[1] + hi[1]) / 2 == pytest.approx(5.0, abs=0.3)
    right = next(o for o in _texts(scene) if o.shape.text == "Right")
    lo, hi = right.bbox()
    assert hi[0] == pytest.approx(40.0, abs=0.3), "ends at its insertion"
    assert lo[1] == pytest.approx(0.0, abs=0.3), "sits on it"


def test_a_block_s_attributes_come_in_as_its_text(tmp_path):
    def build(doc):
        tag = doc.blocks.new("TAG")
        tag.add_circle((0, 0), 1)
        tag.add_attdef("NUMBER", (2, 0), dxfattribs={"height": 1.0})
        ref = doc.modelspace().add_blockref("TAG", (10, 10))
        ref.add_auto_attribs({"NUMBER": "B07"})

    scene = _imported(tmp_path, build)
    (number,) = _texts(scene)
    assert number.shape.text == "B07"
    assert number.group_id is not None, "it belongs to its block"
    assert number.bbox()[0][0] == pytest.approx(12.0, abs=0.5)


# --- units ----------------------------------------------------------------------

def test_a_drawing_in_metres_comes_in_at_its_real_size(tmp_path):
    from serpentine3d import fileio

    doc = ezdxf.new("R2010", units=ezdxf.units.M)
    msp = doc.modelspace()
    msp.add_line((0, 0), (2.5, 0))
    msp.add_text("1 m", height=0.1, dxfattribs={"insert": (0, 1)})
    path = tmp_path / "metres.dxf"
    doc.saveas(path)

    scene = Scene()                    # millimetres
    notes = []
    fileio.import_file(scene, str(path), notes=notes)
    line = next(o for o in scene.all() if o.kind == "curve"
                and not _texts(scene).count(o))
    lo, hi = line.bbox()
    assert hi[0] - lo[0] == pytest.approx(2500.0)
    (label,) = _texts(scene)
    assert label.shape.height == pytest.approx(100.0)
    assert notes == ["converted from metres to millimetres"]


# --- dimensions -----------------------------------------------------------------

def test_a_linear_dimension_comes_in_as_it_is_drawn(tmp_path):
    from serpentine3d.core.hatch import HatchShape

    def build(doc):
        doc.layers.add("Dims", color=3)
        dim = doc.modelspace().add_linear_dim(
            base=(0, 20), p1=(0, 0), p2=(100, 0),
            dxfattribs={"layer": "Dims"},
            override={"dimtxt": 5.0, "dimasz": 4.0})
        dim.render()

    scene = _imported(tmp_path, build)
    pieces = list(scene.all())
    assert {o.group_id for o in pieces} != {None}
    assert len({o.group_id for o in pieces}) == 1, "one dimension, one group"
    assert all(o.name == "Dimension" for o in pieces)
    assert all(scene.layers.get(o.layer_id).name == "Dims" for o in pieces)
    (label,) = _texts(scene)
    assert label.shape.text == "100"
    assert label.shape.height == pytest.approx(5.0)
    lo, hi = label.bbox()
    assert (lo[0] + hi[0]) / 2 == pytest.approx(50.0, abs=0.5)
    assert (lo[1] + hi[1]) / 2 == pytest.approx(20.0, abs=0.5), \
        "in the gap of its dimension line, as this style has it"
    assert "Defpoints" not in [layer.name for layer in scene.layers.all()]
    arrows = [o for o in pieces if isinstance(o.shape, HatchShape)]
    assert len(arrows) == 2 and all(a.shape.solid for a in arrows)
    lines = [o for o in pieces if o.kind == "curve" and o not in _texts(scene)]
    spans = [o.bbox() for o in lines]
    level = [(lo[0], hi[0]) for lo, hi in spans
             if lo[1] == pytest.approx(20.0) and hi[1] == pytest.approx(20.0)]
    assert len(level) == 2, "the dimension line, either side of its text"
    assert min(a for a, _ in level) == pytest.approx(4.0)   # from the arrows
    assert max(b for _, b in level) == pytest.approx(96.0)


def test_a_turned_dimension_with_ticks_keeps_its_turn(tmp_path):
    def build(doc):
        dim = doc.modelspace().add_linear_dim(
            base=(0, 10), p1=(0, 0), p2=(0, 50), angle=90,
            override={"dimtxt": 2.5, "dimblk": "ARCHTICK"})
        dim.render()

    scene = _imported(tmp_path, build)
    (label,) = _texts(scene)
    assert label.shape.text == "50"
    lo, hi = label.bbox()
    assert (hi[1] - lo[1]) > (hi[0] - lo[0]), "it reads up the page"
    assert len({o.group_id for o in scene.all()}) == 1, \
        "the ticks, blocks themselves, stay in the dimension's group"
    assert len(list(scene.all())) >= 5


def test_a_dimension_written_without_its_drawing_is_drawn(tmp_path):
    def build(doc):
        dim = doc.modelspace().add_linear_dim(
            base=(0, 20), p1=(0, 0), p2=(80, 0))
        dim.render()
        geometry = dim.dimension.dxf.geometry
        dim.dimension.dxf.discard("geometry")
        doc.blocks.delete_block(geometry, safe=False)

    scene = _imported(tmp_path, build)
    (label,) = _texts(scene)
    assert label.shape.text == "80"


# --- curves in their own plane --------------------------------------------------

def test_a_mirrored_arc_and_circle_land_where_they_were_drawn(tmp_path):
    from serpentine3d.core import geometry

    def build(doc):
        msp = doc.modelspace()
        # what AutoCAD writes for a fillet that was mirrored: its plane
        # faces down, so its x runs the other way
        msp.add_arc((-100, 10), 5, 270, 0,
                    dxfattribs={"extrusion": (0, 0, -1)})
        msp.add_circle((-50, 0), 2, dxfattribs={"extrusion": (0, 0, -1)})

    scene = _imported(tmp_path, build)
    arc, circle = sorted(scene.all(), key=lambda o: -o.bbox()[1][0])
    lo, hi = arc.bbox()
    assert lo[0] == pytest.approx(95.0, abs=1e-6)
    assert hi[0] == pytest.approx(100.0, abs=1e-6)
    assert lo[1] == pytest.approx(5.0, abs=1e-6)
    assert hi[1] == pytest.approx(10.0, abs=1e-6)
    assert geometry.curve_length(arc.shape) == pytest.approx(math.pi * 5 / 2)
    lo, hi = circle.bbox()
    assert (lo[0] + hi[0]) / 2 == pytest.approx(50.0, abs=1e-6)


def test_a_filleted_polyline_keeps_its_rounds(tmp_path):
    from serpentine3d.core import geometry
    b = math.tan(math.radians(90) / 4)          # a quarter circle's bulge

    def build(doc):
        msp = doc.modelspace()
        msp.add_lwpolyline([(0, 0, 0), (8, 0, b), (10, 2, 0), (10, 10, 0)],
                           format="xyb")
        msp.add_lwpolyline([(0, 0, 1), (2, 0, 0)], format="xyb",
                           dxfattribs={"layer": "Half"})

    scene = _imported(tmp_path, build)
    (corner,) = [o for o in scene.all()
                 if scene.layers.get(o.layer_id).name != "Half"]
    (half,) = [o for o in scene.all()
               if scene.layers.get(o.layer_id).name == "Half"]
    assert geometry.curve_length(corner.shape) == pytest.approx(
        8 + math.pi + 8, abs=1e-6), "two straights and a round of radius 2"
    lo, hi = corner.bbox()
    assert hi[0] == pytest.approx(10.0, abs=1e-6)
    assert lo[1] == pytest.approx(0.0, abs=1e-6)
    lo, hi = half.bbox()
    assert lo[1] == pytest.approx(-1.0, abs=1e-6) and \
        hi[1] == pytest.approx(0.0, abs=1e-6), "a positive bulge turns anticlockwise, below its chord"


def test_a_mirrored_polyline_lands_where_it_was_drawn(tmp_path):
    def build(doc):
        doc.modelspace().add_lwpolyline(
            [(-10, 0), (-20, 0), (-20, 5)],
            dxfattribs={"extrusion": (0, 0, -1)})

    scene = _imported(tmp_path, build)
    (line,) = scene.all()
    lo, hi = line.bbox()
    assert lo[0] == pytest.approx(10.0, abs=1e-6)
    assert hi[0] == pytest.approx(20.0, abs=1e-6)
