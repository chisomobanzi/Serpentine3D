"""End-to-end Definition-of-Done verification.

Drives the real running app (inside Xephyr :2) with RPC calls and xdotool
synthetic input, capturing screenshots for visual review.

Run:  DISPLAY=:2 .venv/bin/python tests/e2e_dod.py
"""

import json
import subprocess
import sys
import time

sys.path.insert(0, "tests")
from rpc_client import SerpClient  # noqa: E402

SHOT = "screenshots/dod"
DISPLAY = ":2"


def xdo(*args):
    subprocess.run(["xdotool", *args], env={"DISPLAY": DISPLAY,
                                            "PATH": "/usr/bin:/bin"},
                   check=True)
    time.sleep(0.25)


def shot(c, name, full=False):
    c.call("screenshot", path=f"{SHOT}_{name}.png", full_window=full)


def type_cmd(text):
    xdo("type", "--delay", "30", text)
    xdo("key", "Return")


def main():
    c = SerpClient()
    results = {}

    def check(name, cond, detail=""):
        results[name] = ("PASS" if cond else "FAIL", detail)
        print(f"[{'PASS' if cond else 'FAIL'}] {name} {detail}")

    # start from a clean scene
    c.call("command", command="new", inputs=["Yes"])

    # --- item 4: curve creation via the command pipeline ------------------
    c.call("command", command="line", inputs=["0,0,0", "20,0,0"])
    c.call("command", command="polyline",
           inputs=["25,0,0", "35,0,0", "35,10,0", "25,10,0", "c"])
    c.call("command", command="circle", inputs=["50,5,0", "6"])
    c.call("command", command="arc", inputs=["65,0,0", "72,6,0", "80,0,0"])
    c.call("command", command="curve",
           inputs=["0,20,0", "10,28,0", "20,18,0", "30,26,0", ""])
    info = c.call("scene_info")
    kinds = [o["kind"] for o in info["objects"]]
    check("curves: line/polyline/circle/arc/nurbs",
          len(info["objects"]) == 5 and all(k == "curve" for k in kinds),
          f"{len(info['objects'])} curves")
    c.call("set_viewport", zoom_extents=True, view="top")
    shot(c, "01_curves")

    # --- item 5: surfaces ---------------------------------------------------
    c.call("command", command="new", inputs=["Yes"])
    c.call("create_curve", points=[[0, 0, 0], [10, 0, 0], [10, 10, 0],
                                   [0, 10, 0]],
           kind="polyline", closed=True, name="SqProfile")
    c.call("create_surface", operation="extrude", curves=["SqProfile"],
           params={"distance": 12, "cap": False}, name="ExtrudeSrf")
    c.call("create_curve", points=[[20, 0, 0], [24, 0, 4], [22, 0, 9],
                                   [26, 0, 14]], kind="interp",
           name="RevProfile")
    c.call("create_surface", operation="revolve", curves=["RevProfile"],
           params={"axis_point": [30, 0, 0], "axis_dir": [0, 0, 1],
                   "angle": 360}, name="RevSrf")
    c.call("create_curve", points=[[40, 0, 0], [50, 5, 0], [60, 0, 0]],
           kind="interp", name="L1")
    c.call("create_curve", points=[[40, 2, 8], [50, 8, 10], [60, 2, 8]],
           kind="interp", name="L2")
    c.call("create_surface", operation="loft", curves=["L1", "L2"],
           name="LoftSrf")
    c.call("create_curve", points=[[70, 0, 0], [80, 0, 0], [80, 10, 0],
                                   [70, 10, 0]], kind="polyline",
           closed=True, name="PlanarProfile")
    c.call("create_surface", operation="planar", curves=["PlanarProfile"],
           name="PlanarSrf")
    info = c.call("scene_info")
    srf = [o for o in info["objects"] if o["kind"] in ("surface", "solid")]
    check("surfaces: extrude/revolve/loft/planar", len(srf) == 4,
          f"{len(srf)} surfaces")
    c.call("set_viewport", zoom_extents=True, view="perspective")
    shot(c, "02_surfaces")

    # --- item 6: transforms -------------------------------------------------
    c.call("command", command="new", inputs=["Yes"])
    c.call("command", command="box", inputs=["0,0,0", "5,5,0", "5"])
    c.call("transform", operation="move", targets=["Solid 01"],
           params={"offset": [10, 0, 0]})
    mn = c.call("measure", what="bbox",
                targets=["Solid 01"])["bboxes"]["Solid 01"][0]
    move_ok = abs(mn[0] - 10) < 1e-6
    c.call("transform", operation="copy", targets=["Solid 01"],
           params={"offset": [10, 0, 0]})
    n_after_copy = c.call("scene_info")["object_count"]
    c.call("transform", operation="rotate", targets=["Solid 01"],
           params={"center": [10, 0, 0], "angle": 45})
    c.call("transform", operation="scale", targets=["Solid 01"],
           params={"center": [10, 0, 0], "factor": 2})
    c.call("transform", operation="mirror", targets=["Solid 01"],
           params={"plane_point": [0, 0, 0], "plane_normal": [1, 0, 0],
                   "keep_original": True})
    n_final = c.call("scene_info")["object_count"]
    check("transforms: move/copy/rotate/scale/mirror",
          move_ok and n_after_copy == 2 and n_final == 3)
    c.call("set_viewport", zoom_extents=True)
    shot(c, "03_transforms")

    # --- item 7: booleans ---------------------------------------------------
    c.call("command", command="new", inputs=["Yes"])
    c.call("command", command="box", inputs=["0,0,0", "20,20,0", "20"])
    c.call("command", command="sphere", inputs=["20,20,20", "12"])
    r = c.call("boolean", operation="difference", targets=["Solid 01"],
               tools=["Solid 02"])
    vol = c.call("measure", what="volume", targets=[r["name"]])["volume"]
    check("boolean difference", 4000 < vol < 8000, f"vol={vol:.0f}")
    c.call("command", command="box", inputs=["0,0,0", "8,8,0", "30"])
    r2 = c.call("boolean", operation="union", targets=[r["name"]],
                tools=["Solid 03"])
    c.call("command", command="cylinder", inputs=["10,10,-5", "4", "40"])
    r3 = c.call("boolean", operation="intersection",
                targets=[r2["name"]], tools=["Solid 04"])
    vol3 = c.call("measure", what="volume", targets=[r3["name"]])["volume"]
    check("boolean union+intersection", 0 < vol3 < 3000,
          f"vol={vol3:.0f}")
    c.call("set_viewport", zoom_extents=True)
    shot(c, "04_booleans")

    # --- item 2 + 8: navigation and click selection (real mouse) ----------
    c.call("command", command="new", inputs=["Yes"])
    c.call("command", command="box", inputs=["-5,-5,0", "5,5,0", "8"])
    c.call("set_viewport", zoom_extents=True, view="perspective")
    vp = c.call("viewport_info", project=[[0, 0, 4]])
    ox, oy = vp["origin"]
    px, py = vp["projected"][0]

    # click on the box -> selects
    xdo("mousemove", str(int(ox + px)), str(int(oy + py)))
    xdo("click", "1")
    time.sleep(0.3)
    sel = c.call("viewport_info")["selected"]
    check("click-select", sel == ["Solid 01"], f"selected={sel}")
    shot(c, "05_selected")

    # click empty space -> deselects
    xdo("mousemove", str(int(ox + 30)), str(int(oy + 30)))
    xdo("click", "1")
    time.sleep(0.3)
    sel = c.call("viewport_info")["selected"]
    check("click-empty-deselect", sel == [], f"selected={sel}")

    # orbit: middle-drag changes azimuth/elevation
    cam0 = c.call("viewport_info")["camera"]
    cx, cy = int(ox + vp["size"][0] / 2), int(oy + vp["size"][1] / 2)
    xdo("mousemove", str(cx), str(cy))
    xdo("mousedown", "2")
    for i in range(1, 9):
        xdo("mousemove", str(cx + i * 12), str(cy + i * 5))
    xdo("mouseup", "2")
    cam1 = c.call("viewport_info")["camera"]
    check("orbit (MMB drag)",
          abs(cam1["azimuth"] - cam0["azimuth"]) > 0.05,
          f"dAz={cam1['azimuth']-cam0['azimuth']:.3f}")

    # zoom: wheel
    xdo("click", "4")
    xdo("click", "4")
    cam2 = c.call("viewport_info")["camera"]
    check("zoom (wheel)", cam2["distance"] < cam1["distance"],
          f"{cam1['distance']:.1f} -> {cam2['distance']:.1f}")

    # pan: shift+middle-drag moves target
    xdo("keydown", "shift")
    xdo("mousedown", "2")
    for i in range(1, 7):
        xdo("mousemove", str(cx + i * 15), str(cy))
    xdo("mouseup", "2")
    xdo("keyup", "shift")
    cam3 = c.call("viewport_info")["camera"]
    dt = sum((a - b) ** 2 for a, b in
             zip(cam3["target"], cam2["target"])) ** 0.5
    check("pan (Shift+MMB)", dt > 0.1, f"target moved {dt:.2f}")
    shot(c, "06_after_nav")

    # --- item 8b: delete selected ------------------------------------------
    c.call("set_viewport", zoom_extents=True)
    vp = c.call("viewport_info", project=[[0, 0, 4]])
    ox, oy = vp["origin"]
    px, py = vp["projected"][0]
    xdo("mousemove", str(int(ox + px)), str(int(oy + py)))
    xdo("click", "1")
    time.sleep(0.3)
    xdo("key", "Delete")
    time.sleep(0.5)
    n = c.call("scene_info")["object_count"]
    check("delete selected via Delete key", n == 0, f"{n} objects left")

    # --- item 9: display modes ----------------------------------------------
    c.call("command", command="box", inputs=["0,0,0", "10,10,0", "10"])
    c.call("command", command="sphere", inputs=["15,5,5", "4"])
    c.call("set_viewport", zoom_extents=True)
    c.call("set_viewport", display_mode="wireframe")
    shot(c, "07_wireframe")
    mode_w = c.call("scene_info")["display_mode"]
    c.call("set_viewport", display_mode="shaded")
    shot(c, "08_shaded")
    mode_s = c.call("scene_info")["display_mode"]
    check("display modes toggle", mode_w == "wireframe" and
          mode_s == "shaded")

    # --- item 10: file I/O ----------------------------------------------------
    import os
    os.makedirs("/tmp/serp_e2e", exist_ok=True)
    c.call("export_file", path="/tmp/serp_e2e/scene.serp")
    c.call("export_file", path="/tmp/serp_e2e/scene.step")
    c.call("export_file", path="/tmp/serp_e2e/scene.obj")
    c.call("command", command="new", inputs=["Yes"])
    c.call("import_file", path="/tmp/serp_e2e/scene.serp")
    n_serp = c.call("scene_info")["object_count"]
    c.call("command", command="new", inputs=["Yes"])
    c.call("import_file", path="/tmp/serp_e2e/scene.step")
    n_step = c.call("scene_info")["object_count"]
    c.call("command", command="new", inputs=["Yes"])
    c.call("import_file", path="/tmp/serp_e2e/scene.obj")
    n_obj = c.call("scene_info")["object_count"]
    check("file io: serp3d/step/obj round-trips",
          n_serp == 2 and n_step == 2 and n_obj == 2,
          f"serp3d={n_serp} step={n_step} obj={n_obj}")

    # --- item 11: layers -------------------------------------------------------
    c.call("command", command="new", inputs=["Yes"])
    c.call("layers", action="create", name="Walls", color=[0.9, 0.5, 0.2])
    c.call("layers", action="rename", name="Walls", new_name="Set Walls")
    c.call("command", command="box", inputs=["0,0,0", "10,10,0", "10"])
    c.call("layers", action="assign", name="Set Walls",
           objects=["Solid 01"])
    c.call("layers", action="visible", name="Set Walls", visible=False)
    hidden = c.call("scene_info")
    vis_hidden = [o for o in hidden["objects"] if o["visible"]]
    bounds_none = hidden["bounds"] is None
    c.call("layers", action="visible", name="Set Walls", visible=True)
    layers = {l["name"] for l in c.call("scene_info")["layers"]}
    check("layers: create/rename/assign/visibility",
          "Set Walls" in layers and bounds_none,
          f"layers={layers}")
    shot(c, "09_layers", full=True)

    # --- item 12: undo/redo ------------------------------------------------------
    n0 = c.call("scene_info")["object_count"]
    c.call("command", command="sphere", inputs=["30,0,0", "5"])
    c.call("undo")
    n1 = c.call("scene_info")["object_count"]
    c.call("redo")
    n2 = c.call("scene_info")["object_count"]
    check("undo/redo", n1 == n0 and n2 == n0 + 1,
          f"{n0}->{n1}->{n2}")

    # --- new tools: split/trim/sweep2 --------------------------------------
    c.call("command", command="new", inputs=["Yes"])
    c.call("create_curve", points=[[0, 0, 0], [10, 0, 0]], kind="line",
           name="T")
    c.call("create_curve", points=[[5, -5, 0], [5, 5, 0]], kind="line",
           name="K")
    c.call("command", command="split", inputs=["T", "", "K", ""])
    n = c.call("scene_info")["object_count"]
    check("split command", n == 3, f"{n} objects")

    c.call("command", command="new", inputs=["Yes"])
    c.call("create_curve", points=[[0, 0, 0], [20, 0, 0]], kind="line",
           name="R1")
    c.call("create_curve", points=[[0, 6, 0], [20, 6, 0]], kind="line",
           name="R2")
    c.call("create_curve", points=[[0, 0, 0], [0, 0, 4]], kind="line",
           name="P")
    c.call("command", command="sweep2", inputs=["R1", "R2", "P"])
    kinds = [o["kind"] for o in c.call("scene_info")["objects"]]
    check("sweep2 command", "surface" in kinds or "solid" in kinds,
          f"kinds={kinds}")

    # --- selection tools -----------------------------------------------------
    c.call("command", command="new", inputs=["Yes"])
    c.call("command", command="box", inputs=["0,0,0", "5,5,0", "5"])
    c.call("create_curve", points=[[10, 0, 0], [15, 5, 0]], kind="line")
    c.call("command", command="selcrv")
    sel1 = c.call("scene_info")["selected"]
    c.call("command", command="invert")
    sel2 = c.call("scene_info")["selected"]
    check("selcrv + invert", len(sel1) == 1 and sel2 == ["Solid 01"],
          f"{sel1} -> {sel2}")
    c.call("command", command="isolate", inputs=["Solid 01", ""])
    vis = [o for o in c.call("scene_info")["objects"] if o["visible"]]
    c.call("command", command="unisolate")
    vis2 = [o for o in c.call("scene_info")["objects"] if o["visible"]]
    check("isolate/unisolate", len(vis) == 1 and len(vis2) == 2)

    # --- control points via API path ----------------------------------------
    c.call("command", command="new", inputs=["Yes"])
    c.call("create_curve", points=[[0, 0, 0], [5, 8, 0], [10, 0, 0]],
           kind="control", name="CV")
    r = c.call("command", command="pointson", inputs=["CV", ""])
    check("pointson", any("Control points on" in m for m in r["messages"]))
    c.call("command", command="pointsoff")

    # --- 3dm round-trip -------------------------------------------------------
    c.call("command", command="new", inputs=["Yes"])
    c.call("command", command="circle", inputs=["0,0,0", "5"])
    c.call("export_file", path="/tmp/serp_e2e/roundtrip.3dm")
    c.call("command", command="new", inputs=["Yes"])
    c.call("import_file", path="/tmp/serp_e2e/roundtrip.3dm")
    length = c.call("measure", what="length",
                    targets=[c.call("scene_info")["objects"][0]["name"]])
    import math as _m
    check("3dm round-trip exact circle",
          abs(length["length"] - 2 * _m.pi * 5) < 1e-6,
          f"len={length['length']:.6f}")

    # --- drafting: layouts, details, annotations, make2d, pdf --------------
    import os
    c.call("command", command="new", inputs=["Yes"])
    c.call("command", command="box", inputs=["-300,-200,0", "300,200,0", "80"])
    c.call("command", command="cylinder", inputs=["0,0,80", "120", "300"])
    c.call("command", command="layout",
           inputs=["New", "E2E Sheet", "A3", "Landscape"])
    c.call("command", command="detail",
           inputs=["20,20", "200,180", "Top", "1:5"])
    c.call("command", command="detail",
           inputs=["220,20", "400,180", "Front", "1:5"])
    c.call("command", command="text",
           inputs=["20,270", "E2E TEST SHEET", "5"])
    c.call("command", command="dim", inputs=["50,40", "170,40", "110,30"])
    r = c.call("command", command="exportpdf",
               inputs=["/tmp/serp_e2e/e2e_sheet.pdf"])
    pdf_ok = (os.path.exists("/tmp/serp_e2e/e2e_sheet.pdf")
              and os.path.getsize("/tmp/serp_e2e/e2e_sheet.pdf") > 2000)
    check("drafting: layout/details/text/dim/pdf", pdf_ok,
          f"pdf={os.path.getsize('/tmp/serp_e2e/e2e_sheet.pdf')}b")
    shot(c, "10_layout_sheet")

    # switch back to model space for make2d (tab click equivalent)
    c.call("command", command="layout", inputs=["Delete", "E2E Sheet"])
    n0 = c.call("scene_info")["object_count"]
    c.call("set_viewport", view="front", zoom_extents=True)
    c.call("command", command="make2d", inputs=[""])
    n1 = c.call("scene_info")["object_count"]
    layer_names = {l["name"] for l in c.call("scene_info")["layers"]}
    check("make2d", n1 > n0 and "Make2D visible" in layer_names,
          f"{n0}->{n1} objects, layers={sorted(layer_names)}")

    # technical display mode renders
    c.call("set_viewport", display_mode="technical")
    mode = c.call("scene_info")["display_mode"]
    shot(c, "11_technical")
    c.call("set_viewport", display_mode="shaded")
    check("technical display mode", mode == "technical")

    # --- summary ---
    print()
    fails = [k for k, v in results.items() if v[0] == "FAIL"]
    print(f"{len(results) - len(fails)}/{len(results)} checks passed")
    if fails:
        print("FAILURES:", fails)
        sys.exit(1)


if __name__ == "__main__":
    main()
