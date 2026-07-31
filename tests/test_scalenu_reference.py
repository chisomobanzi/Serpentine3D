"""`scalenu` by pointing at it, not only by typing three ratios.

Every other scale command lets you grab a reference point and drag it to
where it should end up, and shows you the result while you do. scalenu
asked for three numbers and showed you nothing until it was over — which
is the one scale where the numbers are hardest to work out in your head,
because there are three of them and each is about a different direction.

The two reference points say the same thing per axis: how far the point
started from the base, and how far it should end up. An axis the
reference point does not move along has no reference length, so nothing
about it is being asked, and it is left alone.
"""

from __future__ import annotations

import json

import pytest

from serpentine3d.core import geometry as g


@pytest.fixture
def window(tmp_path, monkeypatch):
    cfg = tmp_path / "cfg.json"
    cfg.write_text(json.dumps({}))
    monkeypatch.setenv("SERP3D_CONFIG", str(cfg))
    monkeypatch.setenv("SERP3D_AUTOSAVE_DIR", str(tmp_path / "autosave"))
    from serpentine3d.app import MainWindow
    w = MainWindow()
    yield w
    w._saved_revision = w.scene.revision
    w.close()


def _box(window):
    obj = window.scene.add(g.make_box((0, 0, 0), 10, 20, 40))
    window.selection.set([obj.id])
    return obj


def _size(window, obj):
    """Bounding size, to within the slack OCC leaves around a box."""
    lo, hi = g.bbox(window.scene.get(obj.id).shape)
    return pytest.approx([float(h - lo_) for lo_, h in zip(lo, hi)],
                         abs=1e-4)


def _start(window, *answers):
    """Run scalenu on a box and answer up to the request under test."""
    obj = _box(window)
    window.processor.run("scalenu")
    for a in answers:
        window.processor.provide_text(a)
    return obj


def test_the_first_prompt_takes_a_point_now(window):
    from serpentine3d.commands.base import PointReq
    _start(window, "0,0,0")
    req = window.processor.request
    assert isinstance(req, PointReq)
    assert req.allow_number                    # typing a factor still works
    assert "reference point" in req.prompt.lower()


def test_two_reference_points_scale_each_axis_by_its_own_ratio(window):
    obj = _start(window, "0,0,0", "10,5,0")
    window.processor.provide_text("20,20,0")   # x doubles, y quadruples
    assert not window.processor.busy
    assert _size(window, obj) == [20, 80, 40]


def test_an_axis_the_reference_does_not_move_along_is_left_alone(window):
    """No reference length, so nothing was asked about it."""
    obj = _start(window, "0,0,0", "10,0,0")
    window.processor.provide_text("20,0,0")
    assert _size(window, obj) == [20, 20, 40]   # y and z untouched


def test_the_second_point_previews_while_you_drag(window):
    _start(window, "0,0,0", "10,0,0")
    req = window.processor.request
    assert req.preview_fn is not None
    window._ghost_timer = None
    window._on_mouse_world((20.0, 0.0, 0.0))
    assert window.viewport._ghost is not None


def test_the_band_hangs_off_the_base_point(window):
    """It measures the same thing the factors do — from the base."""
    _start(window, "0,0,0", "10,0,0")
    assert window.processor.request.rubber_from == (0, 0, 0)


def test_typing_a_factor_still_asks_for_the_other_two(window):
    obj = _start(window, "0,0,0", "2")
    assert "Y factor" in window.processor.prompt_text()
    window.processor.provide_text("3")
    assert "Z factor" in window.processor.prompt_text()
    window.processor.provide_text("0.5")
    assert not window.processor.busy
    assert _size(window, obj) == [20, 60, 20]


def test_the_typed_factors_preview_as_you_type(window):
    """The other half of the same complaint: three numbers and no picture
    of what they do until the command is over."""
    _start(window, "0,0,0")
    assert window.processor.preview_shape("2") is not None   # X factor
    window.processor.provide_text("2")
    assert window.processor.preview_shape("3") is not None   # Y factor
    window.processor.provide_text("3")
    assert window.processor.preview_shape("0.5") is not None  # Z factor


def test_a_reference_point_on_the_base_is_no_reference_at_all(window):
    obj = _start(window, "0,0,0")
    window.processor.provide_text("0,0,0")
    assert not window.processor.busy
    assert _size(window, obj) == [10, 20, 40]


def test_collapsing_the_reference_onto_the_base_is_refused(window):
    """Every factor would be zero, and the objects would stop existing."""
    obj = _start(window, "0,0,0", "10,20,40")
    window.processor.provide_text("0,0,0")
    assert not window.processor.busy
    assert _size(window, obj) == [10, 20, 40]
