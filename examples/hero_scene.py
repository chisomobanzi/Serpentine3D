#!/usr/bin/env python3
"""Build the 'flowing ribbon' hero scene and open Serpentine3D on it.

Run it with the project's venv (GPU-accelerated, nicer lighting than a
headless render):

    cd ~/Developer/Serpentine3D
    .venv/bin/python examples/hero_scene.py

Then, in the app:
  - orbit with the middle mouse button, pan with Shift+middle, zoom on scroll
  - grab the shot: type `vcf` in the command line -> a path -> a crisp PNG
    (or just use your desktop's screenshot tool)

Tweak the CONSTANTS below to restyle it.
"""

import math
import os
import sys

# run from anywhere: put the repo on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
from PySide6.QtWidgets import QApplication

from serpentine3d.app import MainWindow, APP_TITLE
from serpentine3d.ui.viewport import set_default_gl_format
from serpentine3d.ui import theme
from serpentine3d.core import geometry as g

# ---- tweakables ---------------------------------------------------------
# two chained Mobius strips: each is a loft of straight sections that
# rotate a half-turn as they orbit — the second ring's plane is tilted
# (not perpendicular) so both faces read from one camera. Verified
# interlinked with real clearance (BRepExtrema, ~3.8 units).
COLOR_A = (0.24, 0.66, 0.62)        # teal band
COLOR_B = (0.80, 0.60, 0.38)        # gold band
MAT_A = {"metallic": 0.55, "roughness": 0.30, "opacity": 1.0}
MAT_B = {"metallic": 0.75, "roughness": 0.35, "opacity": 1.0}
DISPLAY_MODE = "rendered"           # or "shaded", "ghosted", "wireframe"
RADIUS = 10.0                       # ring radius
WIDTH = 2.8                         # band half-width
SECTIONS = 72
TILT_DEG = 38                       # second ring's plane tilt
CAM = dict(target=(7, 3, 14.8), azimuth_deg=-64, elevation_deg=21,
           distance=68)
# -------------------------------------------------------------------------


def _mobius(center, u, v, n):
    """Mobius band: loft of line sections with a half-twist."""
    center = np.asarray(center, float)
    u, v, n = (np.asarray(a, float) for a in (u, v, n))
    secs = []
    for k in range(SECTIONS + 1):
        th = 2 * math.pi * k / SECTIONS
        radial = math.cos(th) * u + math.sin(th) * v
        c, s = math.cos(th / 2), math.sin(th / 2)
        d = c * radial + s * n
        mid = center + RADIUS * radial
        secs.append(g.make_line(tuple(mid - WIDTH * d),
                                tuple(mid + WIDTH * d)))
    return g.loft(secs, solid=False)


def _pose(shape):
    shape = g.rotate(shape, (6, 0, 0), (0, 0, 1), -20)
    return g.translate(shape, (0, 0, RADIUS + WIDTH + 4.0))


def build(window):
    scene = window.scene
    tilt = math.radians(TILT_DEG)
    a = _mobius((0, 0, 0), (1, 0, 0), (0, 0, 1), (0, 1, 0))
    b = _mobius((RADIUS * 1.18, 0, 0), (1, 0, 0),
                (0, math.cos(tilt), math.sin(tilt)),
                (0, -math.sin(tilt), math.cos(tilt)))
    oa = scene.add(_pose(a), name="Mobius A")
    scene.update(oa.id, color=COLOR_A, material=dict(MAT_A))
    ob = scene.add(_pose(b), name="Mobius B")
    scene.update(ob.id, color=COLOR_B, material=dict(MAT_B))

    vp = window.viewport
    window.selection.clear()
    vp.set_display_mode(DISPLAY_MODE)
    vp.grid_visible = True
    vp.camera.target = np.array(CAM["target"], float)
    vp.camera.azimuth = math.radians(CAM["azimuth_deg"])
    vp.camera.elevation = math.radians(CAM["elevation_deg"])
    vp.camera.distance = CAM["distance"]
    vp.update()


def main():
    set_default_gl_format()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setStyleSheet(theme.QSS)
    app.setDesktopFileName("serpentine3d")
    window = MainWindow()
    build(window)
    window.showMaximized()
    window.command_line.echo(
        "Hero scene loaded. Orbit with the middle mouse; type 'vcf' to "
        "save a PNG of this view.")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
