"""E57 survey stations import as positioned, coloured point clouds.

Fixtures are real ASTM E57 files written by libE57, including coordinate and
colour encodings that the convenience pye57 writer cannot generate.
"""

from __future__ import annotations

import math

import numpy as np
import pye57
import pytest
from pye57 import libe57

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.fileio import (
    Cancelled, EXPORT_EXTS, IMPORT_EXTS, export_filter, import_file,
    import_filter, native,
)


def _scan(name, xyz, *, rgb=None, invalid=None, spherical=False,
          color_max=255, rotation=None, translation=None):
    coords = np.asarray(xyz, dtype=np.float64).reshape(-1, 3)
    keys = (('sphericalRange', 'sphericalAzimuth', 'sphericalElevation')
            if spherical else ('cartesianX', 'cartesianY', 'cartesianZ'))
    fields = {key: coords[:, i].copy() for i, key in enumerate(keys)}
    if rgb is not None:
        colors = np.asarray(rgb, dtype=np.float64)
        fields.update({key: colors[:, i].copy() for i, key in enumerate(
            ('colorRed', 'colorGreen', 'colorBlue'))})
    if invalid is not None:
        key = 'sphericalInvalidState' if spherical else 'cartesianInvalidState'
        fields[key] = np.asarray(invalid, dtype=np.float64)
    return dict(name=name, fields=fields, color_max=color_max,
                rotation=rotation, translation=translation)


def _write_e57(path, *scans):
    """Write and independently decode the fixture, before testing the app."""
    with pye57.E57(str(path), mode='w') as e57:
        f = e57.image_file
        for i, scan in enumerate(scans):
            node = libe57.StructureNode(f)
            node.set('guid', libe57.StringNode(f, f'test-station-{i}'))
            node.set('name', libe57.StringNode(f, scan['name']))
            if scan['rotation'] is not None or scan['translation'] is not None:
                pose = libe57.StructureNode(f)
                rotation = libe57.StructureNode(f)
                for key, value in zip('wxyz', scan['rotation'] or (1, 0, 0, 0)):
                    rotation.set(key, libe57.FloatNode(f, float(value)))
                translation = libe57.StructureNode(f)
                for key, value in zip('xyz', scan['translation'] or (0, 0, 0)):
                    translation.set(key, libe57.FloatNode(f, float(value)))
                pose.set('rotation', rotation)
                pose.set('translation', translation)
                node.set('pose', pose)
            if 'colorRed' in scan['fields']:
                limits = libe57.StructureNode(f)
                for color in ('Red', 'Green', 'Blue'):
                    limits.set(f'color{color}Minimum', libe57.IntegerNode(f, 0))
                    limits.set(f'color{color}Maximum',
                               libe57.IntegerNode(f, scan['color_max']))
                node.set('colorLimits', limits)
            prototype = libe57.StructureNode(f)
            buffers = libe57.VectorSourceDestBuffer()
            count = len(next(iter(scan['fields'].values())))
            for key, array in scan['fields'].items():
                if key.startswith('color'):
                    field = libe57.IntegerNode(f, 0, 0, scan['color_max'])
                elif key.endswith('InvalidState'):
                    field = libe57.IntegerNode(f, 0, 0, 2)
                else:
                    field = libe57.FloatNode(f)
                prototype.set(key, field)
                if count:
                    buffers.append(libe57.SourceDestBuffer(
                        f, key, array, count, True, True))
            points = libe57.CompressedVectorNode(
                f, prototype, libe57.VectorNode(f, True))
            node.set('points', points)
            e57.data3d.append(node)
            if count:
                writer = points.writer(buffers)
                writer.write(count)
                writer.close()
    # Verify these uncommon encodings are readable by the independent library.
    with pye57.E57(str(path)) as e57:
        assert e57.scan_count == len(scans)
        for i, scan in enumerate(scans):
            header = e57.get_header(i)
            expected_count = len(next(iter(scan['fields'].values())))
            assert header.point_count == expected_count
            if not expected_count:
                continue
            arrays = {key: np.empty_like(values)
                      for key, values in scan['fields'].items()}
            buffers = libe57.VectorSourceDestBuffer()
            for key, array in arrays.items():
                buffers.append(libe57.SourceDestBuffer(
                    e57.image_file, key, array, expected_count, True, True))
            reader = header.points.reader(buffers)
            assert reader.read() == expected_count
            reader.close()
            for key, array in arrays.items():
                np.testing.assert_array_equal(array, scan['fields'][key])
    return str(path)


