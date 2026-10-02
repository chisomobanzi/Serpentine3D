"""Projected drawing curves remain safe to select and measure (#55)."""

import math
import os
from pathlib import Path
import subprocess
import sys

import pytest

from serpentine3d.core import geometry as g, hlr, occ


def _legacy_projection():
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
    algo = HLRBRep_Algo()
    algo.Add(g.make_torus((0, 0, 0), 10, 3))
    algo.Projector(hlr._projector((0, 0, 0), (1, 1, 1), (1, -1, 0)))
    algo.Update()
    algo.Hide()
    convert = HLRBRep_HLRToShape(algo)
    return g.make_compound(g.edges_of(convert.VCompound())
                           + g.edges_of(convert.OutLineVCompound()))


def test_building_native_curves_preserves_the_projected_drawing():
    shape = _legacy_projection()
    edges = g.edges_of(shape)
    before = []
    parameters = []
    for edge in edges:
        adaptor = occ.edge_adaptor(edge)
        first, last = adaptor.FirstParameter(), adaptor.LastParameter()
        ts = [first + (last - first) * i / 20 for i in range(21)]
        parameters.append(ts)
        before.append([g.pnt_tuple(adaptor.Value(t)) for t in ts])
    occ.ensure_curves3d(shape)
    for edge, ts, points in zip(edges, parameters, before):
        adaptor = occ.edge_adaptor(edge)
        after = [g.pnt_tuple(adaptor.Value(t)) for t in ts]
        for actual, expected in zip(after, points):
            assert actual == pytest.approx(expected, abs=1e-7)


def test_legitimate_degenerate_sphere_edges_still_measure():
    props = occ.linear_properties(g.make_sphere((0, 0, 0), 10))
    assert math.isfinite(props.Mass()) and props.Mass() > 0


def test_unreconstructable_geometry_is_rejected_before_native_measurement(monkeypatch):
    from OCP.Standard import Standard_NullObject
    from types import SimpleNamespace
    edge = occ.TopoDS_Edge()
    occ.BRep_Builder().MakeEdge(edge)

    def unsafe(*args):
        pytest.fail('Invalid curves reached the native measurement routine')

    monkeypatch.setattr(occ, 'BRepGProp', SimpleNamespace(LinearProperties_s=unsafe))
    # Native reconstruction rejects a completely empty edge itself; a
    # partial reconstruction is rejected by our explicit missing-curve check.
    with pytest.raises((ValueError, Standard_NullObject)):
        occ.linear_properties(edge)


@pytest.mark.parametrize('project', [hlr.hlr_project, hlr.project_by_shape,
                                    hlr.hlr_project_safe])
def test_projected_curved_edges_have_geometry_native_tools_can_read(project):
    result = project([g.make_torus((0, 0, 0), 10, 3)],
                     origin=(0, 0, 0), view_dir=(1, 1, 1), x_dir=(1, -1, 0))
    edges = result['visible'] + result['outline'] + result['hidden']
    assert edges
    for edge in edges:
        curve = occ.BRep_Tool.Curve_s(edge, 0., 0.)
        assert curve is not None, 'Projected curves need a native 3D representation'
        adaptor = occ.edge_adaptor(edge)
        for t in (adaptor.FirstParameter(), adaptor.LastParameter()):
            point = curve.Value(t)
            assert math.isfinite(point.X()) and math.isfinite(point.Y())
            assert point.Z() == pytest.approx(0., abs=1e-9)
    assert g.curve_length(g.make_compound(edges)) > 0


@pytest.mark.parametrize('operation', ['selection', 'length', 'centroid'])
def test_old_saved_projection_curves_do_not_crash_native_consumers(tmp_path, operation):
    # Keep a regression in C++ from bringing down pytest itself. The input is
    # deliberately old-style HLR output, bypassing our repaired projection API.
    code = r'''
import faulthandler, math, os, sys
if sys.platform != 'win32':
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
faulthandler.enable()
from PySide6.QtWidgets import QApplication
app = QApplication([])
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from serpentine3d.core import geometry as g, hlr, occ
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.core.history import History
from serpentine3d.ui.properties import PropertiesPanel
from serpentine3d.fileio.step import export_step, import_step
export_step([g.make_torus((0, 0, 0), 10, 3)], 'torus.step')
source = import_step('torus.step')[0]
algo = HLRBRep_Algo()
algo.Add(source)
algo.Projector(hlr._projector((0, 0, 0), (1, 1, 1), (1, -1, 0)))
algo.Update()
algo.Hide()
convert = HLRBRep_HLRToShape(algo)
raw = g.make_compound(g.edges_of(convert.VCompound())
                      + g.edges_of(convert.OutLineVCompound()))
assert any(occ.BRep_Tool.Curve_s(edge, 0., 0.) is None
           for edge in g.edges_of(raw))
occ.brep_write(raw, 'old-drawing.brep')
shape = occ.brep_read('old-drawing.brep')
operation = sys.argv[1]
if operation == 'length':
    assert g.curve_length(shape) > 0
elif operation == 'centroid':
    assert all(math.isfinite(v) for v in g.centroid(shape))
else:
    scene = Scene()
    selection = SelectionManager(scene)
    panel = PropertiesPanel(scene, selection, History(scene))
    obj = scene.add(shape, name='Old Make2D drawing')
    selection.set([obj.id])
    app.processEvents()
    assert panel.header.text() == obj.name
    assert panel.measure_label.text().startswith('Length:'), panel.measure_label.text()
print('native operation survived', operation)
'''
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PYTHONPATH=str(root), QT_QPA_PLATFORM='offscreen',
               SERP3D_CONFIG=str(tmp_path / 'settings.json'))
    result = subprocess.run([sys.executable, '-c', code, operation], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'native operation survived' in result.stdout
