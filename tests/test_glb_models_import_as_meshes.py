"""Binary glTF from other tools joins a drawing at its physical size.

Fixtures encode the published GLB wire format independently of Serpentine's
exporter, so complementary import/export mistakes cannot hide one another.
"""

import copy
import json
import math
import struct

import numpy as np
import pytest
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QUrl
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from serpentine3d import fileio
from serpentine3d.core import geometry as g
from serpentine3d.core.mesh import MeshShape
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


POSITIONS = np.array([(0, 0, 0), (2, 0, 0), (0, 3, 1)], dtype='<f4')


def _glb(path, doc, binary):
    """Write a genuine little-endian GLB 2.0 container."""
    doc = copy.deepcopy(doc)
    doc['buffers'] = [{'byteLength': len(binary)}]
    metadata = json.dumps(doc, separators=(',', ':')).encode()
    metadata += b' ' * (-len(metadata) % 4)
    binary += b'\0' * (-len(binary) % 4)
    path.write_bytes(struct.pack('<4sII', b'glTF', 2,
                                 28 + len(metadata) + len(binary))
                     + struct.pack('<I4s', len(metadata), b'JSON') + metadata
                     + struct.pack('<I4s', len(binary), b'BIN\0') + binary)
    return path


def _triangle(*, indexed=True):
    binary = POSITIONS.tobytes()
    doc = {
        'asset': {'version': '2.0'}, 'scene': 0,
        'scenes': [{'nodes': [0]}],
        'nodes': [{'mesh': 0, 'name': 'Survey marker'}],
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}}]}],
        'bufferViews': [{'buffer': 0, 'byteOffset': 0, 'byteLength': len(binary)}],
        'accessors': [{'bufferView': 0, 'componentType': 5126,
                       'count': 3, 'type': 'VEC3',
                       'min': [0, 0, 0], 'max': [2, 3, 1]}],
    }
    if indexed:
        doc['bufferViews'].append({'buffer': 0, 'byteOffset': len(binary),
                                   'byteLength': 6})
        binary += struct.pack('<3H', 0, 1, 2)
        doc['accessors'].append({'bufferView': 1, 'componentType': 5123,
                                 'count': 3, 'type': 'SCALAR'})
        doc['meshes'][0]['primitives'][0]['indices'] = 1
    return doc, binary


def _zup(points, scale=1):
    points = np.asarray(points, dtype=float)
    return np.column_stack((points[:, 0], -points[:, 2], points[:, 1])) * scale


@pytest.mark.parametrize(('units', 'scale'), [('mm', 1000), ('m', 1), ('in', 1000/25.4)])
@pytest.mark.parametrize('indexed', [True, False])
def test_external_glb_is_a_selectable_native_mesh_in_document_units(
        tmp_path, units, scale, indexed):
    path = _glb(tmp_path / 'external.glb', *_triangle(indexed=indexed))
    source = path.read_bytes()
    scene = Scene()
    scene.units = units
    existing = scene.add(g.make_line((0, 0, 0), (1, 0, 0)))

    assert fileio.import_file(scene, str(path)) == 1

    assert scene.get(existing.id) is existing
    obj = scene.all()[-1]
    assert isinstance(obj.shape, MeshShape) and obj.kind == 'mesh'
    assert obj.name == 'Survey marker'
    np.testing.assert_allclose(obj.shape.vertices, _zup(POSITIONS, scale))
    np.testing.assert_array_equal(obj.shape.triangles, [[0, 1, 2]])
    assert obj.mesh.has_faces
    selection = SelectionManager(scene)
    selection.set([obj.id])
    assert selection.objects() == [obj]
    assert path.read_bytes() == source
    assert scene.units == units


