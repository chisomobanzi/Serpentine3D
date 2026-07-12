"""3D OpenGL viewport: rendering, navigation, picking."""

from __future__ import annotations

import ctypes

import numpy as np
from OpenGL import GL
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget

from ..utils.math3d import ray_plane, ray_triangle_hits
from . import theme
from .camera import Camera

PICK_RADIUS_PX = 7.0

MESH_VERT = """
#version 330 core
layout(location=0) in vec3 pos;
layout(location=1) in vec3 nrm;
uniform mat4 uMVP;
uniform mat4 uView;
out vec3 vNormal;
out vec3 vPosView;
void main() {
    gl_Position = uMVP * vec4(pos, 1.0);
    vNormal = mat3(uView) * nrm;
    vPosView = (uView * vec4(pos, 1.0)).xyz;
}
"""

MESH_FRAG = """
#version 330 core
in vec3 vNormal;
in vec3 vPosView;
uniform vec3 uColor;
uniform float uAlpha;
out vec4 frag;
void main() {
    vec3 n = normalize(vNormal);
    if (!gl_FrontFacing) n = -n;
    vec3 l = normalize(-vPosView);
    float diff = max(dot(n, l), 0.0);
    vec3 base = uColor * (0.30 + 0.70 * diff);
    float spec = pow(max(dot(reflect(-l, n), l), 0.0), 48.0) * 0.18;
    frag = vec4(base + vec3(spec), uAlpha);
}
"""

LINE_VERT = """
#version 330 core
layout(location=0) in vec3 pos;
uniform mat4 uMVP;
void main() { gl_Position = uMVP * vec4(pos, 1.0); }
"""

LINE_FRAG = """
#version 330 core
uniform vec4 uColor;
out vec4 frag;
void main() { frag = uColor; }
"""

BG_VERT = """
#version 330 core
layout(location=0) in vec2 pos;
out float vY;
void main() { vY = pos.y * 0.5 + 0.5; gl_Position = vec4(pos, 0.999, 1.0); }
"""

BG_FRAG = """
#version 330 core
in float vY;
uniform vec3 uTop;
uniform vec3 uBottom;
out vec4 frag;
void main() { frag = vec4(mix(uBottom, uTop, vY), 1.0); }
"""


def set_default_gl_format():
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    fmt.setSamples(4)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)


def _compile(vert_src: str, frag_src: str) -> int:
    def sh(kind, src):
        s = GL.glCreateShader(kind)
        GL.glShaderSource(s, src)
        GL.glCompileShader(s)
        if not GL.glGetShaderiv(s, GL.GL_COMPILE_STATUS):
            raise RuntimeError(GL.glGetShaderInfoLog(s).decode())
        return s

    prog = GL.glCreateProgram()
    vs, fs = sh(GL.GL_VERTEX_SHADER, vert_src), sh(GL.GL_FRAGMENT_SHADER, frag_src)
    GL.glAttachShader(prog, vs)
    GL.glAttachShader(prog, fs)
    GL.glLinkProgram(prog)
    if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
        raise RuntimeError(GL.glGetProgramInfoLog(prog).decode())
    GL.glDeleteShader(vs)
    GL.glDeleteShader(fs)
    return prog


