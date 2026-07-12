"""Camera and lens controls for previz-style framing."""

import math

import numpy as np

from .base import NumberReq, OptionReq, PointReq, command

ASPECTS = {
    "2.39": 2.39, "1.85": 1.85, "16:9": 16 / 9, "4:3": 4 / 3,
    "Off": None,
}


@command("camera", aliases=("cam",), mutates=False)
def cmd_camera(ctx):
    vp = ctx.viewport
    cam = vp.camera
    action = yield OptionReq(
        f"Camera ({cam.focal_length:.0f}mm on {cam.sensor_name})",
        options=["Lens", "Sensor", "Place", "Frame"], default="Lens")

    if action == "Lens":
        mm = yield NumberReq("Focal length (mm)",
                             default=round(cam.focal_length, 1),
                             minimum=1.0)
        cam.set_focal_length(mm)
        vp.update()
        ctx.echo(f"Lens: {mm:g}mm on {cam.sensor_name} "
                 f"(vertical fov {cam.fov:.1f}°).")

    elif action == "Sensor":
        from ..ui.camera import SENSORS
        keep_focal = cam.focal_length
        choice = yield OptionReq("Sensor / film back",
                                 options=list(SENSORS),
                                 default=cam.sensor_name)
        cam.sensor_name = choice
        cam.set_focal_length(keep_focal)      # same glass, new sensor
        vp.update()
        w, h = cam.sensor
        ctx.echo(f"Sensor: {choice} ({w:g}x{h:g}mm), "
                 f"still {keep_focal:.0f}mm.")

    elif action == "Place":
        eye = yield PointReq("Camera position")
        target = yield PointReq("Camera target", rubber_from=eye)
        direction = np.subtract(eye, target)
        dist = float(np.linalg.norm(direction))
        if dist < 1e-9:
            ctx.echo("Camera and target coincide.")
            return
        d = direction / dist
        cam.target = np.asarray(target, float)
        cam.distance = dist
        cam.azimuth = math.atan2(d[1], d[0])
        cam.elevation = math.asin(float(np.clip(d[2], -1, 1)))
        vp.update()
        ctx.echo(f"Camera placed at {tuple(round(c, 2) for c in eye)} "
                 f"looking at {tuple(round(c, 2) for c in target)} "
                 f"({cam.focal_length:.0f}mm).")

    elif action == "Frame":
        choice = yield OptionReq("Frame guide aspect",
                                 options=list(ASPECTS), default="2.39")
        vp.frame_aspect = ASPECTS[choice]
        vp.update()
        if vp.frame_aspect:
            ctx.echo(f"Frame guides on: {choice} "
                     "(area outside the frame is dimmed).")
        else:
            ctx.echo("Frame guides off.")
