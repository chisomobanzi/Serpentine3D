"""Orbit camera, Z-up (Rhino convention)."""

from __future__ import annotations

import math

import numpy as np

from ..utils.math3d import look_at, normalize, ortho, perspective

Z_UP = np.array([0.0, 0.0, 1.0])


def drag_pans(projection: str, shift: bool, ctrl: bool = False) -> bool:
    """Which navigation a nav-button drag performs. A plain drag orbits in
    perspective and pans in a parallel (orthographic) view, so a Top view
    drags-to-pan like a drawing. Ctrl orbits from anywhere, and is the only
    way to swing an ortho view round: Shift used to do it, but Shift is held
    for so much else while you draw that Top kept turning into an
    axonometric view by accident. Shift pans, wherever you are."""
    if ctrl:
        return False
    return projection == "parallel" or bool(shift)


# cinema sensor presets: (width, height) in millimetres
SENSORS = {
    "Super35": (24.89, 18.66),
    "FullFrame": (36.0, 24.0),
    "Alexa LF": (36.70, 25.54),
    "Super16": (12.52, 7.42),
    "65mm": (52.48, 23.01),
    "IMAX": (70.41, 52.63),
}


# (azimuth, elevation) for each view you can ask for by name. Detail views on
# a layout read the same table, so a name means the same angle wherever it is
# used — see commands/drafting.py.
STANDARD_VIEWS = {
    "perspective": (math.radians(-60), math.radians(30)),
    "top": (math.radians(-90), math.radians(89.9)),
    "bottom": (math.radians(-90), math.radians(-89.9)),
    "front": (math.radians(-90), 0.0),
    "back": (math.radians(90), 0.0),
    "right": (0.0, 0.0),
    "left": (math.radians(180), 0.0),
    # Halfway between front and right, tilted by the one angle that
    # foreshortens all three axes equally: atan(1/sqrt(2)), about 35.26
    # degrees. That is what makes it isometric rather than just a corner
    # view — the three edges at the near corner of a cube come out the same
    # length and 120 degrees apart, so you can measure along all of them.
    "isometric": (math.radians(-45), math.atan(1.0 / math.sqrt(2.0))),
}


def projection_for(name: str) -> str:
    """The named axis views are orthographic; only Perspective foreshortens."""
    return "perspective" if name == "perspective" else "parallel"


# How far a swipe has to travel before it counts as one, in pixels. Small
# enough to feel like a flick, big enough that a click with a shaky hand
# does not throw the view somewhere.
SWIPE_MIN_PX = 12.0

# Which named view stands on which axis, as (positive, negative) per column
# of the eye direction. Read off STANDARD_VIEWS: front is azimuth -90, so
# the eye is out at -Y and looking back at the model.
_AXIS_NAMES = (("right", "left"), ("back", "front"), ("top", "bottom"))


def axis_view_after_swipe(azimuth: float, elevation: float,
                          dx_px: float, dy_px: float,
                          threshold: float = SWIPE_MIN_PX) -> str | None:
    """Which axis view a swipe from this pose lands on, or None if too short.

    A quarter turn the way the drag went, then whichever axis is nearest.
    The turn is about the camera's own up and right rather than about world
    Z, so a sideways swipe still goes somewhere from a Top view, where the
    world axis would be the one you are looking straight down.

    The direction follows `orbit`, which the mouse has already taught: drag
    right and the model turns right, so you end up on its left side.
    """
    if max(abs(dx_px), abs(dy_px)) < threshold:
        return None

    ce = math.cos(elevation)
    eye = np.array([ce * math.cos(azimuth), ce * math.sin(azimuth),
                    math.sin(elevation)])
    fwd = -eye
    cross = np.cross(fwd, Z_UP)
    if np.linalg.norm(cross) < 1e-6:
        right = np.array([-math.sin(azimuth), math.cos(azimuth), 0.0])
    else:
        right = normalize(cross)
    up = np.cross(right, fwd)

    if abs(dx_px) >= abs(dy_px):
        axis, angle = up, -math.copysign(math.pi / 2, dx_px)
    else:
        axis, angle = right, -math.copysign(math.pi / 2, dy_px)

    # Rodrigues, for the one rotation in this file that is not a matrix.
    c, s = math.cos(angle), math.sin(angle)
    turned = (eye * c + np.cross(axis, eye) * s
              + axis * float(np.dot(axis, eye)) * (1.0 - c))

    i = int(np.argmax(np.abs(turned)))
    return _AXIS_NAMES[i][0 if turned[i] >= 0 else 1]


