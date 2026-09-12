"""Issue #18: typography survives modelling, native files and Undo/Redo."""

import numpy as np
import pytest
from PySide6.QtGui import QFontDatabase

from serpentine3d.core import geometry as g
from serpentine3d.core import text as text_geometry
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.fileio import native


@pytest.fixture
def typography():
    families = set(QFontDatabase.families())
    for family in ("DejaVu Sans", "Liberation Sans", "Arial", "Noto Sans"):
        if family in families:
            styles = QFontDatabase.styles(family)
            regular = next((s for s in styles if s in ("Book", "Regular")), styles[0])
            styled = next((s for s in styles if "Bold" in s), regular)
            return family, regular, styled
    pytest.skip("No installed lettering font")


def _text(typography, **overrides):
    text_type = getattr(text_geometry, "TextShape", None)
    assert text_type is not None, (
        "Model text needs an editable TextShape carrying source typography; "
        "immediately generated outline curves cannot be edited as text")
    family, regular, _ = typography
    values = dict(text="Floor 01\nNorth wing", height=4.5, font_family=family,
                  font_style=regular, alignment="center", origin=(31., -12., 8.))
    values.update(overrides)
    return text_type(**values)


def _outline_signature(curves):
    """Placement and size of each real contour, independent of BREP identity."""
    return sorted(tuple(np.asarray(g.bbox(curve)).ravel()) +
                  (g.curve_length(curve), g.surface_area(g.planar_face(curve)))
                  for curve in curves)


def _same_outlines(actual, expected):
    assert len(actual) == len(expected)
    remaining = _outline_signature(expected)
    for contour in _outline_signature(actual):
        # Equal leading bounds can differ by roundoff after a mirror, so raw
        # lexicographic sorting does not reliably pair the same contours.
        match = next((index for index, candidate in enumerate(remaining)
                      if np.allclose(contour, candidate, atol=1e-5, rtol=1e-6)), None)
        assert match is not None, f"No matching contour for {contour}; remaining: {remaining}"
        np.testing.assert_allclose(contour, remaining.pop(match), atol=1e-5, rtol=1e-6)


def _same_source(actual, expected):
    for field in ("text", "height", "font_family", "font_style", "alignment"):
        assert getattr(actual, field) == getattr(expected, field), field
    np.testing.assert_allclose(actual.origin, expected.origin, atol=1e-8)


def test_model_text_is_one_selectable_object_with_real_display_geometry(typography):
    text = _text(typography)
    scene = Scene()
    obj = scene.add(text, name="Drawing label")
    assert scene.all() == [obj]
    assert scene.selectable_objects() == [obj]
    selection = SelectionManager(scene)
    selection.set([obj.id])
    assert selection.objects() == [obj]
    _same_source(obj.shape, text)

    expected = [g.translate(c, text.origin) for c in text_geometry.text_curves(
        text.text, text.height, text.font_family, font_style=text.font_style,
        alignment=text.alignment)]
    _same_outlines(obj.shape.to_curves(), expected)
    np.testing.assert_allclose(obj.bbox(), g.bbox(g.make_compound(expected)), atol=1e-5)
    mesh = obj.mesh
    assert len(mesh.edge_segments) or len(mesh.triangles), (
        "Editable text must supply geometry for normal rendering and picking")
    assert np.isfinite(np.asarray(mesh.bounds())).all()
    np.testing.assert_allclose(mesh.bounds(), obj.bbox(), atol=0.15)


def test_editing_content_and_typography_keeps_placement_and_rebuilds_display(typography):
    original = _text(typography)
    scene = Scene()
    obj = scene.add(original)
    previous_bounds = obj.bbox()
    previous_mesh = obj.mesh
    family, _, styled = typography
    edited = original.edited(text="REVISED\nDrawing title", height=7.,
                             font_family=family, font_style=styled,
                             alignment="right")
    obj = scene.replace_shape(obj.id, edited)
    assert len(scene.all()) == 1
    assert obj.shape.text == "REVISED\nDrawing title"
    assert obj.shape.height == 7.
    assert obj.shape.font_style == styled
    assert obj.shape.alignment == "right"
    np.testing.assert_allclose(obj.shape.origin, original.origin)
    assert original.text == "Floor 01\nNorth wing", "Edits must preserve prior history states"
    assert original.height == 4.5
    assert not np.allclose(obj.bbox(), previous_bounds)
    assert obj.mesh is not previous_mesh
    np.testing.assert_allclose(obj.mesh.bounds(), obj.bbox(), atol=0.15)


