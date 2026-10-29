"""A point object is drawn as a white disc in a thin black rim.

It was three crossed lines along the world axes, which in a perspective
view read as a snowflake and not as a place. A disc of fixed pixels reads
the same from every side and at every zoom.
"""

from __future__ import annotations

import numpy as np
import pytest

from serpentine3d.core import geometry as g


@pytest.fixture
def window(_qapp):
    from serpentine3d.app import MainWindow
    w = MainWindow()
    w.set_view_layout("single")
    w.resize(900, 700)
    w.show()
    vp = w.viewport
    vp.grabFramebuffer()            # makes the context, where there is one
    if not (vp.isValid() and getattr(vp, "_marker_prog", 0)):
        w.mark_saved()
        w.close()
        pytest.skip("no GL 3.3 to draw with here (CI runs offscreen)")
    yield w, vp
    w.mark_saved()
    w.close()


def _around(image, x, y, reach):
    return [image.pixelColor(x + dx, y + dy)
            for dx in range(-reach, reach + 1)
            for dy in range(-reach, reach + 1)
            if 0 <= x + dx < image.width() and 0 <= y + dy < image.height()]


def test_a_point_draws_white_with_a_dark_rim(window):
    w, vp = window
    w.scene.add(g.make_point((0.0, 0.0, 0.0)), name="pt")
    w.scene.notify()
    vp.set_view("top")
    vp.grid_visible = False
    vp.zoom_extents()

    image = vp.grabFramebuffer()
    ratio = vp.devicePixelRatioF()
    centre = vp.camera.project(np.zeros((1, 3)), vp.width(), vp.height())[0]
    x, y = int(round(centre[0] * ratio)), int(round(centre[1] * ratio))

    middle = image.pixelColor(x, y)
    assert min(middle.red(), middle.green(), middle.blue()) > 230, \
        f"the middle of the point is {middle.name()}, not white"
    ring = _around(image, x, y, int(6 * ratio))
    assert any(max(c.red(), c.green(), c.blue()) < 60 for c in ring), \
        "no dark rim round the point"
