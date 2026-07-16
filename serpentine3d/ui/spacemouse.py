"""3Dconnexion SpaceMouse navigation.

Two sources, no third-party dependencies:

1. **spacenavd** (preferred): speaks the FreeSpacenav daemon's socket
   protocol directly (``/var/run/spnav.sock``, override with the
   ``SPNAV_SOCKET`` env var). Display-server agnostic — works on X11
   and Wayland — and inherits the daemon's calibration and deadzones.
2. **evdev fallback**: reads the kernel input device straight from
   ``/dev/input/eventN`` (found via ``/proc/bus/input/devices``) using
   only the stdlib. Needs read access to the device node (usually the
   ``input`` group).

Mapping (turntable camera — the app has no roll):
  - slide left/right  -> pan X
  - lift up/down      -> pan Y
  - push/pull         -> zoom (push forward = zoom in)
  - tilt (pitch)      -> orbit elevation
  - twist (yaw)       -> orbit azimuth
  - roll              -> ignored
Buttons run commands (config ``spacemouse.buttons``; defaults:
0 = zoomextents, 1 = perspective). In a paper layout, slide pans the
sheet and push/pull zooms it.
"""

from __future__ import annotations

import os
import socket
import struct
import time

from PySide6.QtCore import QObject, QSocketNotifier, QTimer

SPNAV_SOCKET = os.environ.get("SPNAV_SOCKET", "/var/run/spnav.sock")

# spacenavd wire protocol: fixed 32-byte packets of 8 native int32s.
# type 0 = motion: x, y, z, rx, ry, rz, period(ms)
# type 1 = button press, type 2 = button release: data[0] = button no.
_EVENT = struct.Struct("iiiiiiii")
_FULL = 350.0                    # nominal full deflection from spacenavd

# per-event gains at sensitivity 1.0 and full deflection
_PAN_PX = 9.0
_ORBIT_PX = 7.0
_ZOOM_STEPS = 0.22