def test_default_scene_nested_trs_and_column_major_matrix_instances(tmp_path):
    doc, binary = _triangle()
    doc['scene'] = 1
    doc['scenes'] = [{'nodes': [3]}, {'nodes': [0, 2]}]
    q = math.sqrt(0.5)
    doc['nodes'] = [
        {'translation': [10, 20, 30], 'rotation': [0, 0, q, q], 'children': [1]},
        {'mesh': 0, 'name': 'Nested', 'translation': [1, 2, 3], 'scale': [2, 3, 4]},
        {'mesh': 0, 'name': 'Matrix instance',
         'matrix': [1, 0, 0, 0, 0, 2, 0, 0, 0, 0, 3, 0, 5, 6, 7, 1]},
        {'mesh': 0, 'name': 'Other scene', 'translation': [999, 0, 0]},
    ]
    scene = Scene()
    scene.units = 'm'
    assert fileio.import_file(scene, str(_glb(tmp_path/'instances.glb', doc, binary))) == 2
    objects = {obj.name: obj for obj in scene.all()}
    assert set(objects) == {'Nested', 'Matrix instance'}
    x, y, z = POSITIONS.T
    expected_nested = np.column_stack((8-3*y, 21+2*x, 33+4*z))
    np.testing.assert_allclose(objects['Nested'].shape.vertices, _zup(expected_nested), atol=1e-6)
    np.testing.assert_allclose(objects['Matrix instance'].shape.vertices,
                               _zup(POSITIONS * (1, 2, 3) + (5, 6, 7)))
    assert objects['Nested'].shape is not objects['Matrix instance'].shape


def test_primitive_materials_keep_colour_opacity_metal_and_roughness(tmp_path):
    doc, binary = _triangle()
    doc['materials'] = [
        {'name': 'Copper glass', 'alphaMode': 'BLEND',
         'pbrMetallicRoughness': {'baseColorFactor': [0.7, 0.3, 0.1, 0.4],
                                'metallicFactor': 0.8, 'roughnessFactor': 0.2}},
        {'pbrMetallicRoughness': {'baseColorFactor': [0.1, 0.2, 0.9, 0.25]}},
    ]
    primitive = doc['meshes'][0]['primitives'][0]
    primitive['material'] = 0
    doc['meshes'][0]['primitives'].append(dict(primitive, material=1))
    scene = Scene()
    assert fileio.import_file(scene, str(_glb(tmp_path/'materials.glb', doc, binary))) == 2
    objects = sorted(scene.all(), key=lambda obj: obj.material['metallic'])
    copper = next(obj for obj in objects if obj.material['metallic'] == pytest.approx(0.8))
    opaque = next(obj for obj in objects if obj is not copper)
    assert scene.render_color_of(copper) == pytest.approx((0.7, 0.3, 0.1))
    assert copper.material['opacity'] == pytest.approx(0.4)
    assert copper.material['roughness'] == pytest.approx(0.2)
    assert scene.render_color_of(opaque) == pytest.approx((0.1, 0.2, 0.9))
    assert opaque.material.get('opacity', 1) == pytest.approx(1), 'glTF defaults to OPAQUE'


def test_a_mirrored_instance_keeps_front_faces_and_normals_consistent(tmp_path):
    doc, binary = _triangle(indexed=False)
    normal = np.cross(POSITIONS[1]-POSITIONS[0], POSITIONS[2]-POSITIONS[0])
    normal /= np.linalg.norm(normal)
    normals = np.tile(normal, (3, 1)).astype('<f4')
    doc['bufferViews'].append({'buffer': 0, 'byteOffset': len(binary), 'byteLength': normals.nbytes})
    binary += normals.tobytes()
    doc['accessors'].append({'bufferView': 1, 'componentType': 5126, 'count': 3, 'type': 'VEC3'})
    doc['meshes'][0]['primitives'][0]['attributes']['NORMAL'] = 1
    doc['nodes'][0]['scale'] = [-2, 3, 4]
    scene = Scene()
    assert fileio.import_file(scene, str(_glb(tmp_path/'mirror.glb', doc, binary))) == 1
    shape = scene.all()[0].shape
    triangle = shape.vertices[shape.triangles[0]]
    facing = np.cross(triangle[1]-triangle[0], triangle[2]-triangle[0])
    facing /= np.linalg.norm(facing)
    expected = _zup([normal / (-2, 3, 4)])[0]
    expected /= np.linalg.norm(expected)
    np.testing.assert_allclose(facing, expected, atol=1e-6)
    if shape.normals is not None:
        np.testing.assert_allclose(shape.normals, np.tile(expected, (len(shape.vertices), 1)), atol=1e-6)


