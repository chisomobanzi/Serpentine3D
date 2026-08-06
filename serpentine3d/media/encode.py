"""Frames to a file: ffmpeg when it is there, a PNG folder when not.

The writer is a pipe, not a library binding: raw RGB frames go to
ffmpeg's stdin and x264 does the rest. No frame ever touches the disk
twice, and the dependency stays optional — a machine without ffmpeg
still gets every frame, numbered, with the assembly command printed.
"""

from __future__ import annotations

import os
import shutil
import subprocess

from PySide6.QtGui import QImage


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ffmpeg_args(width: int, height: int, fps: int, out: str) -> list[str]:
    """The invocation for piping raw frames in and getting an mp4 out."""
    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        # yuv420p plays everywhere, notably phones and browsers
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        out,
    ]


def _rgb_bytes(img: QImage, width: int, height: int) -> bytes:
    img = img.convertToFormat(QImage.Format.Format_RGB888)
    if (img.width(), img.height()) != (width, height):
        img = img.scaled(width, height)
    stride = img.bytesPerLine()
    buf = img.constBits().tobytes()
    row = width * 3
    if stride == row:
        return buf
    return b"".join(buf[y * stride:y * stride + row]
                    for y in range(height))


class FfmpegWriter:
    def __init__(self, out: str, width: int, height: int, fps: int):
        self.out = out
        self.width, self.height = width, height
        self._proc = subprocess.Popen(
            ffmpeg_args(width, height, fps, out),
            stdin=subprocess.PIPE, stderr=subprocess.PIPE)

    def write(self, img: QImage):
        self._proc.stdin.write(_rgb_bytes(img, self.width, self.height))

    def close(self) -> str:
        self._proc.stdin.close()
        err = self._proc.stderr.read().decode(errors="replace")
        if self._proc.wait() != 0:
            raise RuntimeError(f"ffmpeg failed: {err.strip()}")
        return self.out


class PngWriter:
    """The fallback: every frame as a numbered PNG beside the asked-for
    path, plus the ffmpeg line that would finish the job elsewhere."""

    def __init__(self, out: str, width: int, height: int, fps: int = 30):
        base = out[:-4] if out.lower().endswith(".mp4") else out
        self.dir = base + "-frames"
        os.makedirs(self.dir, exist_ok=True)
        self.width, self.height = width, height
        self.fps = fps
        self._n = 0

    def write(self, img: QImage):
        img.save(os.path.join(self.dir, f"frame-{self._n:04d}.png"))
        self._n += 1

    def close(self) -> str:
        return self.dir

    def assembly_hint(self) -> str:
        return (f"ffmpeg -r {self.fps} -i {self.dir}/frame-%04d.png "
                f"-c:v libx264 -pix_fmt yuv420p out.mp4")


def writer_for(out: str, width: int, height: int, fps: int):
    if ffmpeg_available():
        return FfmpegWriter(out, width, height, fps)
    return PngWriter(out, width, height, fps)
