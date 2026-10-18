"""Rhino's Attribute User Text comes in with an object and goes back out.

Asked for on the forum by someone who imported a .3dm and found the keys and
values on every object gone. User text is how a Rhino drawing carries what
the geometry cannot say (a part number, a room, a row in somebody's
schedule), and an importer that drops it loses it for good the first time
the file is saved back.
"""

import subprocess
import sys
import textwrap

import pytest

r3 = pytest.importorskip("rhino3dm")

from serpentine3d.core import geometry as g                   # noqa: E402
from serpentine3d.core.deferred import DeferredShape          # noqa: E402
from serpentine3d.core.scene import Scene                     # noqa: E402
from serpentine3d.fileio import export_file, import_file      # noqa: E402
from serpentine3d.fileio import native, rhino                 # noqa: E402
from serpentine3d.fileio import rhino_parallel as rp          # noqa: E402

DOOR = {"Part": "D-101", "Finish": "Oak",
        "Note": "hung on the left\nclosed by default"}


def _attrs(name, text=None, visible=True):
    attrs = r3.ObjectAttributes()
    attrs.Name = name
    attrs.Visible = visible
    for key, value in (text or {}).items():
        attrs.SetUserString(key, value)
    return attrs


def _box(x):
    return r3.Brep.CreateFromBox(r3.Box(r3.BoundingBox(
        r3.Point3d(x, 0, 0), r3.Point3d(x + 10, 10, 10))))


@pytest.fixture
def tagged(tmp_path):
    """A door with three pairs, a box with none, a tagged line, and a
    tagged box the file keeps hidden."""
    model = r3.File3dm()
    model.Objects.AddBrep(_box(0), _attrs("door", DOOR))
    model.Objects.AddBrep(_box(20), _attrs("plain"))
    model.Objects.AddCurve(
        r3.LineCurve(r3.Point3d(0, 0, 0), r3.Point3d(0, 0, 5)),
        _attrs("rail", {"Length": "5"}))
    model.Objects.AddBrep(_box(40), _attrs("stored", {"Bin": "B7"},
                                           visible=False))
    path = str(tmp_path / "tagged.3dm")
    assert model.Write(path, 8)
    return path


def _opened(path):
    scene = Scene()
    import_file(scene, path)
    return scene


def _named(scene, name):
    return next(o for o in scene.all() if o.name == name)


# ------------------------------------------------------------- coming in

def test_an_imported_object_keeps_its_user_text(tagged):
    assert _named(_opened(tagged), "door").user_text == DOOR


def test_the_pairs_keep_the_order_the_file_gives_them(tagged):
    assert list(_named(_opened(tagged), "door").user_text) == list(DOOR)


def test_an_object_with_none_has_none(tagged):
    assert _named(_opened(tagged), "plain").user_text is None


def test_a_curve_keeps_its_user_text_too(tagged):
    assert _named(_opened(tagged), "rail").user_text == {"Length": "5"}


def test_a_hidden_object_keeps_its_user_text(tagged):
    """A hidden object is read now and converted later (#5). The text is
    the object's, not its geometry's, so it cannot wait for the geometry,
    and showing the object must not lose it."""
    scene = _opened(tagged)
    stored = _named(scene, "stored")
    assert not stored.shape_ready, "the hidden box was meant to be deferred"
    assert stored.user_text == {"Bin": "B7"}
    scene.update(stored.id, visible=True)
    assert scene.get(stored.id).user_text == {"Bin": "B7"}


def test_both_halves_of_a_deferred_object_keep_its_text():
    """An object can convert to two, a sewn solid and the faces that would
    not sew. Eager import gives both the object's attributes, so the
    deferred path must as well."""
    scene = Scene()
    obj = scene.add(DeferredShape(
        lambda: [g.make_box((0, 0, 0), 1, 1, 1),
                 g.make_box((5, 0, 0), 1, 1, 1)], kind="solid"),
        name="Twin")
    scene.update(obj.id, user_text={"Part": "T-1"})
    scene.realise(obj.id)
    assert len(scene.all()) == 2
    assert [o.user_text for o in scene.all()] == [{"Part": "T-1"}] * 2


def test_the_parallel_importer_reads_the_same_text(tagged):
    """A big file converts in other processes; the two paths must agree."""
    serial = {n: m["user_text"] for n, _, m in rhino.import_3dm(tagged)}
    parallel = {n: m["user_text"]
                for n, _, m in rp.import_3dm_parallel(tagged, workers=2)}
    assert parallel == serial
    assert parallel["door"] == DOOR


