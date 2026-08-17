"""Union two boxes and the seam leaves a face split in two. Merge it back.

Serpentine's booleans are careful with coplanar faces, but a union of two
boxes side by side still hands back a solid with ten faces: each of the
four sides that spanned the seam is two coplanar strips rather than one
face. Rhino's MergeAllCoplanarFaces is the tidy-up, and OCCT's
ShapeUpgrade_UnifySameDomain is exactly it: coplanar neighbours fuse and
the redundant seam edges go with them, so the box reads as a box again
with its six faces.

The volume must not budge. Merging faces is a change of description, not
of the solid, so a merge that moved the volume would be a merge that broke
something.
"""

from __future__ import annotations

import pytest

from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core import geometry as g
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


@pytest.fixture
def env():
    scene = Scene()
    sel = SelectionManager(scene)
    ctx = CommandContext(scene, sel, History(scene))
    return scene, sel, CommandProcessor(ctx)


def _seamed_bar(scene=None):
    """Two 10-cubes glued along x, unioned. Ten faces, volume 2000."""
    bar = g.boolean_union(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0),
                          g.make_box((10.0, 0.0, 0.0), 10.0, 10.0, 10.0))
    return scene.add(bar, name="Bar") if scene is not None else bar


def _solids(scene):
    return [o for o in scene.all() if o.kind == "solid"]


def _merge(proc, obj):
    proc.run("mergeallcoplanarfaces")
    proc.click_object(obj.id)
    proc.finish_selection()


# -- the geometry helper --

def test_a_seam_of_two_coplanar_faces_becomes_one():
    bar = _seamed_bar()
    assert len(g.faces_of(bar)) == 10, "the union should leave a seam"
    merged = g.merge_coplanar_faces(bar)
    assert len(g.faces_of(merged)) == 6


def test_merging_does_not_move_the_volume():
    bar = _seamed_bar()
    merged = g.merge_coplanar_faces(bar)
    assert g.volume(merged) == pytest.approx(2000.0, rel=1e-6)


def test_a_clean_box_has_nothing_to_merge():
    box = g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0)
    assert len(g.faces_of(g.merge_coplanar_faces(box))) == 6


def test_merge_keeps_it_a_solid():
    assert g.shape_kind(g.merge_coplanar_faces(_seamed_bar())) == "solid"


# -- what the command leaves behind --

def test_the_command_merges_the_seam(env):
    scene, _sel, proc = env
    bar = _seamed_bar(scene)
    _merge(proc, bar)
    left = _solids(scene)
    assert len(left) == 1
    assert len(g.faces_of(left[0].shape)) == 6


def test_the_command_preserves_identity_and_volume(env):
    scene, _sel, proc = env
    bar = _seamed_bar(scene)
    bid, name, layer = bar.id, bar.name, bar.layer_id
    _merge(proc, bar)
    left = _solids(scene)
    assert len(left) == 1
    assert (left[0].id, left[0].name, left[0].layer_id) == (bid, name, layer)
    assert g.volume(left[0].shape) == pytest.approx(2000.0, rel=1e-6)


def test_the_command_leaves_a_clean_box_alone(env):
    scene, _sel, proc = env
    box = scene.add(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0), name="Box")
    _merge(proc, box)
    left = _solids(scene)
    assert len(left) == 1
    assert len(g.faces_of(left[0].shape)) == 6
