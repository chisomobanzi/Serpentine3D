"""SketchUp files import (issue #42).

SketchUp's own reader is a Windows and Mac SDK, so on Linux nothing could
read a .skp at all. OpenSKP reads the format without it, on every platform,
and is what this import is built on.

A SketchUp model is planar faces, gathered into groups and components that
can be placed many times over. Each group or component placed at the top of
the model arrives as one object, everything nested inside it brought to
where it sits, with its faces joined into a polysurface, and into a solid
where they close, so that push/pull, booleans and fillets work on it as on
anything drawn here. Faces loose at the top of the model arrive as one
object per tag. Tags become layers, with their colours and whether they are
shown, and a material's colour comes across as the object's colour.

The test files are written here, with OpenSKP's own writer, rather than
kept: the sample files that come with it are not ours to ship.
"""

from __future__ import annotations

import math

import pytest

from serpentine3d import fileio
from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene

openskp = pytest.importorskip("openskp")

IN = 25.4                                   # millimetres to the inch


def _box_faces(x0, y0, z0, x1, y1, z1):
    """Six faces of an axis-aligned box, in inches, as SketchUp stores."""
    return [
        [(x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)],
        [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],
        [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],
        [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],
        [(x1, y1, z0), (x0, y1, z0), (x0, y1, z1), (x1, y1, z1)],
        [(x0, y1, z0), (x0, y0, z0), (x0, y0, z1), (x0, y1, z1)],
    ]


@pytest.fixture
def skp(tmp_path):
    """A 10 inch box as a group, tagged Walls and painted Brick; a plank
    component placed twice, the second turned a quarter about Z; and a
    loose face on a hidden Site tag."""
    b = openskp.create()
    brick = b.add_material("Brick", (180, 60, 40, 255))
    walls = b.add_layer("Walls", color=(200, 80, 40))
    site = b.add_layer("Site", color=(60, 160, 60), hidden=True)
    with b.add_component_definition("Plank") as plank:
        for pts in _box_faces(0, 0, 0, 20, 2, 1):
            plank.add_face(pts)
    with b.add_group("Box", material=brick, layer=walls) as box:
        for pts in _box_faces(0, 0, 0, 10, 10, 10):
            box.add_face(pts)
    b.add_instance(plank, name="Plank A", translation=(30.0, 0.0, 0.0))
    b.add_instance(plank, name="Plank B", translation=(30.0, 10.0, 0.0),
                   rotation=((0.0, 0.0, 1.0), math.pi / 2))
    b.add_face([(0, -20, 0), (40, -20, 0), (40, -10, 0), (0, -10, 0)],
               layer=site)
    path = tmp_path / "model.skp"
    b.save(str(path))
    return str(path)


def _by_name(scene):
    return {o.name: o for o in scene.all()}


def _bounds(obj):
    lo, hi = g.bbox(obj.shape)
    return (*lo, *hi)


def test_sketchup_is_offered_on_import():
    assert ".skp" in fileio.IMPORT_EXTS
    assert "*.skp" in fileio.import_filter()


def test_each_placed_group_and_component_is_one_object(skp):
    scene = Scene()

    count = fileio.import_file(scene, skp)

    objs = _by_name(scene)
    assert count == 4
    assert {"Box", "Plank A", "Plank B"} <= set(objs)


def test_a_closed_group_arrives_as_a_solid_at_its_size(skp):
    scene = Scene()
    fileio.import_file(scene, skp)
    box = _by_name(scene)["Box"]

    assert box.kind == "solid"
    assert _bounds(box) == pytest.approx((0, 0, 0, 10 * IN, 10 * IN, 10 * IN),
                                         abs=1e-6)
    assert g.volume(box.shape) == pytest.approx((10 * IN) ** 3, rel=1e-9)


def test_a_component_is_placed_where_each_instance_puts_it(skp):
    scene = Scene()
    fileio.import_file(scene, skp)
    objs = _by_name(scene)

    assert _bounds(objs["Plank A"]) == pytest.approx(
        (30 * IN, 0, 0, 50 * IN, 2 * IN, 1 * IN), abs=1e-6)
    # turned a quarter about Z, then moved to (30, 10): x runs 28..30
    # and y 10..30
    assert _bounds(objs["Plank B"]) == pytest.approx(
        (28 * IN, 10 * IN, 0, 30 * IN, 30 * IN, 1 * IN), abs=1e-6)
    assert objs["Plank B"].kind == "solid"


def test_tags_become_layers_with_their_colour_and_visibility(skp):
    scene = Scene()
    fileio.import_file(scene, skp)
    objs = _by_name(scene)
    walls = scene.layers.get(objs["Box"].layer_id)
    loose = [o for o in scene.all() if o.name not in
             ("Box", "Plank A", "Plank B")]

    assert walls.name == "Walls"
    assert walls.color == pytest.approx((200 / 255, 80 / 255, 40 / 255))
    assert len(loose) == 1
    site = scene.layers.get(loose[0].layer_id)
    assert site.name == "Site"
    assert not site.visible, "a hidden tag arrives as a hidden layer"
    assert _bounds(loose[0]) == pytest.approx(
        (0, -20 * IN, 0, 40 * IN, -10 * IN, 0), abs=1e-6)


