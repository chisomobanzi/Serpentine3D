"""Clips out of the viewport: the turntable."""

from __future__ import annotations

from contextlib import suppress
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


def _story_frame(image, width: int = 1080, height: int = 1920):
    """Fit a window grab into a dark portrait frame without cropping it."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter

    fitted = image.scaled(
        width, height,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation)
    # Window grabs retain the monitor's device-pixel ratio.  QPainter would
    # otherwise interpret the already-scaled pixel dimensions as logical
    # dimensions and draw the UI at half size on a HiDPI display.
    fitted.setDevicePixelRatio(1.0)
    frame = QImage(width, height, QImage.Format.Format_RGB888)
    frame.fill(QColor("#17191d"))
    painter = QPainter(frame)
    try:
        painter.drawImage((width - fitted.width()) // 2,
                          (height - fitted.height()) // 2, fitted)
    finally:
        painter.end()
    return frame


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
    cameras = [turntable_camera(bounds, az, elevation, w / h)
               for az in orbit_azimuths(n, float(vp.camera.azimuth))]
    orbit_distance = max(cam.distance for cam in cameras)
    for k, cam in enumerate(cameras):
        cam.distance = orbit_distance
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


@command("turntableui", mutates=False)
def cmd_turntable_ui(ctx):
    """Record a portrait turntable of the current shot and application UI."""
    from PySide6.QtWidgets import QApplication

    from ..media import encode
    from ..media.turntable import orbit_azimuths

    vp = ctx.viewport
    window = ctx.window
    camera = getattr(vp, "camera", None) if vp is not None else None
    if camera is None or window is None or not hasattr(window, "grab"):
        ctx.echo("UI turntable needs the live application window.")
        return

    seconds = yield NumberReq("Seconds", default=15.0, minimum=0.5)
    out = yield TextReq("Output file (.mp4)", default=_default_out())
    out = os.path.expanduser(out)
    if not out.lower().endswith(".mp4"):
        out += ".mp4"

    fps = 30
    width, height = 1080, 1920
    count = max(1, int(round(float(seconds) * fps)))
    original_target = camera.target.copy() if hasattr(camera.target, "copy") \
        else camera.target
    original_distance = camera.distance
    original_azimuth = camera.azimuth
    original_elevation = camera.elevation
    writer = encode.writer_for(out, width, height, fps)
    writer_closed = False
    app = QApplication.instance()
    try:
        for azimuth in orbit_azimuths(count, float(original_azimuth)):
            camera.azimuth = azimuth
            vp.update()
            window.repaint()
            if app is not None:
                app.processEvents()
            writer.write(_story_frame(window.grab().toImage(), width, height))
        path = writer.close()
        writer_closed = True
    finally:
        try:
            camera.target = original_target
            camera.distance = original_distance
            camera.azimuth = original_azimuth
            camera.elevation = original_elevation
            vp.update()
        finally:
            if not writer_closed:
                # Preserve the capture/encoding error while still releasing
                # an ffmpeg pipe (PNG writers make this a harmless no-op).
                with suppress(Exception):
                    writer.close()

    ctx.echo(f"UI turntable: {path} ({count} frames, {width}x{height}).")
    if isinstance(writer, encode.PngWriter):
        ctx.echo("No ffmpeg on this machine — wrote frames instead. "
                 f"Assemble with: {writer.assembly_hint()}")
