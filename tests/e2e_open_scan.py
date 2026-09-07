"""E2E: open a given scan .serp in the live app, select it, screenshot.

    E2E_FILE=/path/to/scan.serp E2E_SHOT=/path/out.png \
        tests/run_e2e.sh tests/e2e_open_scan.py
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
from rpc_client import SerpClient  # noqa: E402

FILE = os.environ["E2E_FILE"]
SHOT = os.environ.get("E2E_SHOT", "/tmp/serp3d-scan.png")


def main():
    c = SerpClient()
    t = time.time()
    print("import:", c.call("import_file", path=FILE),
          f"in {time.time() - t:.2f}s (includes the first draw)")
    objs = c.call("scene_info")
    objs = objs.get("objects", objs)
    clouds = [o for o in objs if o.get("kind") == "pointcloud"]
    print("clouds:", json.dumps(clouds)[:400])
    assert clouds, f"no point cloud in the scene: {objs}"
    c.call("set_viewport", view="perspective", display_mode="shaded",
           zoom_extents=True)
    time.sleep(1.0)
    root, ext = os.path.splitext(SHOT)
    print("screenshot:", c.call("screenshot", path=root + "-colour" + ext,
                                full_window=True))
    print("select:", c.call("select", names=[clouds[0]["name"]]))
    time.sleep(1.0)
    print("count:", c.call("command", command="count"))
    # a few view changes, timed end to end over the socket, as a feel for
    # how the pane keeps up with the cloud
    t = time.time()
    for view in ("top", "front", "right", "perspective"):
        c.call("set_viewport", view=view, zoom_extents=True)
    print(f"four view changes round-tripped in {time.time() - t:.2f}s")
    print("screenshot:", c.call("screenshot", path=SHOT, full_window=True))


if __name__ == "__main__":
    main()
