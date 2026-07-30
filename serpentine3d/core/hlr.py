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
import shutil as _shutil
import subprocess as _subprocess
import sys as _sys
import tempfile as _tempfile
import threading as _threading

from ..utils import spawn as _spawn


def project_by_shape(shapes: list, origin, view_dir, x_dir,
                     include_hidden: bool = True) -> dict:
    """One HLR pass over every shape, visible edges kept per input shape.

    Everything goes into a single pass so hidden-line removal is correct
    across all of it, then the visible edges come back out *per input shape*
    via the HLRToShape per-shape overloads — that is what lets each object
    keep its own linetype while still being hidden by objects in front of it.
    """
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape

    def edges_for(method, arg):
        try:
            c = method(arg)
        except Exception:                                     # noqa: BLE001
            return []
        return [] if (c is None or c.IsNull()) else geometry.edges_of(c)

    algo = HLRBRep_Algo()
    for s in shapes:
        algo.Add(s)
    algo.Projector(_projector(origin, view_dir, x_dir))
    algo.Update()
    algo.Hide()
    conv = HLRBRep_HLRToShape(algo)

    by_shape = [edges_for(conv.VCompound, s)
                + edges_for(conv.OutLineVCompound, s)
                + edges_for(conv.Rg1LineVCompound, s)
                for s in shapes]
    hidden = []
    if include_hidden:
        hidden = (edges_for(lambda _: conv.HCompound(), None)
                  + edges_for(lambda _: conv.OutLineHCompound(), None)
                  + edges_for(lambda _: conv.Rg1LineHCompound(), None))
    return {"visible": [e for grp in by_shape for e in grp],
            "outline": [], "hidden": hidden, "visible_by_shape": by_shape}


class _HlrWorker:
    def __init__(self):
        self.proc = None

    def _ensure(self) -> bool:
        """Start the worker if it isn't running. False if it cannot be started.

        The command comes from `spawn` rather than from sys.executable: in an
        installed build sys.executable is the application, and asking it to run
        `-m serpentine3d.core.hlr` opened another copy of the app instead — one
        per hidden-line pass, so one per click.
        """
        if self.proc is not None and self.proc.poll() is None:
            return True
        cmd = _spawn.hlr_worker_command()
        if cmd is None:
            return False
        env = dict(_os.environ)
        env["SERP3D_NO_RPC"] = "1"    # a helper does not answer for the app
        self.proc = _subprocess.Popen(
            cmd, stdin=_subprocess.PIPE, stdout=_subprocess.PIPE,
            stderr=_subprocess.DEVNULL, env=env, text=True)
        return True

    def _answer(self, timeout: float) -> str:
        """The worker's reply, or "" if it stopped talking.

        A segfaulted worker leaves a pipe that never closes and never speaks;
        reading it straight left the GUI frozen with nothing to wake it.
        """
        got = []

        def read():
            try:
                got.append(self.proc.stdout.readline())
            except (OSError, ValueError):     # the pipe went with the worker
                got.append("")

        reader = _threading.Thread(target=read, daemon=True)
        reader.start()
        reader.join(timeout)
        return got[0] if got else ""

    def project(self, shapes: list, origin, view_dir, x_dir,
                include_hidden: bool = True, timeout: float = 120.0) -> dict:
        """Like hlr_project, but crash-isolated. Empty result on failure.

        Returns `visible_by_shape`: one visible-edge list per input shape, in
        order — computed from a single HLR pass so occlusion is correct across
        all shapes. `visible` is their flattened union (backward compatible)."""
        empty = {"visible": [], "outline": [], "hidden": [],
                 "visible_by_shape": []}
        if not shapes:
            return empty
        from . import geometry
        if not self._ensure():
            # Nothing to spawn but the app itself. Losing crash isolation is
            # bad; opening a copy of the app per pass is worse.
            try:
                return project_by_shape(shapes, origin, view_dir, x_dir,
                                        include_hidden)
            except Exception:                                 # noqa: BLE001
                return empty
        tmp = _tempfile.mkdtemp(prefix="serp_hlr_")
        in_path = _os.path.join(tmp, "in.brep")
        vis_prefix = _os.path.join(tmp, "vis_")     # per-shape: vis_0.brep …
        h_path = _os.path.join(tmp, "hid.brep")
        try:
            occ.brep_write(geometry.make_compound(shapes), in_path)
            req = _json.dumps({
                "in": in_path, "vis": vis_prefix, "hid": h_path,
                "origin": list(map(float, origin)),
                "view_dir": list(map(float, view_dir)),
                "x_dir": list(map(float, x_dir)),
                "include_hidden": include_hidden,
            })
            try:
                self.proc.stdin.write(req + "\n")
                self.proc.stdin.flush()
                line = self._answer(timeout)
            except (BrokenPipeError, OSError):
                line = ""
            parts = line.strip().split()
            if not parts or parts[0] != "ok":
                # crashed, errored, or went quiet: start a fresh one next time
                try:
                    self.proc.kill()
                except Exception:
                    pass
                self.proc = None
                return empty
            n = int(parts[1]) if len(parts) > 1 else 0
            by_shape = []
            for i in range(n):
                p = f"{vis_prefix}{i}.brep"
                by_shape.append(geometry.edges_of(occ.brep_read(p))
                                if _os.path.exists(p) else [])
            hidden = (geometry.edges_of(occ.brep_read(h_path))
                      if include_hidden and _os.path.exists(h_path) else [])
            return {"visible": [e for grp in by_shape for e in grp],
                    "outline": [], "hidden": hidden,
                    "visible_by_shape": by_shape}
        finally:
            _shutil.rmtree(tmp, ignore_errors=True)