class _GpuObject:
    """GPU buffers for one scene object."""

    def __init__(self, mesh):
        self.mesh_id = id(mesh)
        self.tri_vao = self.tri_count = 0
        self.line_vao = self.line_count = 0
        self._buffers = []
        if mesh.has_faces:
            inter = np.hstack([mesh.vertices, mesh.normals]).astype(np.float32)
            self.tri_vao = GL.glGenVertexArrays(1)
            GL.glBindVertexArray(self.tri_vao)
            vbo = GL.glGenBuffers(1)
            self._buffers.append(vbo)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, inter.nbytes, inter,
                            GL.GL_STATIC_DRAW)
            GL.glEnableVertexAttribArray(0)
            GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, False, 24,
                                     ctypes.c_void_p(0))
            GL.glEnableVertexAttribArray(1)
            GL.glVertexAttribPointer(1, 3, GL.GL_FLOAT, False, 24,
                                     ctypes.c_void_p(12))
            ebo = GL.glGenBuffers(1)
            self._buffers.append(ebo)
            idx = mesh.triangles.astype(np.uint32)
            GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, ebo)
            GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx,
                            GL.GL_STATIC_DRAW)
            self.tri_count = idx.size
        if len(mesh.edge_segments):
            pts = mesh.edge_segments.reshape(-1, 3).astype(np.float32)
            self.line_vao = GL.glGenVertexArrays(1)
            GL.glBindVertexArray(self.line_vao)
            vbo = GL.glGenBuffers(1)
            self._buffers.append(vbo)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, pts.nbytes, pts,
                            GL.GL_STATIC_DRAW)
            GL.glEnableVertexAttribArray(0)
            GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, False, 0,
                                     ctypes.c_void_p(0))
            self.line_count = len(pts)
        GL.glBindVertexArray(0)

    def release(self):
        for vao in (self.tri_vao, self.line_vao):
            if vao:
                GL.glDeleteVertexArrays(1, [vao])
        if self._buffers:
            GL.glDeleteBuffers(len(self._buffers), self._buffers)
        self._buffers = []
        self.tri_vao = self.line_vao = 0


class _LineBatch:
    """Dynamic line VAO for grid / previews."""

    def __init__(self, points: np.ndarray, dynamic: bool = False):
        self.count = len(points)
        self.vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self.vao)
        self.vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        usage = GL.GL_DYNAMIC_DRAW if dynamic else GL.GL_STATIC_DRAW
        data = points.astype(np.float32)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, max(data.nbytes, 12), data, usage)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, False, 0,
                                 ctypes.c_void_p(0))
        GL.glBindVertexArray(0)

    def update(self, points: np.ndarray):
        data = points.astype(np.float32)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self.vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, max(data.nbytes, 12), data,
                        GL.GL_DYNAMIC_DRAW)
        self.count = len(data)

    def release(self):
        GL.glDeleteVertexArrays(1, [self.vao])
        GL.glDeleteBuffers(1, [self.vbo])