@pytest.mark.parametrize('storage', ['interleaved', 'sparse'])
def test_standard_accessor_layouts_produce_the_same_geometry(tmp_path, storage):
    doc, _ = _triangle(indexed=False)
    if storage == 'interleaved':
        # Prefix on both view and accessor; a normal-like padding field follows
        # every position. Reading contiguous float triples gives wrong results.
        binary = b'ABCD' + b'EFGH' + b''.join(
            struct.pack('<6f', *p, 7, 8, 9) for p in POSITIONS)
        doc['bufferViews'] = [{'buffer': 0, 'byteOffset': 4,
                              'byteLength': len(binary)-4, 'byteStride': 24}]
        doc['accessors'][0]['byteOffset'] = 4
    else:
        binary = bytes([0, 1, 2, 0]) + POSITIONS.tobytes()
        doc['bufferViews'] = [
            {'buffer': 0, 'byteOffset': 0, 'byteLength': 3},
            {'buffer': 0, 'byteOffset': 4, 'byteLength': 36},
        ]
        doc['accessors'][0].pop('bufferView')
        doc['accessors'][0]['sparse'] = {
            'count': 3, 'indices': {'bufferView': 0, 'componentType': 5121},
            'values': {'bufferView': 1}}
    scene = Scene()
    scene.units = 'm'
    assert fileio.import_file(scene, str(_glb(tmp_path/'accessor.glb', doc, binary))) == 1
    np.testing.assert_allclose(scene.all()[0].shape.vertices, _zup(POSITIONS))


@pytest.mark.parametrize(('mode', 'triangles'), [(5, [[0, 1, 2], [2, 1, 3]]),
                                               (6, [[0, 1, 2], [0, 2, 3]])])
def test_triangle_strips_and_fans_keep_their_winding(tmp_path, mode, triangles):
    doc, _ = _triangle(indexed=False)
    points = np.array([(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)], dtype='<f4')
    doc['bufferViews'][0]['byteLength'] = points.nbytes
    doc['accessors'][0].update(count=4, max=[1, 1, 0])
    doc['meshes'][0]['primitives'][0]['mode'] = mode
    scene = Scene()
    assert fileio.import_file(scene, str(_glb(tmp_path/'strip.glb', doc, points.tobytes()))) == 1
    shape = scene.all()[0].shape
    # Compare oriented geometry, allowing an importer to duplicate vertices.
    np.testing.assert_allclose(shape.vertices[shape.triangles],
                               _zup(points, 1000)[np.array(triangles)])


@pytest.mark.parametrize(('damage', 'reason'), [
    ('length', r'(?i)(length|truncat|container)'),
    ('index', r'(?i)(index|indices|range)'),
    ('accessor', r'(?i)(accessor|buffer|bounds|range)'),
    ('cycle', r'(?i)(cycle|cyclic|graph)'),
    ('missing-node', r'(?i)(node|graph|range)'),
    ('compression', r'(?i)(KHR_draco_mesh_compression|compression|extension)'),
])
def test_bad_files_report_the_cause_without_partly_importing(tmp_path, damage, reason):
    doc, binary = _triangle()
    if damage == 'index':
        binary = binary[:-6] + struct.pack('<3H', 0, 1, 99)
    elif damage == 'accessor':
        doc['accessors'][0]['count'] = 100
    elif damage == 'cycle':
        doc['nodes'][0]['children'] = [0]
    elif damage == 'missing-node':
        doc['nodes'][0]['children'] = [100]
    elif damage == 'compression':
        doc['extensionsRequired'] = ['KHR_draco_mesh_compression']
    # An earlier valid mesh makes partial mutation observable.
    doc['nodes'].insert(0, {'name': 'Earlier valid object', 'mesh': 0})
    if damage == 'cycle':
        doc['nodes'][1]['children'] = [1]
    doc['scenes'][0]['nodes'] = [0, 1]
    path = _glb(tmp_path/'broken.glb', doc, binary)
    if damage == 'length':
        path.write_bytes(path.read_bytes()[:-8])
    source = path.read_bytes()
    scene = Scene()
    existing = scene.add(g.make_box((0, 0, 0), 2, 3, 4))
    with pytest.raises(ValueError, match=reason):
        fileio.import_file(scene, str(path))
    assert scene.all() == [existing]
    assert g.volume(existing.shape) == pytest.approx(24)
    assert path.read_bytes() == source