_worker = _HlrWorker()


def hlr_project_safe(shapes: list, origin, view_dir, x_dir,
                     include_hidden: bool = True) -> dict:
    return _worker.project(shapes, origin, view_dir, x_dir, include_hidden)


def _worker_streams():
    """The pipes the parent handed us, whatever the app thinks of them.

    An installed build is windowed and has no console, so PyInstaller leaves
    sys.stdin and sys.stdout as None. Fds 0 and 1 are real pipes all the same —
    the parent opened them — so the worker uses them directly. `closefd=False`
    because they are not ours to close.
    """
    # Not a context manager: these live as long as the worker does.
    stdin = (_sys.stdin if _sys.stdin is not None
             else open(0, closefd=False))              # noqa: SIM115
    stdout = (_sys.stdout if _sys.stdout is not None
              else open(1, "w", closefd=False))        # noqa: SIM115
    return stdin, stdout


def _worker_main():
    """Entry point of the isolated HLR worker process.

    A request per line of stdin, an answer per line of stdout; shapes travel
    as .brep files because they do not fit down a pipe."""
    from . import geometry
    from OCP.TopoDS import TopoDS_Iterator

    stdin, stdout = _worker_streams()
    for raw in stdin:
        try:
            req = _json.loads(raw)
            comp = occ.brep_read(req["in"])
            inputs = []
            it = TopoDS_Iterator(comp)
            while it.More():
                inputs.append(it.Value())
                it.Next()

            out = project_by_shape(inputs, req["origin"], req["view_dir"],
                                   req["x_dir"], req["include_hidden"])
            for i, vis in enumerate(out["visible_by_shape"]):
                if vis:
                    occ.brep_write(geometry.make_compound(vis),
                                   f"{req['vis']}{i}.brep")
            if out["hidden"]:
                occ.brep_write(geometry.make_compound(out["hidden"]),
                               req["hid"])
            stdout.write(f"ok {len(inputs)}\n")
        except Exception as exc:                              # noqa: BLE001
            stdout.write(f"err {type(exc).__name__}\n")
        stdout.flush()


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
