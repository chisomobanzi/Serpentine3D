"""Black objects must still read as solids in shaded mode.

Shading is multiplicative — `uColor * (ambient + diffuse)` — so an object on a
black layer has nothing left to shade. Against a viewport background that is
itself nearly black it came out as a hole rather than a solid, and the only way
to see the model was to change the layer colour.
"""

from serpentine3d.ui import theme
from serpentine3d.ui import viewport


def _lit(color):
    """Brightest and dimmest a colour gets under the shaded-mode lighting."""
    v = max(color)
    return v, v * theme.SHADED_AMBIENT


def test_a_black_object_is_not_shaded_black():
    fill = theme.shaded_fill((0.0, 0.0, 0.0))
    assert max(fill) > 0.0, "black stays black: nothing to see"


def test_a_black_object_reads_as_a_solid_against_the_background():
    """Visible means two things: brighter than the background overall, and
    with enough range between its lit and unlit sides to show its form."""
    bg = max(max(theme.VIEWPORT_BG_TOP), max(theme.VIEWPORT_BG_BOTTOM))
    lit, unlit = _lit(theme.shaded_fill((0.0, 0.0, 0.0)))

    assert lit >= bg * 2, f"lit side {lit:.3f} barely clears background {bg}"
    assert lit - unlit >= 0.25, f"only {lit - unlit:.3f} of range: no form"


def test_colours_bright_enough_already_are_untouched():
    """The lift exists for dark colours; everything else must render exactly
    as it did before, including saturated hues that are dark in luminance."""
    for c in [(1.0, 1.0, 1.0), (1.0, 0.0, 0.0), (0.0, 0.0, 1.0),
              (0.5, 0.5, 0.5), (0.9, 0.6, 0.1)]:
        assert theme.shaded_fill(c) == c, f"{c} was altered"


def test_a_dark_colour_keeps_its_hue():
    """Lifting must not turn a dark blue layer into a grey one."""
    fill = theme.shaded_fill((0.0, 0.0, 0.25))
    assert fill[2] > fill[0] and fill[2] > fill[1], fill


def test_the_lift_never_leaves_the_valid_range():
    for c in [(0.0, 0.0, 0.0), (0.34, 0.0, 0.0), (0.0, 0.34, 0.34)]:
        fill = theme.shaded_fill(c)
        assert all(0.0 <= x <= 1.0 for x in fill), fill
        assert len(fill) == 3


def test_darker_colours_are_lifted_at_least_as_much():
    """Monotonic, so the lift can't invert which of two greys looks lighter."""
    greys = [i / 20 for i in range(21)]
    fills = [max(theme.shaded_fill((g, g, g))) for g in greys]
    assert fills == sorted(fills), fills


def test_the_shader_still_uses_the_ambient_this_module_assumes():
    """`SHADED_AMBIENT` mirrors a constant hardcoded in the GLSL. If the
    shader's lighting changes, the floor above stops meaning what it says."""
    ambient = theme.SHADED_AMBIENT
    expected = f"uColor * ({ambient:.2f} + {1 - ambient:.2f} * diff)"
    assert expected in viewport.MESH_FRAG, expected
