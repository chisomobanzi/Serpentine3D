"""Where an imported object's colour comes from.

Reported as "Render display mode does not display colors" (#4). Rhino gives an
object its colour from one of four places — its layer, itself, its material, or
the block it sits in — and we read the layer and nothing else. A file that
colours objects individually, or by material as you would for a rendering,
came in one flat layer colour.
"""

import pytest

r3 = pytest.importorskip("rhino3dm")

from serpentine3d.core.scene import Scene                     # noqa: E402
from serpentine3d.fileio import export_file, import_file      # noqa: E402
from serpentine3d.fileio import rhino                         # noqa: E402

RED = (220, 30, 30)          # the layer everything sits on
GREEN = (30, 200, 60)        # an object's own colour
BLUE = (40, 90, 240)         # a material's colour


def _rgb(c):
    return tuple(round(v / 255.0, 4) for v in c[:3])


@pytest.fixture
def coloured(tmp_path):
    """One red layer, and boxes coloured every way Rhino allows."""
    model = r3.File3dm()
    layer = r3.Layer()
    layer.Name = "everything"
    layer.Color = (*RED, 255)
    model.Layers.Add(layer)

    mat = r3.Material()
    mat.Name = "blue plastic"
    mat.DiffuseColor = (*BLUE, 255)
    mat.Transparency = 0.25
    mat.Shine = 191.25                       # three quarters of Rhino's max
    model.Materials.Add(mat)

    def box(i, name, tweak):
        solid = r3.Box(r3.BoundingBox(r3.Point3d(i * 25, 0, 0),
                                      r3.Point3d(i * 25 + 20, 20, 20)))
        attrs = r3.ObjectAttributes()
        attrs.Name = name
        attrs.LayerIndex = 0
        tweak(attrs)
        model.Objects.AddBrep(r3.Brep.CreateFromBox(solid), attrs)

    def by_object(a):
        a.ObjectColor = (*GREEN, 255)
        a.ColorSource = r3.ObjectColorSource.ColorFromObject

    def by_material(a):
        a.MaterialIndex = 0
        a.MaterialSource = r3.ObjectMaterialSource.MaterialFromObject
        a.ColorSource = r3.ObjectColorSource.ColorFromMaterial

    def rendered_only(a):
        """The ordinary Rhino setup: display colour left on the layer, with a

        material assigned for rendering. Shaded shows the layer, Rendered
        shows the material, and the two are meant to differ.
        """
        a.MaterialIndex = 0
        a.MaterialSource = r3.ObjectMaterialSource.MaterialFromObject

    box(0, "by layer", lambda a: None)
    box(1, "by object", by_object)
    box(2, "by material", by_material)
    box(3, "rendered only", rendered_only)

    path = str(tmp_path / "coloured.3dm")
    assert model.Write(path, 8)
    return path


def _by_name(path):
    return {name: meta for name, _, meta in rhino.import_3dm(path)}


# ------------------------------------------------------- the four sources


def test_an_object_that_says_nothing_takes_its_layers_colour(coloured):
    meta = _by_name(coloured)["by layer"]
    assert meta["color"] is None, "no override; the layer decides"
    assert _rgb(RED) == pytest.approx(meta["layer_color"], abs=1e-3)


def test_an_object_keeps_the_colour_it_was_given(coloured):
    """ColorFromObject: the object overrides its layer."""
    meta = _by_name(coloured)["by object"]
    assert meta["color"] == pytest.approx(_rgb(GREEN), abs=1e-3)


def test_a_colour_that_lives_on_the_material_arrives_too(coloured):
    """ColorFromMaterial: the colour is a property of the material, and

    Rendered mode is the one place it was ever going to show."""
    meta = _by_name(coloured)["by material"]
    assert meta["color"] == pytest.approx(_rgb(BLUE), abs=1e-3)