def test_cancelling_after_reading_begins_preserves_existing_scene(tmp_path):
    doc, binary = _triangle()
    doc['nodes'] *= 20
    doc['scenes'][0]['nodes'] = list(range(20))
    path = _glb(tmp_path/'cancel.glb', doc, binary)
    scene = Scene()
    existing = scene.add(g.make_line((0, 0, 0), (1, 0, 0)))
    seen = []

    def cancel(fraction, message):
        seen.append(fraction)
        return fraction == 0

    with pytest.raises(fileio.Cancelled):
        fileio.import_file(scene, str(path), progress=cancel)
    assert any(0 < f < 1 for f in seen), 'Must offer cancellation before scene commit'
    assert scene.all() == [existing]


@pytest.mark.parametrize('units', ['mm', 'm', 'in'])
def test_exported_glb_uses_metres_and_round_trips_at_original_size(tmp_path, units):
    scene = Scene()
    scene.units = units
    original = scene.add(MeshShape([(0, 0, 0), (2, 0, 0), (0, 3, 1)], [[0, 1, 2]]),
                         name='Physical triangle')
    path = tmp_path/'roundtrip.glb'
    fileio.export_file(scene, str(path))
    raw = path.read_bytes()
    json_length = struct.unpack_from('<I', raw, 12)[0]
    doc = json.loads(raw[20:20+json_length])
    accessor = doc['accessors'][doc['meshes'][0]['primitives'][0]['attributes']['POSITION']]
    view = doc['bufferViews'][accessor['bufferView']]
    offset = 28 + json_length + view.get('byteOffset', 0) + accessor.get('byteOffset', 0)
    first_edge_end = struct.unpack_from('<3f', raw, offset + 12)
    metre_scale = {'mm': 0.001, 'm': 1, 'in': 0.0254}[units]
    assert first_edge_end == pytest.approx((2*metre_scale, 0, 0))
    restored = Scene()
    restored.units = units
    assert fileio.import_file(restored, str(path)) == 1
    assert restored.all()[0].name == original.name
    np.testing.assert_allclose(restored.all()[0].shape.vertices,
                               original.shape.vertices, atol=1e-6)


@pytest.fixture
def window(monkeypatch):
    from serpentine3d.app import MainWindow
    win = MainWindow()
    win.resize(1200, 800)
    win.viewport.resize(640, 480)
    win.import_warnings = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda parent, title, text:
                        win.import_warnings.append((title, text)))
    try:
        yield win
    finally:
        if win.processor.busy:
            win.processor.cancel()
        win.mark_saved()
        win.close()


def test_glb_is_offered_in_both_import_chooser_filters():
    assert '.glb' in fileio.IMPORT_EXTS
    assert '*.glb' in fileio.import_filter()
    assert '*.glb' in fileio.import_filter(pictures=True)


@pytest.mark.parametrize('entry', ['menu', 'drop', 'uppercase-drop'])
def test_glb_import_menu_and_model_drop_are_one_undoable_addition(window, tmp_path, monkeypatch, entry):
    path = _glb(tmp_path/('A model.GLB' if entry == 'uppercase-drop' else 'A model.glb'),
                *_triangle())
    source = path.read_bytes()
    existing = window.scene.add(g.make_box((80, 0, 0), 2, 3, 4))
    window.ctx.current_path = 'Working drawing.serp'
    window.mark_saved()
    if entry == 'menu':
        monkeypatch.setattr(window, '_pick_file', lambda **kwargs: str(path))
        window._file_import()
    else:
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(str(path))])
        enter = QDragEnterEvent(QPoint(320, 240), Qt.DropAction.CopyAction, mime,
                                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(window.viewport, enter)
        assert enter.isAccepted(), 'GLB must be accepted over the model viewport'
        drop = QDropEvent(QPointF(320, 240), Qt.DropAction.CopyAction, mime,
                          Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(window.viewport, drop)
        assert drop.isAccepted() and drop.dropAction() == Qt.DropAction.CopyAction
        QApplication.processEvents()
    assert not window.import_warnings, window.import_warnings
    assert len(window.scene.all()) == 2
    assert window.scene.all()[-1].kind == 'mesh'
    assert window.ctx.current_path == 'Working drawing.serp'
    assert path.read_bytes() == source
    assert window.dirty and window.history.can_undo
    window.history.undo()
    assert [obj.id for obj in window.scene.all()] == [existing.id]
    assert not window.history.can_undo
