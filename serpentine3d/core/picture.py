"""A planar picture, optionally cut to a face, with its original pixel mapping."""
import base64
import copy
import json
import numpy as np
from .mesh import MeshShape

PICTURE_TAG = b"SERPPICTURE1\0"


class PictureShape(MeshShape):
    def __init__(self, plane):
        self.plane = copy.deepcopy(plane)
        o, u, v = (np.asarray(plane[key], float) for key in ("origin", "u", "v"))
        self._face = None
        if plane.get("region_brep"):
            from . import geometry
            from .mesh import mesh_from_brep
            self._face = geometry.shape_from_bytes(base64.b64decode(plane["region_brep"]))
            mesh = mesh_from_brep(self._face)
            super().__init__(mesh.vertices, mesh.triangles)
        else:
            super().__init__([o, o + u, o + u + v, o + v], [[0, 1, 2], [0, 2, 3]])
        # Keep the source rectangle's basis after a cut: fitting UVs to each
        # piece's bounds would stretch the complete image onto every piece.
        self.uv = np.linalg.lstsq(np.column_stack((u, v)),
                                 (self.vertices - o).T, rcond=None)[0].T

    def face(self):
        """The exact visible region, including curved cuts and inner holes."""
        if self._face is None:
            from . import geometry
            self._face = geometry.planar_face(
                geometry.make_polyline(self.vertices.tolist(), closed=True))
        return self._face

    def with_region(self, face):
        from . import geometry
        plane = dict(self.plane)
        plane["region_brep"] = base64.b64encode(
            geometry.shape_to_bytes(face)).decode("ascii")
        return PictureShape(plane)

    def transformed(self, matrix):
        matrix = np.asarray(matrix, float)
        plane = dict(self.plane)
        linear = matrix[:3, :3]
        offset = matrix[:3, 3] if matrix.shape == (4, 4) else np.zeros(3)
        plane.update(origin=(linear @ np.asarray(plane["origin"]) + offset).tolist(),
                     u=(linear @ np.asarray(plane["u"])).tolist(),
                     v=(linear @ np.asarray(plane["v"])).tolist())
        if plane.get("region_brep"):
            from . import geometry
            affine = np.eye(4)
            affine[:3, :3], affine[:3, 3] = linear, offset
            plane["region_brep"] = base64.b64encode(geometry.shape_to_bytes(
                geometry.apply_matrix(self.face(), affine))).decode("ascii")
        return PictureShape(plane)

    def translated(self, offset):
        matrix = np.eye(4)
        matrix[:3, 3] = offset
        return self.transformed(matrix)

    def copy(self):
        return PictureShape(self.plane)

    def to_bytes(self):
        plane = dict(self.plane)
        data = plane.get("image_data")
        if data is not None:
            plane["image_data"] = base64.b64encode(data).decode("ascii")
        return PICTURE_TAG + json.dumps(plane).encode("utf-8")

    @classmethod
    def from_bytes(cls, data):
        plane = json.loads(data[len(PICTURE_TAG):])
        if plane.get("image_data") is not None:
            plane["image_data"] = base64.b64decode(plane["image_data"])
        return cls(plane)