def test_the_material_itself_comes_with_the_object(coloured):
    """Rendered mode already reads opacity, gloss and metal off a material;

    until now no import ever gave it one."""
    material = _by_name(coloured)["by material"]["material"]
    assert material is not None, "the material was dropped"
    assert material["opacity"] == pytest.approx(0.75, abs=1e-3)
    assert material["roughness"] == pytest.approx(0.25, abs=1e-2)


def test_an_object_with_no_material_is_not_given_an_empty_one(coloured):
    assert _by_name(coloured)["by layer"]["material"] is None


# ------------------------------------------------- the colour on the material


def test_a_material_carries_its_own_colour(coloured):
    """An object can display one colour and render another. Rhino keeps both:

    the display colour, from the layer here, and the material's, which is the
    only one Rendered mode shows.
    """
    meta = _by_name(coloured)["rendered only"]
    assert meta["color"] is None, "shaded mode still follows the layer"
    assert meta["material"]["color"] == pytest.approx(_rgb(BLUE), abs=1e-3)


# ------------------------------------------------------- through to the scene


def test_the_colours_reach_the_scene(coloured):
    """The whole point: what the viewport asks for is scene.color_of."""
    scene = Scene()
    import_file(scene, coloured)
    got = {obj.name: scene.color_of(obj) for obj in scene.all()}
    assert got["by layer"] == pytest.approx(_rgb(RED), abs=1e-3)
    assert got["by object"] == pytest.approx(_rgb(GREEN), abs=1e-3)
    assert got["by material"] == pytest.approx(_rgb(BLUE), abs=1e-3)


def test_rendered_mode_shows_the_materials_colour(coloured):
    """The half of #4 the first fix missed: nothing in the file says this

    object's colour comes from its material, and in Rhino the material's
    colour is still what Rendered draws.
    """
    scene = Scene()
    import_file(scene, coloured)
    obj = next(o for o in scene.all() if o.name == "rendered only")
    assert scene.color_of(obj) == pytest.approx(_rgb(RED), abs=1e-3)
    assert scene.render_color_of(obj) == pytest.approx(_rgb(BLUE), abs=1e-3)


def test_an_object_without_a_material_renders_the_colour_it_displays(coloured):
    scene = Scene()
    import_file(scene, coloured)
    obj = next(o for o in scene.all() if o.name == "by layer")
    assert scene.render_color_of(obj) == pytest.approx(_rgb(RED), abs=1e-3)


def test_a_material_colour_survives_being_written_back_out(coloured, tmp_path):
    """Saving has to write the material out, or opening a rendered drawing

    and saving it throws away every colour it renders with.
    """
    scene = Scene()
    import_file(scene, coloured)
    out = str(tmp_path / "round-trip.3dm")
    export_file(scene, out)

    back = Scene()
    import_file(back, out)
    obj = next(o for o in back.all() if o.name == "rendered only")
    assert back.color_of(obj) == pytest.approx(_rgb(RED), abs=1e-2)
    assert back.render_color_of(obj) == pytest.approx(_rgb(BLUE), abs=1e-2)
    assert obj.material["opacity"] == pytest.approx(0.75, abs=1e-2)


def test_a_colour_survives_being_written_back_out(coloured, tmp_path):
    """Now that we read an object's own colour, saving has to keep it, or

    opening a file and saving it flattens every object onto its layer.
    """
    scene = Scene()
    import_file(scene, coloured)
    out = str(tmp_path / "round-trip.3dm")
    export_file(scene, out)

    back = Scene()
    import_file(back, out)
    got = {obj.name: back.color_of(obj) for obj in back.all()}
    assert got["by object"] == pytest.approx(_rgb(GREEN), abs=1e-2)
    assert got["by material"] == pytest.approx(_rgb(BLUE), abs=1e-2)
    assert got["by layer"] == pytest.approx(_rgb(RED), abs=1e-2)


def test_a_transparent_material_reaches_the_scene(coloured):
    scene = Scene()
    import_file(scene, coloured)
    obj = next(o for o in scene.all() if o.name == "by material")
    assert (obj.material or {}).get("opacity") == pytest.approx(0.75, abs=1e-3)