TRANSFORMS = [
    pytest.param(lambda s: g.translate(s, (7., -13., 5.)), id="move"),
    pytest.param(lambda s: g.rotate(s, (2., 1., -3.), (1., 2., 3.), 37.), id="rotate"),
    pytest.param(lambda s: g.scale(s, (-1., 2., 3.), 1.75), id="scale"),
    pytest.param(lambda s: g.scale(s, (2., 3., -1.), 1., factors=(2., .5, 1.)),
                 id="nonuniform-scale"),
    pytest.param(lambda s: g.mirror(s, (4., 3., 2.), (1., 1., 0.)), id="mirror"),
    pytest.param(g.copy_shape, id="copy"),
    pytest.param(lambda s: g.apply_matrix(s, [
        [0., 0., 1., 15.], [1., 0., 0., -7.], [0., 1., 0., 4.], [0., 0., 0., 1.]]),
                 id="cplane-matrix"),
]


@pytest.mark.parametrize("transform", TRANSFORMS)
def test_editing_words_after_a_transform_retains_the_transformed_placement(
        typography, transform):
    source = _text(typography, text="OLD")
    moved = transform(source)
    assert callable(getattr(moved, "edited", None)), (
        "Normal model transforms must retain the source text, not leave anonymous curves")
    assert moved.text == source.text
    expected_origin = g.point_coords(transform(g.make_point(source.origin)))
    np.testing.assert_allclose(moved.origin, expected_origin, atol=1e-8)

    # Editing at the destination should be the same as transforming the new
    # lettering there: changing the words must not discard any rotation,
    # scale, mirror or construction-plane orientation.
    edited_after = moved.edited(text="NEW\nBOR")
    expected = [transform(c) for c in source.edited(text="NEW\nBOR").to_curves()]
    _same_outlines(edited_after.to_curves(), expected)
    np.testing.assert_allclose(edited_after.origin, expected_origin, atol=1e-8)
    assert source.text == moved.text == "OLD"


def _placed_revision(typography):
    shape = _text(typography, text="Level 02\nÉtage 02", alignment="right")
    return g.rotate(g.translate(shape, (9., 5., 3.)),
                    (0., 0., 0.), (1., 0., 0.), 29.)


def test_native_save_load_preserves_source_typography_and_editable_placement(
        typography, tmp_path, monkeypatch):
    source = _placed_revision(typography)
    scene = Scene()
    layer = scene.layers.create("Drawing labels")
    obj = scene.add(source, name="Level heading", layer_id=layer.id)
    scene.update(obj.id, color=(.2, .5, .8), group_id="title-group", locked=True)
    path = str(tmp_path / "Editable lettering.serp")
    native.save_scene(scene, path)
    loaded = Scene()
    expected_contours = source.to_curves()
    with monkeypatch.context() as font_environment:
        font_environment.setattr(text_geometry, "text_curves", _unavailable_font_outlines)
        native.load_scene(loaded, path)
        restored, = loaded.all()
        _same_outlines(restored.shape.to_curves(), expected_contours)
        assert restored.mesh.bounds() is not None
    assert restored.name == "Level heading"
    assert loaded.layers.get(restored.layer_id).name == "Drawing labels"
    assert restored.color == pytest.approx((.2, .5, .8))
    assert restored.group_id == "title-group" and restored.locked
    _same_source(restored.shape, source)
    _same_outlines(restored.shape.to_curves(), source.to_curves())
    edited = restored.shape.edited(text="Changed after reopening", height=6.)
    _same_outlines(edited.to_curves(),
                   source.edited(text="Changed after reopening", height=6.).to_curves())