# ----------------------------------------------------------------- blocks

# Built in an interpreter of its own, as tests/data/make_blocks.py explains:
# rhino3dm has segfaulted writing a block in a process that loaded numpy.
_MAKE_BLOCKS = textwrap.dedent("""
    import sys
    import rhino3dm as r3

    def attrs(name, **text):
        a = r3.ObjectAttributes()
        a.Name = name
        for key, value in text.items():
            a.SetUserString(key, value)
        return a

    def box(x):
        return r3.Brep.CreateFromBox(r3.Box(r3.BoundingBox(
            r3.Point3d(x, 0, 0), r3.Point3d(x + 1, 1, 1))))

    model = r3.File3dm()
    door = model.InstanceDefinitions.Add(
        "door", "", "", "", r3.Point3d(0, 0, 0), (box(0), box(2)),
        (attrs("leaf", Finish="Oak"),
         attrs("handle", Finish="Brass", Maker="Acme")))
    door_id = model.InstanceDefinitions[door].Id
    wall = model.InstanceDefinitions.Add(
        "wall", "", "", "", r3.Point3d(0, 0, 0),
        (r3.InstanceReference(door_id, r3.Transform.Translation(0, 0, 5)),
         box(10)),
        (attrs("doorway", Room="102"), attrs("stud")))
    wall_id = model.InstanceDefinitions[wall].Id
    model.Objects.AddInstanceObject(
        r3.InstanceReference(door_id, r3.Transform.Translation(0, 0, 0)),
        attrs("front door", Room="101", Finish="Walnut"))
    model.Objects.AddInstanceObject(
        r3.InstanceReference(wall_id, r3.Transform.Translation(0, 20, 0)),
        attrs("wall 1", Wall="W1"))
    if not model.Write(sys.argv[1], 8):
        raise SystemExit("could not write the blocks")
""")


@pytest.fixture(scope="module")
def blocks(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("blocks") / "doors.3dm")
    subprocess.run([sys.executable, "-c", _MAKE_BLOCKS, path], check=True)
    return path


def test_a_piece_of_a_block_keeps_its_own_text_and_the_blocks(blocks):
    """Serpentine3D has no blocks, so a placed block comes in as its pieces.
    Each keeps its own user text, the way Rhino's Explode leaves it, and
    takes any key it lacks from the block that placed it: a door's room is
    said once, on the door, and is no less true of its handle."""
    got = {name: meta["user_text"]
           for name, _, meta in rhino.import_3dm(blocks)}
    assert got["front door: leaf"] == {"Room": "101", "Finish": "Oak"}
    assert got["front door: handle"] == {"Room": "101", "Finish": "Brass",
                                         "Maker": "Acme"}


def test_a_block_inside_a_block_passes_its_text_down_too(blocks):
    got = {name: meta["user_text"]
           for name, _, meta in rhino.import_3dm(blocks)}
    assert got["wall 1: leaf"] == {"Wall": "W1", "Room": "102",
                                   "Finish": "Oak"}
    assert got["wall 1: stud"] == {"Wall": "W1"}


def test_the_parallel_importer_gives_a_block_the_same_text(blocks):
    serial = {n: m["user_text"] for n, _, m in rhino.import_3dm(blocks)}
    parallel = {n: m["user_text"]
                for n, _, m in rp.import_3dm_parallel(blocks, workers=2)}
    assert parallel == serial


# ------------------------------------------------------------- the .serp

def test_user_text_survives_a_save(tagged, tmp_path):
    path = str(tmp_path / "kept.serp")
    native.save_scene(_opened(tagged), path)
    back = Scene()
    native.load_scene(back, path)
    assert _named(back, "door").user_text == DOOR
    assert list(_named(back, "door").user_text) == list(DOOR)
    assert _named(back, "plain").user_text is None


def test_importing_a_serp_brings_its_user_text(tagged, tmp_path):
    path = str(tmp_path / "kept.serp")
    native.save_scene(_opened(tagged), path)
    into = Scene()
    into.add(g.make_box((0, 0, 0), 1, 1, 1), name="already here")
    import_file(into, path)
    assert _named(into, "door").user_text == DOOR
    assert _named(into, "already here").user_text is None


def test_a_file_hand_edited_into_nonsense_still_opens(tmp_path):
    """Scripts and assistants write .serp files too. A number where text
    belongs is kept as its text; an empty key or value, which Rhino has no
    way to hold, is left out rather than refused."""
    scene = Scene()
    box = scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="box")
    scene.update(box.id, user_text={"Count": 3, "": "no key",
                                    "Empty": "", "Kept": "yes"})
    path = str(tmp_path / "odd.serp")
    native.save_scene(scene, path)
    back = Scene()
    native.load_scene(back, path)
    assert _named(back, "box").user_text == {"Count": "3", "Kept": "yes"}


