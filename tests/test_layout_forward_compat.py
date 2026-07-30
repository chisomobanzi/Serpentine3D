"""Opening a sheet written by a build that knew more than this one does.

Everything on a sheet was rebuilt from the file with `Cls(**d)`, which means
the file had to name exactly the fields the class has. It never will for
long: a detail gained a section plane, a note gained a style, and the moment
one is added, a drawing saved by the new build stops opening in the old one —
not with a missing section plane, but with a `TypeError` and no drawing at
all. The same in reverse for a field that is ever dropped.

A reader keeps what it understands and lets the rest go. Losing a field you
have no way to draw is a small loss; refusing to open the drawing is a total
one.
"""

from __future__ import annotations

import json

import pytest

from serpentine3d.core.layout import (AngularDim, DetailView, Hatch, Layout,
                                      Leader, LinearDim, RadialDim, TextNote,
                                      layouts_from_json, layouts_to_json)

# every pool on a sheet, with the key a future build might add to it
POOLS = [
    ("details", {"x": 20.0, "y": 30.0, "scale_denom": 2.0}),
    ("notes", {"x": 5.0, "y": 6.0, "text": "SECTION A-A"}),
    ("dims", {"x1": 1.0, "y1": 2.0, "x2": 3.0, "y2": 4.0}),
    ("leaders", {"points": [[0.0, 0.0], [10.0, 10.0]], "text": "typ."}),
    ("hatches", {"points": [[0.0, 0.0], [5.0, 0.0], [5.0, 5.0]],
                 "pattern": "cross"}),
    ("rdims", {"cx": 1.0, "cy": 2.0, "px": 3.0, "py": 4.0}),
    ("adims", {"vx": 1.0, "vy": 2.0, "radius": 20.0}),
]


def _sheet(pool: str, items: list) -> list:
    """One sheet's worth of file, with `pool` holding exactly `items`."""
    doc = layouts_to_json([Layout(name="Sheet1")])
    doc[0][pool] = items
    return doc


def _read_one(pool: str, item: dict, **later):
    """Read back one item written with fields this build may not have."""
    lay, = layouts_from_json(_sheet(pool, [dict(item, **later)]))
    return lay, getattr(lay, pool)


@pytest.mark.parametrize("pool,item", POOLS)
def test_a_field_this_build_has_never_heard_of_still_opens(pool, item):
    _lay, read = _read_one(pool, item, phase_of_moon="waxing")
    assert len(read) == 1


@pytest.mark.parametrize("pool,item", POOLS)
def test_what_this_build_does_understand_survives_it(pool, item):
    """The stray key is dropped, not the fields standing next to it."""
    _lay, read = _read_one(pool, item, phase_of_moon="waxing")
    for key, want in item.items():
        assert getattr(read[0], key) == want


@pytest.mark.parametrize("pool,item", POOLS)
def test_the_stray_key_does_not_stick_to_the_object(pool, item):
    """Or the next save would write back a field this build never drew, and
    say it meant it."""
    lay, read = _read_one(pool, item, phase_of_moon="waxing")
    assert not hasattr(read[0], "phase_of_moon")
    assert "phase_of_moon" not in layouts_to_json([lay])[0][pool][0]


@pytest.mark.parametrize("pool,item", POOLS)
def test_a_field_the_file_is_missing_takes_the_default(pool, item):
    """The other direction: a file older than the field that was added."""
    _lay, read = _read_one(pool, item)
    obj = read[0]
    assert obj.id                      # an id is minted rather than demanded
    assert isinstance(obj.id, str)


def test_one_odd_detail_does_not_cost_you_the_other_details():
    doc = _sheet("details", [
        {"x": 10.0, "y": 10.0},
        {"x": 20.0, "y": 20.0, "cut_list": ["a", "b"]},
        {"x": 30.0, "y": 30.0},
    ])
    lay, = layouts_from_json(doc)
    assert [d.x for d in lay.details] == [10.0, 20.0, 30.0]


def test_a_sheet_written_by_this_build_round_trips_unchanged():
    """The lenient reader must not quietly drop anything current."""
    lay = Layout(name="Sheet1")
    lay.details.append(DetailView(x=20.0, y=30.0, scale_denom=2.0,
                                  target=[1.0, 2.0, 3.0], locked=True,
                                  section_offset=4.0))
    lay.notes.append(TextNote(x=5.0, y=6.0, text="A", style="big"))
    lay.dims.append(LinearDim(x1=1.0, y1=2.0, m1=[0.0, 0.0, 0.0]))
    lay.leaders.append(Leader(points=[[0.0, 0.0]], text="t"))
    lay.hatches.append(Hatch(points=[[0.0, 0.0]], pattern="cross"))
    lay.rdims.append(RadialDim(cx=1.0, diameter=True))
    lay.adims.append(AngularDim(vx=1.0, radius=20.0))
    once = layouts_to_json([lay])
    twice = layouts_to_json(layouts_from_json(json.loads(json.dumps(once))))
    assert twice == once


def test_a_whole_file_from_a_later_build_opens(tmp_path):
    """Through the front door, not just the layout reader."""
    from serpentine3d.core.scene import Scene
    from serpentine3d.fileio import native

    scene = Scene()
    scene.layouts.append(Layout(name="Sheet1"))
    path = str(tmp_path / "later.serp")
    native.save_scene(scene, path)

    import zipfile
    with zipfile.ZipFile(path) as z:
        doc = json.loads(z.read("document.json"))
    doc["layouts"][0]["details"] = [{"x": 15.0, "y": 25.0,
                                     "shadow_softness": 0.3}]
    with open(path, "w") as f:                  # v1 bare JSON still loads
        json.dump(doc, f)

    other = Scene()
    native.load_scene(other, path)
    assert other.layouts[0].details[0].x == 15.0
