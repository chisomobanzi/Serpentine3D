"""The orbit: a camera walked once around the work.

Pure arithmetic — sizes, azimuths, and a camera fitted to the bounds —
so every decision about the shot is testable without a GL context. The
one function that touches pixels lives on the viewport.
"""

from __future__ import annotations

import math

_ASPECTS = {"16:9": 16 / 9, "9:16": 9 / 16, "1:1": 1.0}


def size_for(aspect: str, height: int) -> tuple[int, int]:
    """Frame size for an aspect name, both sides even for x264."""
    ratio = _ASPECTS[aspect]
    h = (height // 2) * 2
    w = int(round(h * ratio / 2)) * 2
    return w, h


def default_size(aspect: str) -> tuple[int, int]:
    """The size people mean by an aspect name: 1080p either way up.

    Passing height=1080 to size_for gives a 9:16 frame 608 wide, which
    is the arithmetic being obedient; a reel is 1080 x 1920.
    """
    return {"16:9": (1920, 1080), "9:16": (1080, 1920),
            "1:1": (1080, 1080)}[aspect]


def orbit_azimuths(n: int, start: float = 0.0) -> list[float]:
    """One full counterclockwise turn in n even steps, back to start."""
    return [start + 2 * math.pi * k / n for k in range(n)]


def turntable_camera(bounds, azimuth: float, elevation: float,
                     aspect: float):
    """A camera looking at the middle of `bounds`, backed off to fit.

    A touch more elevation than the working view tends to flatter a
    model, but the caller decides; this only frames.
    """
    from ..ui.camera import Camera
    cam = Camera()
    mn, mx = bounds
    cam.target = [(a + b) / 2 for a, b in zip(mn, mx)]
    cam.azimuth = azimuth
    cam.elevation = elevation
    cam.zoom_extents(bounds, aspect)
    # breathing room: the fit is exact and a rim that grazes the frame
    # edge reads as cramped
    cam.distance *= 1.12
    return cam