@pytest.mark.parametrize(('units', 'scale'), [('mm', 1000), ('m', 1)])
def test_stations_keep_names_pose_units_colors_and_native_round_trip(tmp_path, units, scale):
    path = _write_e57(
        tmp_path / 'survey.E57',
        _scan('Entrance', [[1, 0, 0], [9, 9, 9], [0, 2, 1]],
              rgb=[[255, 0, 0], [23, 45, 67], [0, 128, 255]],
              invalid=[0, 1, 0],
              rotation=(math.sqrt(0.5), 0, 0, math.sqrt(0.5)),
              translation=(10, 20, 30)),
        _scan('Stairs', [[-1, 0, 2], [0, 1, 0]], translation=(3, 0, 1)),
    )
    scene = Scene()
    scene.units = units
    assert import_file(scene, path) == 2
    first, second = scene.all()
    assert [first.name, second.name] == ['Entrance', 'Stairs']
    assert first.kind == second.kind == 'pointcloud'
    np.testing.assert_allclose(first.shape.xyz,
                               np.array([[10, 21, 30], [8, 20, 31]]) * scale)
    np.testing.assert_array_equal(first.shape.rgb, [[255, 0, 0], [0, 128, 255]])
    assert first.shape.rgb.dtype == np.uint8
    np.testing.assert_allclose(second.shape.xyz,
                               np.array([[2, 0, 3], [3, 1, 1]]) * scale)
    assert second.shape.rgb is None
    saved = str(tmp_path / 'imported.serp')
    native.save_scene(scene, saved)
    restored = Scene()
    native.load_scene(restored, saved)
    assert restored.units == units
    for original, back in zip(scene.all(), restored.all()):
        assert back.name == original.name and back.kind == 'pointcloud'
        np.testing.assert_array_equal(back.shape.xyz, original.shape.xyz)
        np.testing.assert_array_equal(back.shape.rgb, original.shape.rgb)


def test_spherical_scan_converts_pose_and_normalizes_16_bit_rgb(tmp_path):
    path = _write_e57(tmp_path / 'spherical.e57', _scan(
        'Tripod', [[2, 0, 0], [3, math.pi / 2, 0], [4, 0, math.pi / 2]],
        spherical=True, invalid=[0, 2, 0],
        rgb=[[65535, 0, 32768], [100, 200, 300], [0, 65535, 65535]],
        color_max=65535, translation=(1, 2, 3)))
    scene = Scene()
    scene.units = 'm'
    assert import_file(scene, path) == 1
    cloud = scene.all()[0].shape
    np.testing.assert_allclose(cloud.xyz, [[3, 2, 3], [1, 2, 7]], atol=1e-6)
    np.testing.assert_allclose(cloud.rgb, [[255, 0, 128], [0, 255, 255]], atol=1)
    assert cloud.rgb.dtype == np.uint8


def test_nonfinite_samples_are_removed_with_their_colors(tmp_path):
    path = _write_e57(tmp_path / 'finite.e57', _scan(
        'Scan', [[1, 2, 3], [np.nan, 0, 0], [0, np.inf, 0], [4, 5, 6]],
        rgb=[[1, 2, 3], [4, 5, 6], [7, 8, 9], [10, 11, 12]]))
    scene = Scene()
    scene.units = 'm'
    assert import_file(scene, path) == 1
    np.testing.assert_array_equal(scene.all()[0].shape.xyz, [[1, 2, 3], [4, 5, 6]])
    np.testing.assert_array_equal(scene.all()[0].shape.rgb, [[1, 2, 3], [10, 11, 12]])


@pytest.mark.parametrize('empty_kind', ['zero-points', 'all-invalid', 'no-scans'])
def test_empty_point_data_reports_why_and_adds_no_partial_stations(tmp_path, empty_kind):
    scans = []
    if empty_kind != 'no-scans':
        scans.append(_scan('Good first station', [[1, 2, 3]]))
        scans.append(_scan('Empty station', [] if empty_kind == 'zero-points'
                           else [[1, 2, 3]],
                           invalid=None if empty_kind == 'zero-points' else [1]))
    path = _write_e57(tmp_path / 'empty.e57', *scans)
    scene = Scene()
    original = scene.add(g.make_line((0, 0, 0), (1, 0, 0)), name='Existing')
    with pytest.raises(ValueError, match=r'(?i)(empty|no .*points|no .*scans|no .*data|valid points)'):
        import_file(scene, path)
    assert scene.all() == [original]


def test_malformed_e57_is_reported_without_changing_the_scene(tmp_path):
    path = tmp_path / 'broken.e57'
    path.write_bytes(b'This is not an E57 file.\x00')
    scene = Scene()
    original = scene.add(g.make_line((0, 0, 0), (1, 0, 0)))
    with pytest.raises(ValueError, match=r'(?i)(invalid|malformed|read|open).*e57|e57.*(invalid|malformed|read|open)'):
        import_file(scene, str(path))
    assert scene.all() == [original]


def test_cancel_during_multi_station_read_leaves_existing_scene_unchanged(tmp_path):
    path = _write_e57(tmp_path / 'cancel.e57',
                      *[_scan(f'Station {i}', [[i, 0, 0]]) for i in range(3)])
    scene = Scene()
    original = scene.add(g.make_line((0, 0, 0), (1, 0, 0)))
    updates = []

    def cancel_after_work_begins(fraction, message):
        updates.append((fraction, message))
        return not 0 < fraction < 1

    with pytest.raises(Cancelled):
        import_file(scene, path, progress=cancel_after_work_begins)
    assert any(0 < fraction < 1 for fraction, _ in updates)
    assert scene.all() == [original]


def test_e57_is_offered_for_import_and_drop_but_not_export():
    assert '.e57' in IMPORT_EXTS
    assert '*.e57' in import_filter()
    assert '*.e57' in import_filter(pictures=True)
    assert '.e57' not in EXPORT_EXTS
    assert '*.e57' not in export_filter()