class Viewport(QOpenGLWidget):
    objectClicked = Signal(str, object)     # object id, modifiers
    emptyClicked = Signal(object)           # modifiers
    pointPicked = Signal(object)            # (x, y, z) in point-input mode
    mouseWorldMoved = Signal(object)        # (x, y, z) while in point-input mode
    escapePressed = Signal()

    def __init__(self, scene, selection, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.selection = selection
        self.camera = Camera()
        self.display_mode = "shaded"        # shaded | wireframe | ghosted
        self.grid_visible = True
        self.point_mode = False             # command wants a point click
        self._gpu: dict[str, _GpuObject] = {}
        self._grid = None
        self._preview: _LineBatch | None = None
        self._preview_data = np.zeros((0, 3), np.float32)
        self._marker_points: list = []
        self._last_mouse = None
        self._mesh_prog = self._line_prog = self._bg_prog = 0
        self._bg_vao = 0
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        scene.add_listener(self.update)
        selection.add_listener(self.update)

    # ---------------------------------------------------------------- GL setup

    def initializeGL(self):
        self._mesh_prog = _compile(MESH_VERT, MESH_FRAG)
        self._line_prog = _compile(LINE_VERT, LINE_FRAG)
        self._bg_prog = _compile(BG_VERT, BG_FRAG)
        quad = np.array([-1, -1, 1, -1, -1, 1, 1, 1], np.float32)
        self._bg_vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self._bg_vao)
        vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, quad.nbytes, quad,
                        GL.GL_STATIC_DRAW)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 2, GL.GL_FLOAT, False, 0,
                                 ctypes.c_void_p(0))
        GL.glBindVertexArray(0)
        self._build_grid()
        self._preview = _LineBatch(np.zeros((0, 3), np.float32), dynamic=True)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_MULTISAMPLE)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)

    def _build_grid(self, extent: int = 100, step: int = 1, major: int = 10):
        minor, majors = [], []
        for i in range(-extent, extent + 1, step):
            target = majors if i % major == 0 else minor
            if i == 0:
                continue
            target.append([[i, -extent, 0], [i, extent, 0]])
            target.append([[-extent, i, 0], [extent, i, 0]])
        axis_x = [[[-extent, 0, 0], [extent, 0, 0]]]
        axis_y = [[[0, -extent, 0], [0, extent, 0]]]
        as_pts = lambda segs: np.asarray(segs, np.float32).reshape(-1, 3)
        self._grid = {
            "minor": _LineBatch(as_pts(minor)),
            "major": _LineBatch(as_pts(majors)),
            "axis_x": _LineBatch(as_pts(axis_x)),
            "axis_y": _LineBatch(as_pts(axis_y)),
        }

    # ---------------------------------------------------------------- render

    def paintGL(self):
        GL.glClearColor(*theme.VIEWPORT_BG_BOTTOM, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

        # gradient background
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glUseProgram(self._bg_prog)
        GL.glUniform3f(GL.glGetUniformLocation(self._bg_prog, "uTop"),
                       *theme.VIEWPORT_BG_TOP)
        GL.glUniform3f(GL.glGetUniformLocation(self._bg_prog, "uBottom"),
                       *theme.VIEWPORT_BG_BOTTOM)
        GL.glBindVertexArray(self._bg_vao)
        GL.glDrawArrays(GL.GL_TRIANGLE_STRIP, 0, 4)
        GL.glEnable(GL.GL_DEPTH_TEST)

        w, h = self.width(), self.height()
        view = self.camera.view_matrix()
        mvp = (self.camera.proj_matrix(w, h) @ view).astype(np.float32)

        if self.grid_visible:
            self._draw_grid(mvp)
        self._sync_gpu()
        self._draw_objects(mvp, view)
        self._draw_preview(mvp)

    def _set_line_uniforms(self, mvp, color):
        GL.glUseProgram(self._line_prog)
        GL.glUniformMatrix4fv(
            GL.glGetUniformLocation(self._line_prog, "uMVP"), 1, GL.GL_TRUE,
            mvp)
        GL.glUniform4f(GL.glGetUniformLocation(self._line_prog, "uColor"),
                       *color)

    def _draw_lines(self, batch: _LineBatch, mvp, color, width=1.0):
        if not batch or batch.count == 0:
            return
        self._set_line_uniforms(mvp, color)
        GL.glLineWidth(width)
        GL.glBindVertexArray(batch.vao)
        GL.glDrawArrays(GL.GL_LINES, 0, batch.count)

    def _draw_grid(self, mvp):
        GL.glDepthMask(False)
        self._draw_lines(self._grid["minor"], mvp, theme.GRID_MINOR)
        self._draw_lines(self._grid["major"], mvp, theme.GRID_MAJOR)
        self._draw_lines(self._grid["axis_x"], mvp, theme.GRID_AXIS_X)
        self._draw_lines(self._grid["axis_y"], mvp, theme.GRID_AXIS_Y)
        GL.glDepthMask(True)

    def _sync_gpu(self):
        live = set()
        for obj in self.scene.all():
            live.add(obj.id)
            gpu = self._gpu.get(obj.id)
            if gpu is not None and gpu.mesh_id != id(obj.mesh):
                gpu.release()
                gpu = None
                del self._gpu[obj.id]
            if gpu is None:
                self._gpu[obj.id] = _GpuObject(obj.mesh)
        for dead in set(self._gpu) - live:
            self._gpu[dead].release()
            del self._gpu[dead]

    def _draw_objects(self, mvp, view):
        mode = self.display_mode
        fill_alpha = {"shaded": 1.0, "ghosted": 0.35, "wireframe": 0.0}[mode]
        for obj in self.scene.visible_objects():
            gpu = self._gpu.get(obj.id)
            if gpu is None:
                continue
            selected = self.selection.is_selected(obj.id)
            color = theme.SELECTION_COLOR if selected else self.scene.color_of(obj)

            if fill_alpha > 0 and gpu.tri_count:
                GL.glUseProgram(self._mesh_prog)
                GL.glUniformMatrix4fv(
                    GL.glGetUniformLocation(self._mesh_prog, "uMVP"), 1,
                    GL.GL_TRUE, mvp)
                GL.glUniformMatrix4fv(
                    GL.glGetUniformLocation(self._mesh_prog, "uView"), 1,
                    GL.GL_TRUE, view.astype(np.float32))
                GL.glUniform3f(
                    GL.glGetUniformLocation(self._mesh_prog, "uColor"), *color)
                GL.glUniform1f(
                    GL.glGetUniformLocation(self._mesh_prog, "uAlpha"),
                    fill_alpha)
                if mode == "ghosted":
                    GL.glDepthMask(False)
                GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
                GL.glPolygonOffset(1.0, 1.0)
                GL.glBindVertexArray(gpu.tri_vao)
                GL.glDrawElements(GL.GL_TRIANGLES, gpu.tri_count,
                                  GL.GL_UNSIGNED_INT, ctypes.c_void_p(0))
                GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
                GL.glDepthMask(True)

            if gpu.line_count:
                if selected:
                    edge_color = (*theme.SELECTION_COLOR, 1.0)
                elif obj.kind == "curve":
                    edge_color = (*color, 1.0)
                else:
                    # face edges: darkened object colour
                    edge_color = (color[0] * 0.35, color[1] * 0.35,
                                  color[2] * 0.35, 1.0)
                self._set_line_uniforms(mvp, edge_color)
                GL.glLineWidth(2.2 if selected else 1.4)
                GL.glBindVertexArray(gpu.line_vao)
                GL.glDrawArrays(GL.GL_LINES, 0, gpu.line_count)
        GL.glLineWidth(1.0)

    def _draw_preview(self, mvp):
        pts = self._preview_data
        markers = self._marker_points
        if len(pts) == 0 and not markers:
            return
        segs = [pts] if len(pts) else []
        # screen-scaled cross markers at picked points
        size = self.camera.distance * 0.008
        for m in markers:
            m = np.asarray(m, np.float32)
            for axis in np.eye(3, dtype=np.float32) * size:
                segs.append(np.stack([m - axis, m + axis]))
        allpts = np.concatenate(segs).astype(np.float32)
        self._preview.update(allpts)
        GL.glDisable(GL.GL_DEPTH_TEST)
        self._draw_lines(self._preview, mvp, (*theme.SELECTION_COLOR, 0.9),
                         1.6)
        GL.glEnable(GL.GL_DEPTH_TEST)

    # ------------------------------------------------------------- public API

    def set_preview(self, segments: np.ndarray | None,
                    markers: list | None = None):
        """Segments: (K,2,3) rubber-band lines; markers: picked points."""
        if segments is None or len(segments) == 0:
            self._preview_data = np.zeros((0, 3), np.float32)
        else:
            self._preview_data = np.asarray(
                segments, np.float32).reshape(-1, 3)
        self._marker_points = list(markers or [])
        self.update()

    def set_point_mode(self, on: bool):
        self.point_mode = on
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor if on
                               else Qt.CursorShape.ArrowCursor))
        if not on:
            self.set_preview(None)

    def set_display_mode(self, mode: str):
        if mode not in ("shaded", "wireframe", "ghosted"):
            raise ValueError(f"Unknown display mode '{mode}'")
        self.display_mode = mode
        self.update()

    def zoom_extents(self):
        self.camera.zoom_extents(self.scene.bbox())
        self.update()

    def set_view(self, name: str):
        self.camera.set_standard_view(name)
        self.update()

    def screenshot(self, path: str) -> bool:
        img = self.grabFramebuffer()
        return img.save(path)

    # -------------------------------------------------------------- picking

    def world_point_at(self, px: float, py: float):
        """Intersect the pixel ray with the construction plane (z=0)."""
        origin, direction = self.camera.ray_through(px, py, self.width(),
                                                    self.height())
        hit = ray_plane(origin, direction, np.zeros(3),
                        np.array([0.0, 0.0, 1.0]))
        if hit is None:
            return None
        return tuple(round(float(c), 9) for c in hit)

    def pick_object(self, px: float, py: float) -> str | None:
        w, h = self.width(), self.height()
        origin, direction = self.camera.ray_through(px, py, w, h)
        best_id, best_depth = None, np.inf

        for obj in self.scene.visible_objects():
            mesh = obj.mesh
            depth = np.inf
            hit = False
            if mesh.has_faces and self.display_mode != "wireframe":
                tris = mesh.triangles
                t = ray_triangle_hits(origin, direction,
                                      mesh.vertices[tris[:, 0]].astype(float),
                                      mesh.vertices[tris[:, 1]].astype(float),
                                      mesh.vertices[tris[:, 2]].astype(float))
                tmin = t.min() if len(t) else np.inf
                if np.isfinite(tmin):
                    depth = tmin
                    hit = True
            if len(mesh.edge_segments):
                pts = mesh.edge_segments.reshape(-1, 3)
                scr = self.camera.project(pts, w, h)
                a, b = scr[0::2], scr[1::2]
                d2 = _point_segment_dist2(np.array([px, py]), a[:, :2],
                                          b[:, :2])
                near = d2 < PICK_RADIUS_PX ** 2
                if near.any():
                    seg_depth = np.minimum(a[near, 2], b[near, 2]).min()
                    if seg_depth > 0:
                        # small bias so curves on surfaces stay selectable
                        seg_depth *= 0.999
                        if seg_depth < depth:
                            depth = seg_depth
                        hit = True
            if hit and depth < best_depth:
                best_depth = depth
                best_id = obj.id
        return best_id

    # ---------------------------------------------------------------- events

    def mousePressEvent(self, ev):
        self._last_mouse = ev.position()
        self._orbiting = False
        if ev.button() == Qt.MouseButton.LeftButton:
            pos = ev.position()
            if self.point_mode:
                pt = self.world_point_at(pos.x(), pos.y())
                if pt is not None:
                    self.pointPicked.emit(pt)
                return
            picked = self.pick_object(pos.x(), pos.y())
            if picked:
                self.objectClicked.emit(picked, ev.modifiers())
            else:
                self.emptyClicked.emit(ev.modifiers())

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._last_mouse is None:
            self._last_mouse = pos
        dx = pos.x() - self._last_mouse.x()
        dy = pos.y() - self._last_mouse.y()
        if ev.buttons() & Qt.MouseButton.MiddleButton:
            if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.camera.pan(dx, dy, self.height())
            else:
                self.camera.orbit(dx, dy)
            self.update()
        elif self.point_mode:
            pt = self.world_point_at(pos.x(), pos.y())
            if pt is not None:
                self.mouseWorldMoved.emit(pt)
        self._last_mouse = pos

    def wheelEvent(self, ev):
        steps = ev.angleDelta().y() / 120.0
        self.camera.zoom(steps)
        self.update()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.escapePressed.emit()
        else:
            super().keyPressEvent(ev)


def _point_segment_dist2(p: np.ndarray, a: np.ndarray,
                         b: np.ndarray) -> np.ndarray:
    """Squared distance from point p to 2D segments a->b (vectorized)."""
    ab = b - a
    ap = p[None, :] - a
    denom = np.einsum("ij,ij->i", ab, ab)
    denom[denom < 1e-12] = 1e-12
    t = np.clip(np.einsum("ij,ij->i", ap, ab) / denom, 0.0, 1.0)
    closest = a + ab * t[:, None]
    d = p[None, :] - closest
    return np.einsum("ij,ij->i", d, d)
