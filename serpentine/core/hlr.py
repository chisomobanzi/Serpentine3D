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


def dash_segments(polyline: np.ndarray, dash: float = 2.0,
                  gap: float = 1.2) -> np.ndarray:
    """Split a polyline into dash segment pairs (K,2,C) for hidden lines."""
    pts = polyline.astype(float)
    segs = []
    period = dash + gap
    dist_into = 0.0
    for a, b in zip(pts[:-1], pts[1:]):
        seg_len = float(np.linalg.norm(b - a))
        if seg_len < 1e-12:
            continue
        direction = (b - a) / seg_len
        t = 0.0
        while t < seg_len:
            phase = (dist_into + t) % period
            if phase < dash:
                run = min(dash - phase, seg_len - t)
                segs.append((a + direction * t, a + direction * (t + run)))
                t += run
            else:
                t += period - phase
        dist_into += seg_len
    if not segs:
        return np.zeros((0, 2, pts.shape[1]), np.float32)
    return np.asarray(segs, np.float32)