def _document(path):
    import json
    import zipfile
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read("document.json"))


def _tagged_scene(kind):
    import numpy as np

    from serpentine3d.core.picture import PictureShape
    from serpentine3d.core.pointcloud import PointCloudShape
    shape = {"box": lambda: g.make_box((0, 0, 0), 1, 1, 1),
             "picture": lambda: PictureShape(dict(
                 origin=[0, 0, 0], u=[10, 0, 0], v=[0, 10, 0],
                 path="reference.png")),
             "cloud": lambda: PointCloudShape(np.eye(3))}[kind]()
    scene = Scene()
    obj = scene.add(shape, name="tagged")
    scene.update(obj.id, user_text=dict(DOOR))
    return scene


@pytest.mark.parametrize("kind", ["box", "picture", "cloud"])
def test_a_file_with_user_text_names_the_release_that_reads_it(
        kind, tmp_path, monkeypatch):
    """A release before user text opens the file, drops every key without a
    word, and a save there loses them for good, so it is told instead,
    as it is about pictures and hatches."""
    path = str(tmp_path / "tagged.serp")
    native.save_scene(_tagged_scene(kind), path)
    doc = _document(path)
    assert doc["version"] == 6
    assert doc["requires"] == "0.13.0"

    monkeypatch.setattr(native, "FORMAT_VERSION", 5)
    existing = Scene()
    box = existing.add(g.make_box((0, 0, 0), 1, 1, 1))
    with pytest.raises(ValueError, match="0.13.0"):
        native.load_scene(existing, path)
    assert existing.get(box.id) is box


def test_a_file_without_user_text_keeps_the_version_it_had(tmp_path):
    """Asking for a newer reader only when the file needs one keeps
    ordinary drawings opening in every release that could open them."""
    scene = Scene()
    scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="plain")
    path = str(tmp_path / "plain.serp")
    native.save_scene(scene, path)
    assert _document(path)["version"] == native.PLAIN_VERSION


# ------------------------------------------------------- going back out

def _written(path):
    model = r3.File3dm.Read(path)
    return {o.Attributes.Name: dict(o.Attributes.GetUserStrings())
            for o in model.Objects}


def test_user_text_goes_back_out_to_rhino(tagged, tmp_path):
    out = str(tmp_path / "back.3dm")
    export_file(_opened(tagged), out)
    written = _written(out)
    assert written["door"] == DOOR
    assert written["rail"] == {"Length": "5"}
    assert written["stored"] == {"Bin": "B7"}
    assert written["plain"] == {}


def test_a_round_trip_through_a_serp_loses_nothing(tagged, tmp_path):
    """Rhino in, Serpentine3D's own file, Rhino out."""
    kept = str(tmp_path / "kept.serp")
    native.save_scene(_opened(tagged), kept)
    scene = Scene()
    native.load_scene(scene, kept)
    out = str(tmp_path / "back.3dm")
    export_file(scene, out)
    assert _written(out)["door"] == DOOR


def test_text_set_here_reaches_rhino(tmp_path):
    scene = Scene()
    box = scene.add(g.make_box((0, 0, 0), 1, 1, 1), name="box")
    scene.update(box.id, user_text={"Room": "204"})
    out = str(tmp_path / "made.3dm")
    export_file(scene, out)
    assert _written(out)["box"] == {"Room": "204"}


# ------------------------------------------------------------ copies

def test_a_copy_carries_the_user_text_and_owns_it():
    """A copy of a tagged door is a tagged door, as it is in Rhino; editing
    one's text must not edit the other's."""
    scene = Scene()
    door = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    door = scene.update(door.id, user_text={"Part": "D-101"})
    copy = scene.add_from(g.make_box((5, 0, 0), 1, 1, 1), door)
    assert copy.user_text == {"Part": "D-101"}
    assert copy.user_text is not door.user_text


def test_the_copy_command_carries_it(env):
    scene, selection, _hist, _ctx, proc = env
    door = scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    scene.update(door.id, user_text={"Part": "D-101"})
    selection.set([door.id])
    proc.run("copy")
    proc.provide_text("0,0,0")
    proc.provide_text("5,0,0")
    proc.provide_text("")
    assert len(scene.all()) == 2
    assert [o.user_text for o in scene.all()] == [{"Part": "D-101"}] * 2
