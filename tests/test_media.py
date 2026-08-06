"""The media stack: frames, encoding, the orbit, and the end card.

Everything here is the pure side of video: camera paths, frame sizes,
ffmpeg argv, PNG fallback, caption and end-card compositing. Nothing in
this file touches GL — an offscreen test that calls a viewport draw path
takes the whole run down with it, so the one GL frame function is
exercised through a stub and verified for real in the live app.
"""

import math
import os

import numpy as np
import pytest
from PySide6.QtGui import QImage

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.media import encode, endcard, turntable


def _lum(img):
    """Mean luminance of a QImage, 0..255."""
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    w, h = img.width(), img.height()
    buf = img.constBits().tobytes()
    stride = img.bytesPerLine()
    rows = [np.frombuffer(buf[y * stride:y * stride + w * 3], np.uint8)
            for y in range(h)]
    return float(np.mean(np.stack(rows)))


# -- sizes and the orbit --

def test_every_aspect_comes_out_even_sided():
    assert turntable.size_for("16:9", 1080) == (1920, 1080)
    assert turntable.size_for("9:16", 1920) == (1080, 1920)
    assert turntable.size_for("1:1", 1080) == (1080, 1080)
    # x264 refuses odd dimensions, so an odd request rounds down to even
    w, h = turntable.size_for("16:9", 719)
    assert w % 2 == 0 and h % 2 == 0


def test_an_aspect_name_means_1080p_the_right_way_up():
    assert turntable.default_size("16:9") == (1920, 1080)
    assert turntable.default_size("9:16") == (1080, 1920)
    assert turntable.default_size("1:1") == (1080, 1080)


def test_the_orbit_is_one_full_turn():
    az = turntable.orbit_azimuths(120, start=0.5)
    assert len(az) == 120
    assert az[0] == pytest.approx(0.5)
    # evenly spaced, and the last step returns to the start
    steps = np.diff(az + [az[0] + 2 * math.pi])
    assert np.allclose(steps, steps[0])


def test_the_camera_stands_off_far_enough_to_see_it_all():
    scene = Scene()
    scene.add(g.make_box((-10.0, -10.0, 0.0), 20.0, 20.0, 20.0))
    cam = turntable.turntable_camera(scene.bbox(), azimuth=0.8,
                                     elevation=0.5, aspect=16 / 9)
    assert cam.azimuth == pytest.approx(0.8)
    assert tuple(cam.target) == pytest.approx((0.0, 0.0, 10.0))
    # every corner of the box lands inside the frame
    corners = np.array([[x, y, z] for x in (-10, 10)
                        for y in (-10, 10) for z in (0, 20)], float)
    scr = cam.project(corners, 1920, 1080)
    assert (scr[:, 2] > 0).all()
    assert (scr[:, 0] > 0).all() and (scr[:, 0] < 1920).all()
    assert (scr[:, 1] > 0).all() and (scr[:, 1] < 1080).all()


# -- encoding --

def test_the_ffmpeg_argv_is_what_a_pipe_needs():
    args = encode.ffmpeg_args(1920, 1080, 30, "/tmp/out.mp4")
    joined = " ".join(args)
    assert "1920x1080" in joined
    assert "rawvideo" in joined
    assert "yuv420p" in joined            # plays everywhere, notably phones
    assert args[-1] == "/tmp/out.mp4"


def test_the_png_fallback_writes_numbered_frames(tmp_path):
    w = encode.PngWriter(str(tmp_path / "clip.mp4"), 64, 48)
    img = QImage(64, 48, QImage.Format.Format_RGB888)
    img.fill(0xFF3366)
    for _ in range(3):
        w.write(img)
    out = w.close()
    files = sorted(os.listdir(out))
    assert files == ["frame-0000.png", "frame-0001.png", "frame-0002.png"]


def test_without_ffmpeg_the_writer_falls_back_to_pngs(tmp_path,
                                                      monkeypatch):
    monkeypatch.setattr(encode, "ffmpeg_available", lambda: False)
    w = encode.writer_for(str(tmp_path / "clip.mp4"), 64, 48, 30)
    assert isinstance(w, encode.PngWriter)
    w.close()


# -- the end card --

def test_the_end_card_names_the_tool():
    img = endcard.endcard_frame(640, 360, 1.0)
    assert (img.width(), img.height()) == (640, 360)
    assert _lum(img) > _lum(endcard.endcard_frame(640, 360, 0.0))


