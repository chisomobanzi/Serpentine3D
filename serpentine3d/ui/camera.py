"""Orbit camera, Z-up (Rhino convention)."""

from __future__ import annotations

import math

import numpy as np

from ..utils.math3d import look_at, normalize, ortho, perspective

Z_UP = np.array([0.0, 0.0, 1.0])


def drag_pans(projection: str, shift: bool) -> bool:
    """Which navigation a nav-button drag performs. A plain drag orbits in
    perspective and pans in a parallel (orthographic) view; Shift inverts
    it. So a Top view drags-to-pan like a drawing, and you can still orbit
    it into an axonometric view with Shift held."""
    return (projection == "parallel") != bool(shift)


# cinema sensor presets: (width, height) in millimetres
SENSORS = {
    "Super35": (24.89, 18.66),
    "FullFrame": (36.0, 24.0),
    "Alexa LF": (36.70, 25.54),
    "Super16": (12.52, 7.42),
    "65mm": (52.48, 23.01),
    "IMAX": (70.41, 52.63),
}


class Camera:
    def __init__(self):
        self.target = np.zeros(3)
        self.distance = 60.0
        self.azimuth = math.radians(-60.0)     # around +Z from +X
        self.elevation = math.radians(30.0)    # from XY plane
        self.fov = 45.0
        self.sensor_name = "Super35"
        self.projection = "perspective"        # or "parallel" (orthographic)

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

    def proj_matrix(self, width: int, height: int) -> np.ndarray:
        aspect = width / max(height, 1)
        if self.projection == "parallel":
            # match the perspective scale at the target plane, so switching
            # projection and zooming (distance) stay visually consistent
            half_h = self.distance * math.tan(math.radians(self.fov) / 2)
            half_w = half_h * aspect
            depth = self.distance * 100.0 + 1000.0   # slab centred on target
            return ortho(-half_w, half_w, -half_h, half_h,
                         self.distance - depth, self.distance + depth)
        near = max(self.distance * 0.001, 0.01)
        far = self.distance * 100.0 + 1000.0
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
        self.distance = max(0.01, min(self.distance, 1e6))

    def zoom_extents(self, bbox: tuple | None):
        if bbox is None:
            self.target = np.zeros(3)
            self.distance = 60.0
            return
        mn, mx = np.asarray(bbox[0], float), np.asarray(bbox[1], float)
        center = (mn + mx) / 2
        radius = float(np.linalg.norm(mx - mn)) / 2
        radius = max(radius, 1.0)
        self.target = center
        self.distance = radius / math.sin(math.radians(self.fov) / 2) * 1.15

    def set_standard_view(self, name: str):
        views = {
            "perspective": (math.radians(-60), math.radians(30)),
            "top": (math.radians(-90), math.radians(89.9)),
            "bottom": (math.radians(-90), math.radians(-89.9)),
            "front": (math.radians(-90), 0.0),
            "back": (math.radians(90), 0.0),
            "right": (0.0, 0.0),
            "left": (math.radians(180), 0.0),
        }
        if name not in views:
            raise ValueError(f"Unknown view '{name}'")
        self.azimuth, self.elevation = views[name]
        # the named axis views are orthographic; only Perspective foreshortens
        self.projection = "perspective" if name == "perspective" else "parallel"

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

    def project(self, points: np.ndarray, width: int,
                height: int) -> np.ndarray:
        """World points (N,3) -> pixel coords + depth (N,3): x_px, y_px, w."""
        n = len(points)
        hom = np.hstack([points, np.ones((n, 1))])
        mvp = self.proj_matrix(width, height) @ self.view_matrix()
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
            fwd = normalize(self.target - self.position)
            out[:, 2] = (np.asarray(points, float) - self.position) @ fwd
        else:
            out[:, 2] = w[:, 0]
        return out