def test_untagged_geometry_stays_on_the_default_layer(skp):
    scene = Scene()
    default = scene.layers.current_id
    fileio.import_file(scene, skp)

    assert _by_name(scene)["Plank A"].layer_id in (None, default)


def test_a_material_colour_comes_across(skp):
    scene = Scene()
    fileio.import_file(scene, skp)

    assert _by_name(scene)["Box"].color == pytest.approx(
        (180 / 255, 60 / 255, 40 / 255))


def test_sizes_arrive_in_the_scene_units(skp):
    scene = Scene()
    scene.units = "in"
    fileio.import_file(scene, skp)

    assert _bounds(_by_name(scene)["Box"]) == pytest.approx(
        (0, 0, 0, 10, 10, 10), abs=1e-6)


def test_a_file_it_cannot_read_says_what_to_do_instead(tmp_path):
    bad = tmp_path / "broken.skp"
    bad.write_bytes(b"\xff\xfe\xff\x0e" + b"not really a model" * 20)

    with pytest.raises(Exception) as caught:
        fileio.import_file(Scene(), str(bad))

    said = str(caught.value)
    assert "SketchUp" in said and "OBJ" in said


# --- a group is what it holds -----------------------------------------------
# A SketchUp group often holds more than one body, and stray edges besides.
# Sewn into one shape they made a bundle nothing could push/pull or boolean,
# so each body is an object of its own, solid where it closes, the edges
# are curves beside them, and the lot is grouped so it selects as one.

@pytest.fixture
def mixed(tmp_path):
    b = openskp.create()
    with b.add_group("Pair") as pair:
        for pts in _box_faces(0, 0, 0, 5, 5, 5):
            pair.add_face(pts)
        for pts in _box_faces(10, 0, 0, 15, 5, 5):
            pair.add_face(pts)
        pair.add_polyline([(0, 10, 0), (15, 10, 0), (15, 20, 0)])
    with b.add_group("Flipped", translation=(0.0, 40.0, 0.0)) as flipped:
        # every face wound the wrong way round, as SketchUp models often are
        for pts in _box_faces(0, 0, 0, 5, 5, 5):
            flipped.add_face(list(reversed(pts)))
    path = tmp_path / "mixed.skp"
    b.save(str(path))
    return str(path)


def test_each_body_in_a_group_is_its_own_solid(mixed):
    scene = Scene()
    fileio.import_file(scene, mixed)
    pair = [o for o in scene.all() if o.name == "Pair"]

    assert len(pair) == 2
    assert all(o.kind == "solid" for o in pair)
    assert sorted(round(g.volume(o.shape)) for o in pair) == [
        round((5 * IN) ** 3)] * 2


def test_stray_edges_in_a_group_are_curves_beside_its_solids(mixed):
    scene = Scene()
    fileio.import_file(scene, mixed)
    edges = [o for o in scene.all() if o.name == "Pair edges"]

    assert len(edges) == 1
    assert edges[0].kind == "curve"


def test_what_one_group_made_selects_together(mixed):
    scene = Scene()
    fileio.import_file(scene, mixed)
    made = [o for o in scene.all() if o.name.startswith("Pair")]

    assert len(made) == 3
    assert made[0].group_id is not None
    assert len({o.group_id for o in made}) == 1
    flipped = next(o for o in scene.all() if o.name == "Flipped")
    assert flipped.group_id is None, "one object needs no group"


def test_a_body_wound_inside_out_comes_in_facing_out(mixed):
    scene = Scene()
    fileio.import_file(scene, mixed)
    flipped = next(o for o in scene.all() if o.name == "Flipped")

    assert flipped.kind == "solid"
    assert g.volume(flipped.shape) == pytest.approx((5 * IN) ** 3, rel=1e-9)


def test_an_untagged_group_takes_the_tag_its_faces_are_on(tmp_path):
    """Tags can sit on the faces inside a group rather than on the group,
    and then the faces say where the object belongs."""
    b = openskp.create()
    chair = b.add_layer("Chair", color=(120, 150, 190))
    with b.add_group("Seat") as seat:
        for pts in _box_faces(0, 0, 0, 4, 4, 1):
            seat.add_face(pts, layer=chair)
    path = tmp_path / "tagged_faces.skp"
    b.save(str(path))
    scene = Scene()

    fileio.import_file(scene, str(path))

    seat = _by_name(scene)["Seat"]
    assert scene.layers.get(seat.layer_id).name == "Chair"