def test_the_end_card_fades_in():
    frames = endcard.endcard_frames(320, 180, fps=10, seconds=1.0)
    assert len(frames) == 10
    lums = [_lum(f) for f in frames]
    assert lums[0] < lums[-1]
    assert lums == sorted(lums)


def test_a_caption_lands_on_the_frame():
    from serpentine3d.media.captions import caption
    img = QImage(320, 180, QImage.Format.Format_RGB888)
    img.fill(0x202020)
    before = _lum(img)
    caption(img, "> box", "Created Box 1.")
    assert _lum(img) != before


# -- the replay renderer's pacing, which is pure arithmetic --

def test_the_schedule_compresses_the_pauses():
    from serpentine3d.media.render import frame_schedule
    events = [{"ev": "cmd", "t": 0.0}, {"ev": "val", "t": 10.0},
              {"ev": "fin", "t": 10.1}]
    n = frame_schedule(events, fps=30, speed=10.0)
    assert n[0] == 30                      # 10 s of dithering -> 1 s
    assert n[1] == 0                       # a tenth of a second: same breath
    assert n[2] >= 1                       # the last event holds the shot


def test_a_lunch_break_does_not_become_a_minute_of_video():
    from serpentine3d.media.render import frame_schedule
    events = [{"ev": "cmd", "t": 0.0}, {"ev": "fin", "t": 3600.0}]
    n = frame_schedule(events, fps=30, speed=10.0)
    assert n[0] <= 45                      # capped, not 360 s of nothing


def test_something_made_always_gets_a_frame():
    from serpentine3d.media.render import frame_schedule
    events = [{"ev": "cmd", "t": 0.0}, {"ev": "fin", "t": 0.01},
              {"ev": "edit", "t": 0.02}, {"ev": "cmd", "t": 0.03}]
    n = frame_schedule(events, fps=30, speed=10.0)
    assert n[1] >= 1 and n[2] >= 1


# -- the turntable command, everything but the GL --

def test_the_turntable_command_writes_a_clip(tmp_path, monkeypatch):
    import serpentine3d.commands  # noqa: F401
    from serpentine3d.commands.base import (
        CommandContext, CommandProcessor)
    from serpentine3d.core.history import History
    from serpentine3d.core.selection import SelectionManager
    monkeypatch.setattr(encode, "ffmpeg_available", lambda: False)

    scene = Scene()
    scene.add(g.make_box((0.0, 0.0, 0.0), 10.0, 10.0, 10.0))
    sel = SelectionManager(scene)
    ctx = CommandContext(scene, sel, History(scene))
    rendered = []

    class FakeGL:
        class camera:
            azimuth, elevation = 0.6, 0.5
        config = None

        def render_model_image(self, cam, w, h):
            rendered.append((round(cam.azimuth, 6), w, h))
            img = QImage(w, h, QImage.Format.Format_RGB888)
            img.fill(0x445566)
            return img

    ctx.viewport = FakeGL()
    proc = CommandProcessor(ctx)
    out = str(tmp_path / "spin.mp4")
    proc.run("turntable")
    proc.provide_text("1")                 # seconds
    proc.provide_text("1:1")               # aspect
    proc.provide_text(out)                 # where to put it
    assert not proc.busy
    azs = [r[0] for r in rendered]
    assert len(azs) == 30                  # 1 s at 30 fps
    assert len(set(azs)) == 30             # every frame stands elsewhere
    assert all((w, h) == (1080, 1080) for _, w, h in rendered)
    frames_dir = out[:-4] + "-frames"
    assert len(os.listdir(frames_dir)) == 30


def test_the_turntable_command_needs_something_to_look_at(tmp_path):
    import serpentine3d.commands  # noqa: F401
    from serpentine3d.commands.base import (
        CommandContext, CommandProcessor)
    from serpentine3d.core.history import History
    from serpentine3d.core.selection import SelectionManager
    scene = Scene()
    ctx = CommandContext(scene, SelectionManager(scene), History(scene))
    ctx.viewport = object()
    heard = []
    ctx.add_echo_listener(heard.append)
    proc = CommandProcessor(ctx)
    proc.run("turntable")
    assert not proc.busy
    assert any("empty" in h.lower() or "nothing" in h.lower()
               for h in heard)
