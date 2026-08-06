"""The replay renderer: a session journal becomes a timelapse.

Nothing is screen-recorded. The journal is re-executed headless and each
event is rendered fresh through a scripted camera, which is why one
session can come out 9:16 for a reel and 16:9 for a talk without being
modelled twice, and why a fumbled take never appears — the journal only
holds what was actually done.

The camera is nobody's mouse: a slow constant orbit, eased out to fit
the work as it grows. The command line rides the bottom of the frame,
because the recipe being visible is the point.
"""

from __future__ import annotations

import math

from .captions import caption
from .encode import PngWriter, writer_for
from .endcard import endcard_frames
from .turntable import default_size, size_for

# how the recording's pauses become screen time
_MAX_EVENT_GAP = 60.0        # thinking longer than this reads as a break
_MAX_HOLD = 1.5              # seconds of video any one event may hold
_ORBIT_PERIOD = 48.0         # video seconds per full camera turn
_EASE = 0.10                 # how fast the camera settles on new bounds


def frame_schedule(events, fps: int, speed: float) -> list[int]:
    """Frames each event holds: recorded pauses, compressed by `speed`.

    Events that landed in the same breath share a frame; a finished
    command always gets at least one, so nothing appears without a frame
    to appear on.
    """
    out = []
    for i, e in enumerate(events):
        if i + 1 < len(events):
            dt = max(0.0, events[i + 1].get("t", 0.0) - e.get("t", 0.0))
        else:
            dt = _MAX_HOLD * speed
        vdt = min(dt, _MAX_EVENT_GAP) / max(speed, 1e-6)
        n = int(round(min(vdt, _MAX_HOLD) * fps))
        if n == 0 and e.get("ev") in ("fin", "edit", "load"):
            n = 1
        out.append(n)
    return out


class _OrbitCamera:
    """The scripted eye: constant turn, eased fit to what exists."""

    def __init__(self, fps: int, aspect: float):
        from ..ui.camera import Camera
        self.cam = Camera()
        self.aspect = aspect
        self._step = 2 * math.pi / (_ORBIT_PERIOD * fps)
        self.cam.elevation = math.radians(28.0)

    def frame_for(self, bounds):
        import numpy as np
        cam = self.cam
        cam.azimuth += self._step
        if bounds is not None:
            from ..ui.camera import Camera
            want = Camera()
            want.target = np.asarray(
                [(a + b) / 2 for a, b in zip(*bounds)], float)
            want.azimuth, want.elevation = cam.azimuth, cam.elevation
            want.zoom_extents(bounds, self.aspect)
            cam.target = (np.asarray(cam.target, float)
                          + _EASE * (want.target
                                     - np.asarray(cam.target, float)))
            cam.distance += _EASE * (want.distance * 1.15 - cam.distance)
        cam._vp_cache = None
        return cam


def render_replay_video(events, out: str, aspect: str = "16:9",
                        height: int | None = None, fps: int = 30,
                        speed: float = 10.0, endcard: bool = False,
                        captions: bool = True,
                        progress=None) -> str:
    """Re-execute `events` and write the timelapse to `out`."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from ..core.replay import Replayer
    from ..ui.viewport import Viewport

    w, h = (size_for(aspect, height) if height is not None
            else default_size(aspect))
    echoes: list[str] = []
    r = Replayer(events, echo=echoes.append)
    vp = Viewport(r.scene, r.selection)
    vp.resize(640, 480)
    vp.show()                    # realises the GL context
    app.processEvents()

    schedule = frame_schedule(events, fps, speed)
    eye = _OrbitCamera(fps, w / h)
    writer = writer_for(out, w, h, fps)
    last_cmd = ""
    total = 0
    try:
        i = 0
        while i < len(r.events):
            e = r.events[i]
            nxt = r.step(i)
            if e["ev"] == "cmd":
                last_cmd = f"> {e['name']}"
            for _ in range(schedule[i]):
                img = vp.render_model_image(eye.frame_for(r.scene.bbox()),
                                            w, h)
                if img is None:
                    raise RuntimeError(
                        "the viewport could not render a frame "
                        "(no GL on this display?)")
                if captions and last_cmd:
                    caption(img, last_cmd, echoes[-1] if echoes else "")
                writer.write(img)
                total += 1
            if progress is not None and e["ev"] == "fin":
                progress(i + 1, len(r.events))
            i = nxt
        if endcard:
            for frame in endcard_frames(w, h, fps):
                writer.write(frame)
                total += 1
    finally:
        vp.close()
    path = writer.close()
    if isinstance(writer, PngWriter):
        path = f"{path} (no ffmpeg — {writer.assembly_hint()})"
    return path
