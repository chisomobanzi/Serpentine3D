"""E2E: a v3 .serp scan opens in the live app, draws, selects, screenshots.

Run through tests/run_e2e.sh (Xephyr + clean-config app):

    tests/run_e2e.sh tests/e2e_pointcloud.py

Writes the file it opens with zipfile and numpy straight from the spec, the
way the engine does, so nothing of Serpentine's own writer is on the path.
The screenshot goes to E2E_SHOT (default /tmp/serp3d-pointcloud.png).
"""

import json
import os
import sys
import tempfile
import zipfile

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from rpc_client import SerpClient  # noqa: E402

SHOT = os.environ.get("E2E_SHOT", "/tmp/serp3d-pointcloud.png")


def room_scan(points: int = 1_000_000, seed: int = 11):
    """A scanned room: floor, three walls, a table, colour by surface."""
    rng = np.random.default_rng(seed)
    w, d, h = 6.0, 4.5, 2.7
    parts = []

    def plane(n, lo, hi, colour, jitter=0.01):
        p = rng.random((n, 3)) * (np.array(hi) - np.array(lo)) + np.array(lo)
        p += rng.normal(0, jitter, p.shape)
        c = np.array(colour, float) + rng.normal(0, 8, (n, 3))
        parts.append((p, np.clip(c, 0, 255)))

    plane(int(points * 0.35), (0, 0, 0), (w, d, 0), (168, 150, 120))    # floor
    plane(int(points * 0.2), (0, 0, 0), (w, 0, h), (210, 205, 195))     # wall y=0
    plane(int(points * 0.15), (0, 0, 0), (0, d, h), (190, 200, 215))    # wall x=0
    plane(int(points * 0.2), (0, d, 0), (w, d, h), (215, 200, 190))     # wall y=d
    plane(int(points * 0.05), (2, 1.5, 0.75), (3.6, 2.4, 0.75),
          (120, 80, 50))                                                # table top
    # no ceiling: the room is looked into from above
    plane(int(points * 0.05), (0, 0, 0), (w, d, 0.02), (150, 135, 110))  # rug
    xyz = np.concatenate([p for p, _ in parts]).astype("<f4")
    rgb = np.concatenate([c for _, c in parts]).astype(np.uint8)
    n = len(xyz)
    conf = rng.random(n).astype("<f4")
    level = rng.choice([0, 1, 2], size=n, p=[0.15, 0.3, 0.55]).astype(np.uint8)
    return xyz, rgb, conf, level


def write_scan(path: str):
    xyz, rgb, conf, level = room_scan()
    n = len(xyz)
    doc = {
        "format": "serpentine3d", "version": 3, "requires": "0.9.0",
        "units": "m",
        "layers": [
            {"id": "default", "name": "Default", "color": [0.8, 0.8, 0.8],
             "visible": True},
            {"id": "scan", "name": "Scan", "color": [0.1, 0.6, 0.9],
             "visible": True},
        ],
        "current_layer": "default",
        "objects": [],
        "pointclouds": [{
            "id": "pc-room", "name": "Room", "layer": "scan", "visible": True,
            "count": n,
            "bbox": [xyz.min(axis=0).tolist(), xyz.max(axis=0).tolist()],
            "blobs": {"xyz": "blobs/pc-room/xyz.f32",
                      "rgb": "blobs/pc-room/rgb.u8",
                      "conf": "blobs/pc-room/conf.f32",
                      "level": "blobs/pc-room/level.u8"},
            "provenance": {"session": "sess-e2e", "stream": "a",
                           "backbone": "lingbot-map", "scale": "metric",
                           "created": "2026-09-03T12:00:00"},
        }],
        "trajectories": [{
            "id": "traj-a", "name": "Wearer", "layer": "scan",
            "visible": True, "stream": "a",
            "intrinsics": [500, 0, 320, 0, 500, 240, 0, 0, 1],
            "image_size": [640, 480],
            "frames": [{"t_ns": i * 33_000_000, "index": i,
                        "c2w": [1, 0, 0, 0.2 * i, 0, 1, 0, 1.0,
                                0, 0, 1, 1.6, 0, 0, 0, 1], "vis": 0.9}
                       for i in range(30)],
        }],
        "session": {"id": "sess-e2e", "engine": "mica e2e",
                    "backbone": "lingbot-map", "scale": "metric"},
    }
    meta = {"format": "serpentine3d", "version": 3,
            "saved": "2026-09-03T12:00:00", "objects": 0, "layouts": 0,
            "pointclouds": 1, "points": n, "trajectories": 1,
            "session": {"id": "sess-e2e", "engine": "mica e2e",
                        "backbone": "lingbot-map"}}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("meta.json", json.dumps(meta))
        z.writestr("document.json", json.dumps(doc))
        z.writestr("blobs/pc-room/xyz.f32", xyz.tobytes(),
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("blobs/pc-room/rgb.u8", rgb.tobytes(),
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("blobs/pc-room/conf.f32", conf.tobytes(),
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("blobs/pc-room/level.u8", level.tobytes(),
                   compress_type=zipfile.ZIP_STORED)
    return n


def main():
    work = tempfile.mkdtemp(prefix="serp3d-pc-")
    path = os.path.join(work, "room.serp")
    n = write_scan(path)
    print(f"wrote {path} with {n:,} points")

    c = SerpClient()
    # a clean-config launch is already an empty scene; `new` would only
    # ask whether to clear it
    print("import:", c.call("import_file", path=path))
    info = c.call("scene_info")
    objs = info.get("objects", info)
    print("scene:", json.dumps(objs)[:300])
    kinds = [o.get("kind") for o in objs] if isinstance(objs, list) else []
    assert "pointcloud" in kinds, f"no point cloud in the scene: {info}"
    c.call("set_viewport", view="perspective", display_mode="shaded",
           zoom_extents=True)
    # a moment for the frame, then the proof: once in the scanner's
    # colours, once selected
    import time
    time.sleep(1.0)
    root, ext = os.path.splitext(SHOT)
    print("screenshot:", c.call("screenshot", path=root + "-colour" + ext,
                                full_window=True))
    print("select:", c.call("select", names=["Room"]))
    time.sleep(1.0)
    print("count:", c.call("command", command="count"))
    print("screenshot:", c.call("screenshot", path=SHOT, full_window=True))
    # save it back and check the round trip kept the scan
    again = os.path.join(work, "again.serp")
    print("export:", c.call("export_file", path=again))
    with zipfile.ZipFile(again) as z:
        doc = json.loads(z.read("document.json"))
        assert doc["version"] == 3 and doc["pointclouds"][0]["count"] == n
        assert doc["session"]["id"] == "sess-e2e"
        assert len(doc["trajectories"]) == 1
    print("round trip ok")


if __name__ == "__main__":
    main()
