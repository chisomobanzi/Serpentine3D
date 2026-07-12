"""Hidden line removal via OCCT HLRBRep.

Projects 3D shapes along a view direction, separating visible edges,
silhouettes (outlines), and hidden edges. Results are 2D curves lying in
the projection plane (z=0 of the projector frame).
"""

from __future__ import annotations

import numpy as np

from . import geometry, occ
from .occ import gp_Ax2, gp_Dir, gp_Pnt


def _projector(origin, view_dir, x_dir):
    from OCP.HLRAlgo import HLRAlgo_Projector
    ax2 = gp_Ax2(gp_Pnt(*[float(c) for c in origin]),
                 gp_Dir(*[float(c) for c in view_dir]),
                 gp_Dir(*[float(c) for c in x_dir]))
    return HLRAlgo_Projector(ax2)


def hlr_project(shapes: list, origin, view_dir, x_dir,
                include_hidden: bool = True) -> dict:
    """Run HLR. Returns {'visible': [edges], 'outline': [...], 'hidden': [...]}

    view_dir points from the scene towards the viewer. Output edges lie in
    the projector's XY plane: x along x_dir, y along (view_dir x x_dir).
    """
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape

    algo = HLRBRep_Algo()
    for s in shapes:
        algo.Add(s)
    algo.Projector(_projector(origin, view_dir, x_dir))
    algo.Update()
    algo.Hide()
    conv = HLRBRep_HLRToShape(algo)

    def edges(compound) -> list:
        if compound is None or compound.IsNull():
            return []
        return geometry.edges_of(compound)

    out = {
        "visible": edges(conv.VCompound()) + edges(conv.Rg1LineVCompound()),
        "outline": edges(conv.OutLineVCompound()),
        "hidden": [],
    }
    if include_hidden:
        out["hidden"] = (edges(conv.HCompound())
                         + edges(conv.OutLineHCompound())
                         + edges(conv.Rg1LineHCompound()))
    return out


def edges_to_polylines(edges: list, deflection: float = 0.1) -> list:
    """Tessellate HLR result edges into (N,3) float arrays."""
    from .tessellate import _edge_polyline
    out = []
    for e in edges:
        pts = _edge_polyline(e, deflection)
        if pts is not None and len(pts) >= 2:
            out.append(pts)
    return out


def polylines_2d(polylines: list) -> list:
    """Drop the (≈0) z of projector-frame polylines -> (N,2) arrays."""
    return [p[:, :2].astype(np.float32) for p in polylines]


# ------------------------------------------------------- crash-safe wrapper
#
# OCCT's HLR can segfault on degenerate input (e.g. re-projecting a 2D
# drawing edge-on). A worker process isolates those crashes: the app loses
# one HLR result instead of the session.

import json as _json
import os as _os
import subprocess as _subprocess
import sys as _sys
import tempfile as _tempfile


class _HlrWorker:
    def __init__(self):
        self.proc = None

    def _ensure(self):
        if self.proc is not None and self.proc.poll() is None:
            return
        env = dict(_os.environ)
        env.pop("SERP_NO_RPC", None)
        self.proc = _subprocess.Popen(
            [_sys.executable, "-m", "serpentine.core.hlr"],
            stdin=_subprocess.PIPE, stdout=_subprocess.PIPE,
            stderr=_subprocess.DEVNULL, env=env, text=True)

    def project(self, shapes: list, origin, view_dir, x_dir,
                include_hidden: bool = True, timeout: float = 120.0) -> dict:
        """Like hlr_project, but crash-isolated. Empty result on failure."""
        empty = {"visible": [], "outline": [], "hidden": []}
        if not shapes:
            return empty
        from . import geometry
        tmp = _tempfile.mkdtemp(prefix="serp_hlr_")
        in_path = _os.path.join(tmp, "in.brep")
        v_path = _os.path.join(tmp, "vis.brep")
        h_path = _os.path.join(tmp, "hid.brep")
        try:
            occ.brep_write(geometry.make_compound(shapes), in_path)
            req = _json.dumps({
                "in": in_path, "vis": v_path, "hid": h_path,
                "origin": list(map(float, origin)),
                "view_dir": list(map(float, view_dir)),
                "x_dir": list(map(float, x_dir)),
                "include_hidden": include_hidden,
            })
            self._ensure()
            try:
                self.proc.stdin.write(req + "\n")
                self.proc.stdin.flush()
                line = self.proc.stdout.readline()
            except (BrokenPipeError, OSError):
                line = ""
            if not line.strip() or not line.strip().startswith("ok"):
                # worker crashed (segfault) or errored: restart next time
                try:
                    self.proc.kill()
                except Exception:
                    pass
                self.proc = None
                return empty
            out = dict(empty)
            if _os.path.exists(v_path):
                out["visible"] = geometry.edges_of(occ.brep_read(v_path))
            if include_hidden and _os.path.exists(h_path):
                out["hidden"] = geometry.edges_of(occ.brep_read(h_path))
            return out
        finally:
            for p in (in_path, v_path, h_path):
                try:
                    _os.unlink(p)
                except OSError:
                    pass
            try:
                _os.rmdir(tmp)
            except OSError:
                pass


_worker = _HlrWorker()


def hlr_project_safe(shapes: list, origin, view_dir, x_dir,
                     include_hidden: bool = True) -> dict:
    return _worker.project(shapes, origin, view_dir, x_dir, include_hidden)


def _worker_main():
    """Entry point of the isolated HLR worker process."""
    from . import geometry
    for raw in _sys.stdin:
        try:
            req = _json.loads(raw)
            shape = occ.brep_read(req["in"])
            res = hlr_project([shape], req["origin"], req["view_dir"],
                              req["x_dir"],
                              include_hidden=req["include_hidden"])
            visible = res["visible"] + res["outline"]
            if visible:
                occ.brep_write(geometry.make_compound(visible), req["vis"])
            if res["hidden"]:
                occ.brep_write(geometry.make_compound(res["hidden"]),
                               req["hid"])
            _sys.stdout.write("ok\n")
        except Exception as exc:                              # noqa: BLE001
            _sys.stdout.write(f"err {type(exc).__name__}\n")
        _sys.stdout.flush()


def dash_segments(polyline: np.ndarray, dash: float = 2.0,
                  gap: float = 1.2) -> np.ndarray:
    """Split a polyline into dash segment pairs (K,2,C) for hidden lines.

    Works in absolute arc length with integer dash indices, so it cannot
    loop regardless of floating-point round-off.
    """
    pts = polyline.astype(float)
    segs = []
    period = dash + gap
    s0 = 0.0
    for a, b in zip(pts[:-1], pts[1:]):
        seg_len = float(np.linalg.norm(b - a))
        if seg_len < 1e-12:
            continue
        direction = (b - a) / seg_len
        s1 = s0 + seg_len
        first = int(s0 // period)
        last = int(s1 // period)
        for k in range(first, last + 1):
            dash_start = k * period
            cs = max(dash_start, s0)
            ce = min(dash_start + dash, s1)
            if ce - cs > 1e-9:
                segs.append((a + direction * (cs - s0),
                             a + direction * (ce - s0)))
        s0 = s1
    if not segs:
        return np.zeros((0, 2, pts.shape[1]), np.float32)
    return np.asarray(segs, np.float32)


if __name__ == "__main__":
    _worker_main()