class SpaceMouseNavigator(QObject):
    """Owns the event source and drives the active viewport's camera."""

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.cfg = window.cfg
        self.sock = None
        self._notifier = None
        self._buf = b""
        self.source = None            # "spacenavd" | "evdev" | None
        self.diag_until = 0.0
        self._diag_last = 0.0
        # quiet retry so plugging in later just works
        self._retry = QTimer(self)
        self._retry.setInterval(5000)
        self._retry.timeout.connect(self._connect)
        self._connect()
        if self.source is None:
            self._retry.start()

    # ------------------------------------------------------------ wiring

    def _connect(self):
        if self.source is not None:
            return
        fd = None
        if os.path.exists(SPNAV_SOCKET):
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(SPNAV_SOCKET)
                s.setblocking(False)
                self.sock = s
                fd = s.fileno()
                self.source = "spacenavd"
            except OSError:
                self.sock = None
        if fd is None:
            fd = self._open_evdev()
            if fd is not None:
                self.source = "evdev"
        if fd is None:
            return
        self._retry.stop()
        self._notifier = QSocketNotifier(fd, QSocketNotifier.Type.Read,
                                         self)
        self._notifier.activated.connect(self._read)

    def _open_evdev(self):
        try:
            with open("/proc/bus/input/devices") as f:
                block_name, node = "", None
                for line in f:
                    if line.startswith("N: Name="):
                        block_name = line.lower()
                    elif line.startswith("H: Handlers=") and (
                            "3dconnexion" in block_name
                            or "spacemouse" in block_name
                            or "spacenavigator" in block_name):
                        for tok in line.split("=", 1)[1].split():
                            if tok.startswith("event"):
                                node = "/dev/input/" + tok
                        if node:
                            break
            if node is None:
                return None
            self._evdev_fd = os.open(node, os.O_RDONLY | os.O_NONBLOCK)
            return self._evdev_fd
        except OSError:
            return None

    def attach_socket(self, sock):
        """Test hook: drive the navigator from an existing socket."""
        self._retry.stop()
        self.sock = sock
        sock.setblocking(False)
        self.source = "spacenavd"
        self._notifier = QSocketNotifier(sock.fileno(),
                                         QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._read)

    def status(self) -> str:
        if self.source is None:
            return ("no SpaceMouse source — is spacenavd running? "
                    f"(looked for {SPNAV_SOCKET} and /dev/input)")
        return f"connected via {self.source}"

    # ------------------------------------------------------------ events

    def _read(self):
        if self.source == "spacenavd":
            try:
                while True:
                    chunk = self.sock.recv(4096)
                    if not chunk:
                        self._disconnect()
                        return
                    self._buf += chunk
            except BlockingIOError:
                pass
            except OSError:
                self._disconnect()
                return
            motion = [0.0] * 6
            buttons = []
            while len(self._buf) >= 32:
                ev = _EVENT.unpack(self._buf[:32])
                self._buf = self._buf[32:]
                if ev[0] == 0:
                    for i in range(6):
                        motion[i] += ev[1 + i]
                elif ev[0] in (1, 2):
                    buttons.append((ev[1], ev[0] == 1))
            self._apply(motion, buttons)
        else:
            self._read_evdev()

    def _read_evdev(self):
        # struct input_event on 64-bit: 2 longs (timeval) + H type +
        # H code + i value = 24 bytes; raw axes span roughly +-500
        motion = [0.0] * 6
        buttons = []
        try:
            while True:
                data = os.read(self._evdev_fd, 24 * 64)
                if not data:
                    break
                for off in range(0, len(data) - 23, 24):
                    _, _, etype, code, value = struct.unpack_from(
                        "qqHHi", data, off)
                    if etype == 3 and code < 6:          # EV_ABS
                        # raw kernel axes: X, Y(fwd/back), Z(up/down)
                        order = (0, 2, 1, 3, 5, 4)
                        sign = (1, -1, -1, 1, -1, -1)
                        i = order[code]
                        motion[i] += value * sign[code] * (_FULL / 500.0)
                    elif etype == 1 and value in (0, 1):  # EV_KEY
                        buttons.append((code - 0x100, value == 1))
        except BlockingIOError:
            pass
        except OSError:
            self._disconnect()
            return
        self._apply(motion, buttons)

    def _disconnect(self):
        if self._notifier is not None:
            self._notifier.setEnabled(False)
            self._notifier = None
        self.sock = None
        self.source = None
        self._retry.start()

    # ------------------------------------------------------------ mapping

    def _apply(self, m, buttons):
        cfg = self.cfg
        if not cfg.get("spacemouse", "enabled", default=True):
            return
        for num, pressed in buttons:
            if pressed:
                self._button(num)
        if not any(m):
            return
        sens = float(cfg.get("spacemouse", "sensitivity", default=1.0))
        x, y, z, rx, ry, rz = (v / _FULL for v in m)
        if time.time() < self.diag_until:
            now = time.time()
            if now - self._diag_last > 0.25:
                self._diag_last = now
                self.window.ctx.echo(
                    f"[spacemouse] slide {x:+.2f},{y:+.2f} push {z:+.2f} "
                    f"tilt {rx:+.2f} twist {ry:+.2f} roll {rz:+.2f}")
        s_pan = -1.0 if cfg.get("spacemouse", "invert_pan",
                                default=False) else 1.0
        s_zoom = -1.0 if cfg.get("spacemouse", "invert_zoom",
                                 default=False) else 1.0
        s_orb = -1.0 if cfg.get("spacemouse", "invert_orbit",
                                default=False) else 1.0

        vp = self.window.active_viewport
        if vp.space != "model":
            lv = vp.layout_view
            k = _PAN_PX * sens / max(lv.px_per_mm, 1e-6)
            lv.pan[0] -= s_pan * x * k
            lv.pan[1] -= s_pan * y * k
            if abs(z) > 1e-3:
                lv.wheel(s_zoom * -z * _ZOOM_STEPS * sens * 4,
                         vp.width() / 2, vp.height() / 2)
            vp.update()
            return

        cam = vp.camera
        if abs(x) > 1e-3 or abs(y) > 1e-3:
            cam.pan(s_pan * x * _PAN_PX * sens,
                    s_pan * y * _PAN_PX * sens, vp.height())
        if abs(z) > 1e-3:
            cam.zoom(s_zoom * -z * _ZOOM_STEPS * sens)
        if abs(rx) > 1e-3 or abs(ry) > 1e-3:
            cam.orbit(s_orb * -ry * _ORBIT_PX * sens,
                      s_orb * rx * _ORBIT_PX * sens)
        vp.update()

    def _button(self, num):
        cmds = self.cfg.get("spacemouse", "buttons",
                            default={"0": "zoomextents",
                                     "1": "perspective"}) or {}
        cmd = cmds.get(str(num))
        if cmd and not self.window.processor.busy:
            self.window.run_command(cmd)