def _unavailable_font_outlines(*args, **kwargs):
    pytest.fail("Opening saved text must retain its rendered geometry without rebuilding fonts")


def test_shape_byte_roundtrip_used_by_clipboard_keeps_text_editable(typography, monkeypatch):
    source = _placed_revision(typography)
    saved = g.shape_to_bytes(source)
    expected_contours = source.to_curves()
    with monkeypatch.context() as font_environment:
        font_environment.setattr(text_geometry, "text_curves", _unavailable_font_outlines)
        restored = g.shape_from_bytes(saved)
        _same_outlines(restored.to_curves(), expected_contours)
    _same_source(restored, source)
    _same_outlines(restored.to_curves(), source.to_curves())
    copied = g.translate(restored, (25., 0., 0.)).edited(text="Copied label")
    expected = [g.translate(c, (25., 0., 0.))
                for c in source.edited(text="Copied label").to_curves()]
    _same_outlines(copied.to_curves(), expected)
    assert source.text == "Level 02\nÉtage 02"


def test_undo_and_redo_restore_text_content_style_and_rendered_geometry(typography):
    scene = Scene()
    history = History(scene)
    original = _placed_revision(typography)
    obj = scene.add(original)
    original_mesh_bounds = np.asarray(obj.mesh.bounds()).copy()
    history.checkpoint("Edit text")
    revised = original.edited(text="REVISED", height=8., font_style=typography[2])
    scene.replace_shape(obj.id, revised)
    history.undo()
    undone = scene.get(obj.id)
    _same_source(undone.shape, original)
    _same_outlines(undone.shape.to_curves(), original.to_curves())
    np.testing.assert_allclose(undone.mesh.bounds(), original_mesh_bounds, atol=1e-5)
    history.redo()
    redone = scene.get(obj.id)
    _same_source(redone.shape, revised)
    _same_outlines(redone.shape.to_curves(), revised.to_curves())
    assert redone.shape.edited(text="Still editable").text == "Still editable"


def test_explicit_curve_conversion_keeps_independent_letter_counters(typography):
    source = _text(typography, text="BOR", height=10., origin=(20., 7., 3.))
    contours = source.to_curves()
    assert len(contours) == 7, "B has two counters; O and R each have one"
    assert all(g.shape_kind(c) == "curve" and g.is_closed_curve(c)
               and g.is_valid(c) for c in contours)
    assert all(not callable(getattr(c, "edited", None)) for c in contours)
    expected_before = _outline_signature(source.to_curves())
    scene = Scene()
    outputs = [scene.add(c) for c in contours]
    scene.replace_shape(outputs[0].id, g.translate(outputs[0].shape, (0., 0., 20.)))
    assert _outline_signature(source.to_curves()) == expected_before

    solids = g.extrude_profiles(contours, (0., 0., 1.), 2., cap=True)
    assert len(solids) == 3
    assert all(g.shape_kind(s) == "solid" and g.is_valid(s) for s in solids)
    # The solid volumes include only the letter material, not the inner
    # contours' areas. This exercises the same capped extrusion users run.
    ink_area = sum(g.surface_area(region) for region in g.planar_regions(contours))
    assert sum(g.volume(s) for s in solids) == pytest.approx(ink_area * 2., rel=1e-6)


def test_capped_extrusion_of_editable_text_honors_the_letter_counters(typography):
    source = _text(typography, text="BOR", height=10., origin=(20., 7., 3.))
    solids = g.extrude_profiles([source], (0., 0., 1.), 2., cap=True)
    expected = g.extrude_profiles(source.to_curves(), (0., 0., 1.), 2., cap=True)
    assert len(solids) == len(expected) == 3
    assert all(g.shape_kind(s) == "solid" and g.is_valid(s) for s in solids), (
        "Selecting an editable text label for capped extrusion must keep its letter holes")
    assert sorted(g.volume(s) for s in solids) == pytest.approx(
        sorted(g.volume(s) for s in expected), rel=1e-6)
    assert source.edited(text="Editable after extrusion").text == "Editable after extrusion"
