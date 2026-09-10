"""ASTM E57 scans as native point clouds, positioned in document units."""

from pathlib import Path

import numpy as np
import pye57
from pye57 import libe57

from ..core.pointcloud import PointCloudShape
from ..utils.units import convert
from .progress import Cancelled, Progress


_CARTESIAN = ("cartesianX", "cartesianY", "cartesianZ")
_SPHERICAL = ("sphericalRange", "sphericalAzimuth", "sphericalElevation")
_COLORS = ("colorRed", "colorGreen", "colorBlue")
_CHUNK_POINTS = 262_144


def _color_limits(header):
    """Use declared limits, including scaled prototypes, rather than sample maxima."""
    prototype = libe57.StructureNode(header.points.prototype())
    limits = []
    for field in _COLORS:
        low_path, high_path = f"colorLimits/{field}Minimum", f"colorLimits/{field}Maximum"
        if header.node.isDefined(low_path) and header.node.isDefined(high_path):
            low, high = header.node[low_path].value(), header.node[high_path].value()
        else:
            node = prototype[field]
            if isinstance(node, libe57.ScaledIntegerNode):
                low, high = node.scaledMinimum(), node.scaledMaximum()
            else:
                low, high = node.minimum(), node.maximum()
        if not np.isfinite([low, high]).all() or high <= low:
            raise ValueError("Invalid E57 color limits")
        limits.append((low, high))
    return np.array(limits).T


def _pose(header):
    # E57 structure field order is unspecified; read quaternion components by
    # name. Rotation and translation are independently optional.
    rotation = np.eye(3)
    translation = np.zeros(3)
    if header.node.isDefined("pose/rotation"):
        node = header.node["pose/rotation"]
        quat = np.array([node[key].value() for key in "wxyz"])
        norm = np.linalg.norm(quat)
        if not np.isfinite(norm) or norm == 0:
            raise ValueError("Invalid E57 scan rotation")
        w, x, y, z = quat / norm
        rotation = np.array([
            [1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)],
            [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)],
            [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)],
        ])
    if header.node.isDefined("pose/translation"):
        node = header.node["pose/translation"]
        translation = np.array([node[key].value() for key in "xyz"])
        if not np.isfinite(translation).all():
            raise ValueError("Invalid E57 scan translation")
    return rotation, translation


def _read_scan(source, header, scale, report, label):
    count = header.point_count
    if not count:
        raise ValueError(f"E57 scan {label!r} is empty (no points)")
    fields = set(header.point_fields)
    if set(_CARTESIAN) <= fields:
        coordinates, invalid = _CARTESIAN, "cartesianInvalidState"
    elif set(_SPHERICAL) <= fields:
        coordinates, invalid = _SPHERICAL, "sphericalInvalidState"
    else:
        raise ValueError(f"Cannot read E57 scan {label!r}: no supported coordinates")
    colored = set(_COLORS) <= fields
    wanted = list(coordinates)
    if invalid in fields:
        wanted.append(invalid)
    if colored:
        wanted.extend(_COLORS)
        low, high = _color_limits(header)
        if "colorInvalidState" in fields:
            wanted.append("colorInvalidState")
    rotation, translation = _pose(header)
    capacity = min(count, _CHUNK_POINTS)
    data = {field: np.empty(capacity, np.float64) for field in wanted}
    buffers = libe57.VectorSourceDestBuffer()
    for field, array in data.items():
        # Float64 accepts integer, float and scaled-integer encodings. The
        # convenience reader's uint8 colors overflow on 16-bit scan colors.
        buffers.append(libe57.SourceDestBuffer(
            source.image_file, field, array, capacity, True, True))
    xyz = np.empty((count, 3), np.float32)
    rgb = np.empty((count, 3), np.uint8) if colored else None
    read_count = kept = 0
    reader = header.points.reader(buffers)
    try:
        while read_count < count:
            report(read_count / count, f"Reading {label} ({read_count:,}/{count:,} points)")
            size = reader.read()
            if not size:
                raise ValueError(f"Cannot read E57 scan {label!r}: incomplete point data")
            points = np.column_stack([data[field][:size] for field in coordinates])
            valid = np.isfinite(points).all(axis=1)
            if invalid in data:
                valid &= data[invalid][:size] == 0
            if coordinates == _SPHERICAL:
                distance, azimuth, elevation = points.T
                valid &= distance >= 0
                with np.errstate(invalid="ignore"):
                    horizontal = distance * np.cos(elevation)
                    points = np.column_stack((horizontal * np.cos(azimuth),
                                              horizontal * np.sin(azimuth),
                                              distance * np.sin(elevation)))
            with np.errstate(over="ignore", invalid="ignore"):
                points = ((points @ rotation.T + translation) * scale).astype(np.float32)
            valid &= np.isfinite(points).all(axis=1)
            length = np.count_nonzero(valid)
            xyz[kept:kept + length] = points[valid]
            if colored:
                colors = np.column_stack([data[field][:size] for field in _COLORS])[valid]
                good = np.isfinite(colors).all(axis=1)
                if "colorInvalidState" in data:
                    good &= data["colorInvalidState"][:size][valid] == 0
                colors[~good] = high
                rgb[kept:kept + length] = np.rint(
                    np.clip((colors - low) / (high - low), 0, 1) * 255).astype(np.uint8)
            kept += length
            read_count += size
        report(1.0, f"Read {label}: {kept:,} valid points")
    finally:
        reader.close()
    if not kept:
        raise ValueError(f"E57 scan {label!r} has no valid points")
    # Release space occupied by invalid records without retaining the full
    # backing allocation through a sliced view.
    xyz.resize((kept, 3), refcheck=False)
    if colored:
        rgb.resize((kept, 3), refcheck=False)
    return PointCloudShape(xyz, rgb)


def import_e57(path: str, *, units: str = "mm", progress=None) -> list:
    """Read every station before returning; callers can add them atomically."""
    report = Progress(progress)
    result = []
    try:
        with pye57.E57(str(path)) as source:
            if not source.scan_count:
                raise ValueError("E57 file has no scans")
            scale = convert(1.0, "m", units)
            for index in range(source.scan_count):
                header = source.get_header(index)
                name = (header.node["name"].value().strip()
                        if header.node.isDefined("name") else "")
                name = name or f"{Path(path).stem} {index + 1:02d}"
                scan_progress = report.part(index / source.scan_count,
                                            (index + 1) / source.scan_count)
                result.append((name, _read_scan(source, header, scale, scan_progress, name)))
    except Cancelled:
        raise
    except Exception as exc:
        raise ValueError(f"Cannot read E57 file {Path(path).name!r}: {exc}") from exc
    return result
