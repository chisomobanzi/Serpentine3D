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
COLOR = (0.24, 0.66, 0.62)          # surface colour (RGB 0-1); app-teal
MATERIAL = {"metallic": 0.45, "roughness": 0.38, "opacity": 1.0}
DISPLAY_MODE = "rendered"           # or "shaded", "ghosted", "wireframe"
# blooming petal vase: lofted profiles whose lobes grow with height —
# circular foot, swelling belly, scalloped seven-petal lip
LOBES = 7
HEIGHT = 32.0
# silhouette: (fraction of height, radius)
SILHOUETTE = [(0.00, 2.6), (0.10, 4.0), (0.28, 5.6), (0.46, 5.4),
              (0.62, 4.0), (0.76, 3.4), (0.88, 4.2), (1.00, 5.8)]
CAM = dict(target=(0, 0, 16), azimuth_deg=-55, elevation_deg=18, distance=66)
# -------------------------------------------------------------------------


def _vase_profile(t, r):
    """Lobed profile at height fraction t: lobes grow from foot to lip."""
    z = t * HEIGHT
    amp = 0.015 + 0.14 * t * t
    pts = []
    n = 96
    for k in range(n):
        a = 2 * math.pi * k / n
        rr = r * (1.0 + amp * math.cos(LOBES * a))
        pts.append((rr * math.cos(a), rr * math.sin(a), z))
    return g.make_interp_curve(pts + [pts[0]])


def build(window):
    scene = window.scene
    vase = g.loft([_vase_profile(t, r) for t, r in SILHOUETTE],
                  solid=False)
    obj = scene.add(vase, name="Vase")
    scene.update(obj.id, color=COLOR, material=dict(MATERIAL))

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