def pose_between(start: tuple[float, float], end: tuple[float, float],
                 t: float) -> tuple[float, float]:
    """(azimuth, elevation) a fraction `t` of the way from one to the other.

    The pair, rather than the eye direction, because azimuth is also what a
    Top view is rolled to: coming to Top from Right there is a quarter turn
    of roll to make up, and spreading it over the flight arrives with the
    plan the right way up instead of popping it round at the end.

    Azimuth goes the short way, which is the way you swiped: a swipe turns
    ninety degrees plus at most forty-five of snap, so the long way round is
    never the way you came. Exactly half a turn apart there is no shorter
    way and no gesture to follow, so it picks one and is consistent.
    """
    az0, el0 = start
    az1, el1 = end
    turn = (az1 - az0 + math.pi) % (2.0 * math.pi) - math.pi
    return az0 + turn * t, el0 + (el1 - el0) * t


def eased(t: float) -> float:
    """Away quickly, into the view gently. It is the easing rather than the
    motion that reads as a turn rather than a lurch."""
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


class Camera:
    def __init__(self):
        self.target = np.zeros(3)
        self.distance = 60.0
        self.azimuth = math.radians(-60.0)     # around +Z from +X
        self.elevation = math.radians(30.0)    # from XY plane
        self.fov = 45.0
        self.sensor_name = "Super35"
        self.projection = "perspective"        # or "parallel" (orthographic)
        self.scene_bounds = None               # ((x,y,z),(x,y,z)); clip_planes
        self._vp_cache = None                  # see _view_proj

    @property
    def sensor(self) -> tuple[float, float]:
        return SENSORS.get(self.sensor_name, SENSORS["Super35"])

    @property
    def focal_length(self) -> float:
        """Lens focal length (mm) equivalent to the current vertical fov."""
        h = self.sensor[1]
        return h / (2.0 * math.tan(math.radians(self.fov) / 2))

    def set_focal_length(self, mm: float):
        h = self.sensor[1]
        self.fov = math.degrees(2.0 * math.atan(h / (2.0 * float(mm))))

    # -- pose ---------------------------------------------------------------

    @property
    def position(self) -> np.ndarray:
        ce = math.cos(self.elevation)
        direction = np.array([
            ce * math.cos(self.azimuth),
            ce * math.sin(self.azimuth),
            math.sin(self.elevation),
        ])
        return self.target + direction * self.distance

    def view_matrix(self) -> np.ndarray:
        # near the poles the Z up vector degenerates; lean on azimuth
        if abs(math.cos(self.elevation)) < 1e-3:
            sign = 1.0 if math.sin(self.elevation) > 0 else -1.0
            up = np.array([-math.cos(self.azimuth) * sign,
                           -math.sin(self.azimuth) * sign, 0.0])
        else:
            up = Z_UP
        return look_at(self.position, self.target, up)

    def clip_planes(self) -> tuple[float, float]:
        """Near and far planes wrapped around the scene, not the zoom.

        They were derived from `distance` alone — near floored at an absolute
        0.01 and far at `distance * 100 + 1000` — which reads as sensible
        until someone zooms in on a small detail of a big model: `distance`
        shrinks, the far plane collapses to a bubble around the detail, and
        the rest of the model vanishes (GitHub #5, "exclusion" through the
        translator). The viewport keeps `scene_bounds` current; with it the
        far plane reaches the farthest corner wherever the camera stands,
        and the near plane scales with the zoom instead of stopping at a
        floor a millimetre-scale detail can never fit inside. The old
        arithmetic stays as the fallback for a camera no one told about a
        scene.
        """
        d = self.distance
        if self.scene_bounds is None:
            if self.projection == "parallel":
                depth = d * 100.0 + 1000.0
                return d - depth, d + depth
            return max(d * 0.001, 0.01), d * 100.0 + 1000.0

        mn, mx = (np.asarray(self.scene_bounds[0], float),
                  np.asarray(self.scene_bounds[1], float))
        corners = np.array([(x, y, z)
                            for x in (mn[0], mx[0])
                            for y in (mn[1], mx[1])
                            for z in (mn[2], mx[2])])
        eye = self.position

        if self.projection == "parallel":
            # Depth along the view direction; negative is fine in ortho, a
            # corner behind the eye plane still projects.
            fwd = normalize(self.target - eye)
            depths = (corners - eye) @ fwd
            span = float(depths.max() - depths.min())
            pad = max(span * 0.05, d * 0.05, 1.0)
            return float(depths.min()) - pad, float(depths.max()) + pad

        # Euclidean distance bounds depth along any forward, so the plane
        # holds however the camera turns about its target.
        farthest = float(np.linalg.norm(corners - eye, axis=1).max())
        far = max(farthest * 1.05, d * 1.05, 1e-3)
        # Proportional to the zoom, but never so deep a ratio that the
        # depth buffer runs out of teeth across the scene.
        near = max(d * 0.001, far * 1e-6)
        return near, far

    def proj_matrix(self, width: int, height: int) -> np.ndarray:
        aspect = width / max(height, 1)
        near, far = self.clip_planes()
        if self.projection == "parallel":
            # match the perspective scale at the target plane, so switching
            # projection and zooming (distance) stay visually consistent
            half_h = self.distance * math.tan(math.radians(self.fov) / 2)
            half_w = half_h * aspect
            return ortho(-half_w, half_w, -half_h, half_h, near, far)
        return perspective(self.fov, aspect, near, far)

    def right_up(self) -> tuple[np.ndarray, np.ndarray]:
        fwd = normalize(self.target - self.position)
        cross = np.cross(fwd, Z_UP)
        if np.linalg.norm(cross) < 1e-6:
            # looking along Z: limit of cross(fwd, Z) as elevation -> pole
            right = np.array([-math.sin(self.azimuth),
                              math.cos(self.azimuth), 0.0])
        else:
            right = normalize(cross)
        up = np.cross(right, fwd)
        return right, up

    # -- interaction ----------------------------------------------------------

    def orbit(self, dx_px: float, dy_px: float):
        self.azimuth -= dx_px * 0.008
        self.elevation += dy_px * 0.008
        limit = math.radians(89.9)
        self.elevation = max(-limit, min(limit, self.elevation))

    def pan(self, dx_px: float, dy_px: float, viewport_h: int):
        right, up = self.right_up()
        scale = 2.0 * self.distance * math.tan(math.radians(self.fov) / 2)
        per_px = scale / max(viewport_h, 1)
        self.target += (-dx_px * right + dy_px * up) * per_px

    def zoom(self, steps: float):
        self.distance *= math.pow(0.88, steps)
        # The floor is numerical, not ergonomic: 0.01 stopped a
        # millimetre-scale detail from ever filling the frame (GitHub #5).
        self.distance = max(1e-6, min(self.distance, 1e9))

    def zoom_extents(self, bbox: tuple | None, aspect: float = 1.0):
        """Pull back until the box just fills the frame.

        It used to frame the sphere around the box in the vertical field of
        view, then back off another 15%. All three parts of that gave away
        room: the sphere around a box is half its diagonal where the box on
        screen is only about half its height, the window is wider than it is
        tall so the sides went unused, and the 15% came on top of both. A
        wide flat model — a set, a floor plan, most of what anyone zooms to —
        came back filling under half the frame in each direction, so a
        quarter of the picture.

        So measure the box instead of a sphere around it: put the eight
        corners on the camera's own axes and take the distance at which the
        outermost one lands on the edge, sideways and up-down separately.
        `aspect` is the window's width over its height; the default of 1
        assumes a square window, which only ever leaves room spare.
        """
        if bbox is None:
            self.target = np.zeros(3)
            self.distance = 60.0
            return
        mn, mx = np.asarray(bbox[0], float), np.asarray(bbox[1], float)
        self.target = (mn + mx) / 2
        half = (mx - mn) / 2

        # A hair inside the edge, so the outermost face is not sitting on the
        # boundary pixel and clipped by rounding.
        t = math.tan(math.radians(self.fov) / 2) / 1.03
        t_side = t * max(float(aspect), 1e-3)

        # A point, or something else with no size: nothing to fill the frame
        # with, so stand off as if it were a unit sphere. Measured against
        # where it is rather than against zero — a single vertex comes back
        # as a box a ten-millionth wide, and out at survey coordinates the
        # slack in a bounding box is bigger still.
        if not np.any(half > 1e-6 * max(1.0, float(np.abs(self.target).max()))):
            self.distance = 1.0 / math.sin(math.radians(self.fov) / 2)
            return

        signs = np.array([(x, y, z) for x in (-1, 1)
                          for y in (-1, 1) for z in (-1, 1)], float)
        pts = signs * half
        right, up = self.right_up()
        fwd = normalize(self.target - self.position)   # away from the eye
        across, high, deep = pts @ right, pts @ up, pts @ fwd

        if self.projection == "parallel":
            # No foreshortening, so depth does not enter it — the frame is
            # distance x tan(fov/2) either side, by proj_matrix.
            dist = max(np.abs(high).max() / t, np.abs(across).max() / t_side)
        else:
            # A corner sits on the edge when its offset equals its depth
            # times the tangent; a near corner therefore needs more room
            # than a far one, hence subtracting its depth.
            dist = max((np.abs(high) / t - deep).max(),
                       (np.abs(across) / t_side - deep).max())
        self.distance = max(float(dist), 1e-3)

    def set_standard_view(self, name: str):
        if name not in STANDARD_VIEWS:
            raise ValueError(f"Unknown view '{name}'")
        self.azimuth, self.elevation = STANDARD_VIEWS[name]
        self.projection = projection_for(name)

    # -- picking ----------------------------------------------------------------

    def ray_through(self, px: float, py: float, width: int,
                    height: int) -> tuple[np.ndarray, np.ndarray]:
        """World-space ray (origin, direction) through a pixel."""
        x_ndc = (2.0 * px / max(width, 1)) - 1.0
        y_ndc = 1.0 - (2.0 * py / max(height, 1))
        aspect = width / max(height, 1)
        fwd = normalize(self.target - self.position)
        right, up = self.right_up()
        if self.projection == "parallel":
            # parallel rays: shared direction, origin spread over the view plane
            half_h = self.distance * math.tan(math.radians(self.fov) / 2)
            origin = (self.position + right * (x_ndc * half_h * aspect)
                      + up * (y_ndc * half_h))
            return origin, fwd
        tan_f = math.tan(math.radians(self.fov) / 2)
        direction = normalize(
            fwd + right * (x_ndc * tan_f * aspect) + up * (y_ndc * tan_f))
        return self.position.copy(), direction

    def _view_proj(self, width: int, height: int) -> tuple:
        """Cached (view-projection, position, forward) for the current pose.

        Picking projects every object's bounds to the screen to decide what
        the ray need not be tested against, so this is asked for once per
        object — thousands of times between two camera moves, for the same
        answer. Rebuilding it each time meant two `np.cross` calls per
        object inside `look_at`, which is where the click time went.

        The key is read straight off the pose rather than bumped by a
        setter, so it cannot outlive a move it did not hear about: every
        field here is public and callers do assign to them directly.
        """
        bounds = self.scene_bounds
        key = (width, height, self.projection, self.fov, self.distance,
               self.azimuth, self.elevation, tuple(self.target),
               None if bounds is None else (tuple(bounds[0]),
                                            tuple(bounds[1])))
        cached = self._vp_cache
        if cached is None or cached[0] != key:
            pos = self.position
            cached = (key,
                      self.proj_matrix(width, height) @ self.view_matrix(),
                      pos, normalize(self.target - pos))
            self._vp_cache = cached
        return cached[1], cached[2], cached[3]

    def project(self, points: np.ndarray, width: int,
                height: int, clipped: bool = True) -> np.ndarray:
        """World points (N,3) -> pixel coords + depth (N,3): x_px, y_px, w.

        `clipped` is nothing to a camera, which shows the whole window; it is
        here because a detail is asked the same question and does have an edge
        to fall off, and both have to answer the same call.
        """
        n = len(points)
        hom = np.hstack([points, np.ones((n, 1))])
        mvp, pos, fwd = self._view_proj(width, height)
        clip = hom @ mvp.T
        w = clip[:, 3:4]
        w_safe = np.where(np.abs(w) < 1e-9, 1e-9, w)
        ndc = clip[:, :3] / w_safe
        out = np.empty((n, 3))
        out[:, 0] = (ndc[:, 0] + 1) * 0.5 * width
        out[:, 1] = (1 - ndc[:, 1]) * 0.5 * height
        if self.projection == "parallel":
            # w is a constant 1 in parallel projection, so the "in front of
            # camera" sign must come from the forward distance instead
            out[:, 2] = (np.asarray(points, float) - pos) @ fwd
        else:
            out[:, 2] = w[:, 0]
        return out
