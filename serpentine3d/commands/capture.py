"""Clips out of the viewport: the turntable."""

from __future__ import annotations

import math
import os
import time

from .base import NumberReq, OptionReq, TextReq, command


def _bounds_of(ctx):
    """What the orbit looks at: the selection if there is one, else all."""
    objs = ctx.selection.objects() or ctx.scene.all()
    boxes = []
    for o in objs:
        try:
            boxes.append(o.bbox())
        except Exception:                                  # noqa: BLE001
            continue
    if not boxes:
        return None
    mn = [min(b[0][k] for b in boxes) for k in range(3)]
    mx = [max(b[1][k] for b in boxes) for k in range(3)]
    if all(abs(a - b) < 1e-9 for a, b in zip(mn, mx)):
        return None
    return tuple(mn), tuple(mx)


def _default_out() -> str:
    videos = os.path.expanduser("~/Videos")
    base = videos if os.path.isdir(videos) else os.path.expanduser("~")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    return os.path.join(base, f"serpentine-turntable-{stamp}.mp4")


@command("turntable", mutates=False)
def cmd_turntable(ctx):
    """Orbit the camera once around the work and write a video clip;
    orbits the selection if there is one, at the pane's own elevation."""
    from ..media import encode, endcard
    from ..media.turntable import default_size, orbit_azimuths, \
        turntable_camera
    bounds = _bounds_of(ctx)
    if bounds is None:
        ctx.echo("The scene is empty — nothing to orbit.")
        return
    vp = ctx.viewport
    if vp is None or not hasattr(vp, "render_model_image"):
        ctx.echo("Turntable needs a live viewport to render through.")
        return

    seconds = yield NumberReq("Seconds", default=8.0, minimum=0.5)
    aspect = yield OptionReq("Aspect", options=["16:9", "9:16", "1:1"],
                             default="16:9")
    out = yield TextReq("Output file (.mp4)", default=_default_out())
    out = os.path.expanduser(out)
    if not out.lower().endswith(".mp4"):
        out += ".mp4"

    fps = 30
    w, h = default_size(aspect)
    n = max(1, int(round(float(seconds) * fps)))
    elevation = min(float(vp.camera.elevation) + math.radians(5),
                    math.radians(60))
    writer = encode.writer_for(out, w, h, fps)
    marks = {int(n * q): f"{int(q * 100)}%" for q in (0.25, 0.5, 0.75)}
    for k, az in enumerate(orbit_azimuths(n, float(vp.camera.azimuth))):
        cam = turntable_camera(bounds, az, elevation, w / h)
        img = vp.render_model_image(cam, w, h)
        if img is None:
            writer.close()
            ctx.echo("Turntable: the viewport could not render a frame.")
            return
        writer.write(img)
        if k in marks:
            ctx.echo(f"Turntable: {marks[k]}…")
    cfg = getattr(vp, "config", None)
    if cfg is not None and bool(cfg.get("media", "endcard", default=False)):
        for frame in endcard.endcard_frames(w, h, fps):
            writer.write(frame)
    path = writer.close()
    ctx.echo(f"Turntable: {path} ({n} frames, {w}x{h}).")
    if isinstance(writer, encode.PngWriter):
        ctx.echo("No ffmpeg on this machine — wrote frames instead. "
                 f"Assemble with: {writer.assembly_hint()}")