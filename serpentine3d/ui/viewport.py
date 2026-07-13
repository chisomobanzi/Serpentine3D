"""3D OpenGL viewport: rendering, navigation, picking."""

from __future__ import annotations

import ctypes

import numpy as np
from OpenGL import GL
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication

from ..utils.math3d import (normalize, ray_line_parameter, ray_plane, ray_plane_any, ray_triangle_hits)
from . import theme
from .camera import Camera

PICK_RADIUS_PX = 7.0

MESH_VERT = """
#version 330 core
layout(location=0) in vec3 pos;
layout(location=1) in vec3 nrm;
layout(location=2) in float curv;
uniform mat4 uMVP;
uniform mat4 uView;
out vec3 vNormal;
out vec3 vPosView;
out float vCurv;
out float vWorldZ;
void main() {
    gl_Position = uMVP * vec4(pos, 1.0);
    vNormal = mat3(uView) * nrm;
    vPosView = (uView * vec4(pos, 1.0)).xyz;
    vCurv = curv;
    vWorldZ = nrm.z;
}
"""

MESH_FRAG = """
#version 330 core
in vec3 vNormal;
in vec3 vPosView;
in float vCurv;
in float vWorldZ;
uniform vec3 uColor;
uniform float uAlpha;
uniform int uZebra;
uniform int uDraft;         // 1 = draft-angle analysis
uniform float uDraftCos;    // cos(90deg - required draft)
uniform float uCurvRange;   // >0 enables curvature false-colour
uniform int uRendered;      // 1 = environment-lit rendered mode
uniform float uMetallic;
uniform float uRoughness;
out vec4 frag;
void main() {
    vec3 n = normalize(vNormal);
    if (!gl_FrontFacing) n = -n;
    vec3 l = normalize(-vPosView);
    float diff = max(dot(n, l), 0.0);
    if (uCurvRange > 0.0) {
        float t = clamp(vCurv / uCurvRange * 0.5 + 0.5, 0.0, 1.0);
        vec3 cold = vec3(0.15, 0.35, 0.9);
        vec3 flat_ = vec3(0.25, 0.8, 0.35);
        vec3 hot = vec3(0.95, 0.25, 0.2);
        vec3 cc = t < 0.5 ? mix(cold, flat_, t * 2.0)
                          : mix(flat_, hot, (t - 0.5) * 2.0);
        frag = vec4(cc * (0.45 + 0.55 * diff), uAlpha);
        return;
    }
    if (uDraft == 1) {
        // world-space normal ~ view-space transformed back is overkill:
        // use the mesh normal via uView inverse-free trick — pass world
        // normals: vNormal is view-space, so compare against view up of
        // world +Z transformed. Instead we approximate with vWorldN.
        float c = vWorldZ;                  // world normal z component
        vec3 col;
        if (c < -0.02)      col = vec3(0.85, 0.25, 0.2);    // undercut
        else if (c < uDraftCos) col = vec3(0.3, 0.5, 0.9);  // needs draft
        else                col = vec3(0.35, 0.8, 0.4);     // ok
        frag = vec4(col * (0.45 + 0.55 * diff), uAlpha);
        return;
    }
    if (uZebra == 1) {
        // stripes follow the reflection direction: any kink in the surface
        // shows as a jag in the stripes
        vec3 r = reflect(normalize(vPosView), n);
        float band = sin(40.0 * r.y);
        float stripe = smoothstep(-0.06, 0.06, band);
        vec3 zebra = mix(vec3(0.06), vec3(0.95), stripe);
        frag = vec4(zebra * (0.55 + 0.45 * diff), uAlpha);
        return;
    }
    if (uRendered == 1) {
        // three-light studio: key from camera-up-left, cool fill, rim
        vec3 key = normalize(vec3(-0.4, 0.35, 0.85));
        vec3 fill = normalize(vec3(0.7, 0.1, 0.25));
        vec3 kd = uColor * mix(1.0, 0.35, uMetallic);
        float dk = max(dot(n, key), 0.0);
        float df = max(dot(n, fill), 0.0);
        // hemisphere ambient: bluish sky above, warm ground bounce
        float hemi = n.y * 0.5 + 0.5;
        vec3 amb = mix(vec3(0.16, 0.14, 0.12), vec3(0.20, 0.22, 0.26),
                       hemi);
        float gloss = mix(64.0, 6.0, clamp(uRoughness, 0.0, 1.0));
        vec3 h = normalize(key + l);
        float spec_i = pow(max(dot(n, h), 0.0), gloss)
                       * mix(0.25, 0.9, uMetallic)
                       * mix(1.0, 0.25, uRoughness);
        vec3 spec_c = mix(vec3(1.0), uColor, uMetallic);
        float fres = pow(1.0 - max(dot(n, l), 0.0), 3.0) * 0.25;
        vec3 c = kd * (amb + vec3(0.95, 0.93, 0.88) * dk
                       + vec3(0.25, 0.28, 0.34) * df)
                 + spec_c * spec_i + vec3(fres);
        frag = vec4(c, uAlpha);
        return;
    }
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

THICK_VERT = """
#version 330 core
layout(location=0) in vec3 pos;      // this end of the segment
layout(location=1) in vec3 other;    // the far end
layout(location=2) in float side;    // +1 / -1 across the line
uniform mat4 uMVP;
uniform vec2 uViewport;              // pixels
uniform float uWidthPx;
void main() {
    vec4 p = uMVP * vec4(pos, 1.0);
    vec4 q = uMVP * vec4(other, 1.0);
    vec2 half_vp = uViewport * 0.5;
    vec2 sp = p.xy / p.w * half_vp;
    vec2 sq = q.xy / q.w * half_vp;
    vec2 dir = sq - sp;
    float len = length(dir);
    vec2 n = len > 1e-4 ? vec2(-dir.y, dir.x) / len : vec2(1.0, 0.0);
    sp += n * side * uWidthPx * 0.5;
    gl_Position = vec4(sp / half_vp * p.w, p.z, p.w);
}
"""

TEX_VERT = """
#version 330 core
layout(location=0) in vec3 pos;
layout(location=1) in vec2 uv;
uniform mat4 uMVP;
out vec2 vUV;
void main() { gl_Position = uMVP * vec4(pos, 1.0); vUV = uv; }
"""

TEX_FRAG = """
#version 330 core
in vec2 vUV;
uniform sampler2D uTex;
uniform float uAlpha;
out vec4 frag;
void main() { frag = vec4(texture(uTex, vUV).rgb, uAlpha); }
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
        self.iso_vao = self.iso_count = 0
        self._buffers = []
        if mesh.has_faces:
            curv = mesh.curvature
            if len(curv) != len(mesh.vertices):
                curv = np.zeros(len(mesh.vertices), np.float32)
            inter = np.hstack([mesh.vertices, mesh.normals,
                               curv[:, None]]).astype(np.float32)
            self.tri_vao = GL.glGenVertexArrays(1)
            GL.glBindVertexArray(self.tri_vao)
            vbo = GL.glGenBuffers(1)
            self._buffers.append(vbo)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, inter.nbytes, inter,
                            GL.GL_STATIC_DRAW)
            GL.glEnableVertexAttribArray(0)
            GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, False, 28,
                                     ctypes.c_void_p(0))
            GL.glEnableVertexAttribArray(1)
            GL.glVertexAttribPointer(1, 3, GL.GL_FLOAT, False, 28,
                                     ctypes.c_void_p(12))
            GL.glEnableVertexAttribArray(2)
            GL.glVertexAttribPointer(2, 1, GL.GL_FLOAT, False, 28,
                                     ctypes.c_void_p(24))
            ebo = GL.glGenBuffers(1)
            self._buffers.append(ebo)
            idx = mesh.triangles.astype(np.uint32)
            GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, ebo)
            GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx,
                            GL.GL_STATIC_DRAW)
            self.tri_count = idx.size
        self.thick_vao = self.thick_count = 0
        if len(mesh.edge_segments):
            self.line_vao, self.line_count = self._make_line_vao(
                mesh.edge_segments)
            self.thick_vao, self.thick_count = self._make_thick_vao(
                mesh.edge_segments)
        if len(mesh.iso_segments):
            self.iso_vao, self.iso_count = self._make_line_vao(
                mesh.iso_segments)
        GL.glBindVertexArray(0)

    def _make_line_vao(self, segments) -> tuple[int, int]:
        pts = segments.reshape(-1, 3).astype(np.float32)
        vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(vao)
        vbo = GL.glGenBuffers(1)
        self._buffers.append(vbo)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, pts.nbytes, pts,
                        GL.GL_STATIC_DRAW)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, False, 0,
                                 ctypes.c_void_p(0))
        return vao, len(pts)

    def _make_thick_vao(self, segments) -> tuple[int, int]:
        """Per-segment quads for the screen-space wide-line shader."""
        segs = segments.astype(np.float32)
        n = len(segs)
        a, b = segs[:, 0], segs[:, 1]
        # vertex layout: pos(3) other(3) side(1); quad = A+n, A-n, B-n, B+n
        verts = np.empty((n, 4, 7), np.float32)
        verts[:, 0, :3] = a
        verts[:, 0, 3:6] = b
        verts[:, 0, 6] = 1.0
        verts[:, 1, :3] = a
        verts[:, 1, 3:6] = b
        verts[:, 1, 6] = -1.0
        verts[:, 2, :3] = b
        verts[:, 2, 3:6] = a
        verts[:, 2, 6] = 1.0
        verts[:, 3, :3] = b
        verts[:, 3, 3:6] = a
        verts[:, 3, 6] = -1.0
        idx = (np.arange(n, dtype=np.uint32)[:, None] * 4
               + np.array([0, 1, 2, 0, 2, 3], np.uint32)[None, :]).ravel()
        flat = verts.reshape(-1, 7)
        vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(vao)
        vbo = GL.glGenBuffers(1)
        self._buffers.append(vbo)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, flat.nbytes, flat,
                        GL.GL_STATIC_DRAW)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, False, 28,
                                 ctypes.c_void_p(0))
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 3, GL.GL_FLOAT, False, 28,
                                 ctypes.c_void_p(12))
        GL.glEnableVertexAttribArray(2)
        GL.glVertexAttribPointer(2, 1, GL.GL_FLOAT, False, 28,
                                 ctypes.c_void_p(24))
        ebo = GL.glGenBuffers(1)
        self._buffers.append(ebo)
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, ebo)
        GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx,
                        GL.GL_STATIC_DRAW)
        return vao, len(idx)

    def release(self):
        for vao in (self.tri_vao, self.line_vao, self.iso_vao,
                    getattr(self, "thick_vao", 0)):
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
    boxSelected = Signal(list, object)      # picked ids, modifiers
    pointPicked = Signal(object)            # (x, y, z) in point-input mode
    mouseWorldMoved = Signal(object)        # (x, y, z) while in point-input mode
    cvEditBegan = Signal()                  # control-point drag started
    escapePressed = Signal()
    _tessDone = Signal()                    # a background mesh finished

    def __init__(self, scene, selection, config=None, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.selection = selection
        self.config = config
        self.camera = Camera()
        self.display_mode = "shaded"        # shaded | wireframe | ghosted
        self.grid_visible = True
        self.point_mode = False             # command wants a point click
        from ..core.cplane import CPlane
        self.cplane = CPlane()
        from .layout_view import LayoutView
        self.space = "model"                # "model" | layout id
        self.layout_view = LayoutView(self)
        from .gumball import Gumball
        self.gumball = Gumball(self)
        self.history = None                 # set by the main window
        from ..core.snaps import SnapIndex
        self.snaps = SnapIndex(scene, config)
        self._active_snap = None            # (point, kind) under cursor
        self.snap_base = None               # reference point for perp snap
        self.frame_aspect = None            # cinema frame guide (e.g. 2.39)
        self.grid_snap = bool(config.get("grid_snap")) if config else False
        self.grid_snap_step = (float(config.get("grid_snap_step",
                                                default=1.0))
                               if config else 1.0)
        self.cv_enabled: set[str] = set()   # objects showing control points
        self.comb_enabled: set[str] = set() # curvature combs on curves
        self.draft_angle = 3.0              # draft analysis threshold (deg)
        self._cv_cache: dict = {}
        self._cv_drag = None                # (obj_id, index, plane_pt, normal)
        self._press_pos = None
        self._box_end = None
        self._box_active = False
        self._gpu: dict[str, _GpuObject] = {}
        self._grid = None
        # heavy shapes tessellate off the UI thread; bbox shown meanwhile
        self._tess_pool = None                     # created on first use
        self._tess_pending: dict[str, np.ndarray] = {}   # id -> bbox segs
        self._tessDone.connect(self._on_tess_done,
                               Qt.ConnectionType.QueuedConnection)
        self._preview: _LineBatch | None = None
        self._preview_data = np.zeros((0, 3), np.float32)
        self._ghost = None                     # DisplayMesh of pending result
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
        self._thick_prog = _compile(THICK_VERT, LINE_FRAG)
        self._bg_prog = _compile(BG_VERT, BG_FRAG)
        self._tex_prog = _compile(TEX_VERT, TEX_FRAG)
        self._tex_vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(self._tex_vao)
        self._tex_vbo = GL.glGenBuffers(1)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._tex_vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, 6 * 5 * 4, None,
                        GL.GL_DYNAMIC_DRAW)
        GL.glEnableVertexAttribArray(0)
        GL.glVertexAttribPointer(0, 3, GL.GL_FLOAT, False, 20,
                                 ctypes.c_void_p(0))
        GL.glEnableVertexAttribArray(1)
        GL.glVertexAttribPointer(1, 2, GL.GL_FLOAT, False, 20,
                                 ctypes.c_void_p(12))
        GL.glBindVertexArray(0)
        self._image_textures = {}
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
        extent = (int(self.config.get("display", "grid_extent", default=100))
                  if self.config else 100)
        major = (int(self.config.get("display", "grid_major", default=10))
                 if self.config else 10)
        self._build_grid(extent=extent, major=major)
        self._preview = _LineBatch(np.zeros((0, 3), np.float32), dynamic=True)
        # forward-compatible core contexts reject widths > 1.0 regardless of
        # the advertised range, so probe rather than trust the query
        self._max_line_width = 1.0
        try:
            # software GL advertises a wide range but rasterizes 1px in a
            # core profile; those edges go through the quad shader instead
            renderer = GL.glGetString(GL.GL_RENDERER) or b""
            soft = any(s in renderer for s in (b"llvmpipe", b"softpipe",
                                               b"SWR"))
            GL.glLineWidth(2.0)
            if not soft and GL.glGetError() == GL.GL_NO_ERROR:
                rng = GL.glGetFloatv(GL.GL_ALIASED_LINE_WIDTH_RANGE)
                self._max_line_width = float(rng[1])
            GL.glLineWidth(1.0)
            GL.glGetError()
        except Exception:
            pass
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glEnable(GL.GL_MULTISAMPLE)
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)

    def set_grid_params(self, extent: int, major: int):
        """Rebuild the grid with new dimensions (needs a live GL context)."""
        self._grid_params = (int(extent), int(major))
        if self._grid is not None:
            self.makeCurrent()
            for batch in self._grid.values():
                batch.release()
            self._build_grid(extent=int(extent), major=int(major))
            self.doneCurrent()
            self.update()

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

        if self.space != "model":
            from PySide6.QtGui import QPainter
            painter = QPainter(self)
            painter.beginNativePainting()
            GL.glEnable(GL.GL_DEPTH_TEST)
            GL.glEnable(GL.GL_BLEND)
            GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
            self._sync_gpu()
            self.layout_view.paint()
            self._draw_preview(self.layout_view._paper_mvp())
            GL.glBindVertexArray(0)
            GL.glUseProgram(0)
            GL.glDisable(GL.GL_SCISSOR_TEST)
            GL.glDisable(GL.GL_DEPTH_TEST)
            painter.endNativePainting()
            self.layout_view.paint_overlay(painter)
            painter.end()
            return

        view = self.camera.view_matrix()
        mvp = (self.camera.proj_matrix(w, h) @ view).astype(np.float32)

        if self.display_mode == "technical":
            self._paint_technical(w, h)
            self._draw_preview(mvp)
            self._draw_selection_box(w, h)
            return

        if self.grid_visible:
            self._draw_grid(mvp)
        self._draw_image_planes(mvp)
        self._sync_gpu()
        self._draw_objects(mvp, view)
        self._draw_ghost(mvp)
        self._draw_preview(mvp)
        self._draw_control_points(mvp)
        self._draw_combs(mvp)
        self.gumball.paint(mvp)
        self._draw_axis_triad(view, w, h)
        self._draw_frame_guides(w, h)
        self._draw_selection_box(w, h)

    def _paint_technical(self, w, h):
        """Model-space technical view: parallel-projection HLR linework."""
        import math as _math
        from ..core import hlr as _hlr
        # paper-like background
        GL.glDisable(GL.GL_DEPTH_TEST)
        self._preview.update(np.array(
            [[-1, -1, 0], [1, -1, 0], [-1, 1, 0],
             [1, -1, 0], [1, 1, 0], [-1, 1, 0]], np.float32))
        self._set_line_uniforms(np.eye(4, dtype=np.float32),
                                (0.94, 0.94, 0.92, 1.0))
        GL.glBindVertexArray(self._preview.vao)
        GL.glDrawArrays(GL.GL_TRIANGLES, 0, 6)

        cam = self.camera
        half_h = cam.distance * _math.tan(_math.radians(cam.fov) / 2)
        half_w = half_h * w / max(h, 1)
        mvp2d = np.eye(4, dtype=np.float32)
        mvp2d[0, 0] = 1.0 / half_w
        mvp2d[1, 1] = 1.0 / half_h

        dragging = bool(QApplication.mouseButtons() & self._nav_button())
        if dragging:
            # fast wireframe preview while navigating
            self._sync_gpu()
            view = cam.view_matrix()
            mvp = (cam.proj_matrix(w, h) @ view).astype(np.float32)
            GL.glEnable(GL.GL_DEPTH_TEST)
            self._draw_objects(mvp, view, mode_override="wireframe",
                               light_background=True)
            GL.glDisable(GL.GL_DEPTH_TEST)
            return

        key = (self.scene.revision, round(cam.azimuth, 5),
               round(cam.elevation, 5),
               tuple(round(float(c), 4) for c in cam.target))
        cached = getattr(self, "_tech_cache", None)
        if cached is None or cached[0] != key:
            from ..core.mesh import MeshShape
            shapes = [o.shape for o in self.scene.visible_objects()
                      if not isinstance(o.shape, MeshShape)]
            if shapes:
                fwd = cam.target - cam.position
                fwd = fwd / max(np.linalg.norm(fwd), 1e-12)
                right, up = cam.right_up()
                res = _hlr.hlr_project_safe(shapes, origin=tuple(cam.target),
                                       view_dir=tuple(-fwd),
                                       x_dir=tuple(right))
                data = {
                    "visible": _hlr.edges_to_polylines(
                        res["visible"] + res["outline"]),
                    "hidden": _hlr.edges_to_polylines(res["hidden"]),
                }
            else:
                data = {"visible": [], "hidden": []}
            self._tech_cache = (key, data)
        data = self._tech_cache[1]

        hidden_segs = []
        for poly in data["hidden"]:
            seg = _hlr.dash_segments(poly, dash=half_h * 0.02,
                                     gap=half_h * 0.012)
            if len(seg):
                hidden_segs.append(seg)
        if hidden_segs:
            allh = np.concatenate(hidden_segs).reshape(-1, 3)
            self._preview.update(allh.astype(np.float32))
            self._set_line_uniforms(mvp2d, (0.45, 0.45, 0.5, 1.0))
            self._line_width(1.0)
            GL.glBindVertexArray(self._preview.vao)
            GL.glDrawArrays(GL.GL_LINES, 0, len(allh))
        vis_segs = []
        for poly in data["visible"]:
            vis_segs.append(np.stack([poly[:-1], poly[1:]], axis=1))
        if vis_segs:
            allv = np.concatenate(vis_segs).reshape(-1, 3)
            self._preview.update(allv.astype(np.float32))
            self._set_line_uniforms(mvp2d, (0.08, 0.08, 0.1, 1.0))
            self._line_width(1.6)
            GL.glBindVertexArray(self._preview.vao)
            GL.glDrawArrays(GL.GL_LINES, 0, len(allv))
        GL.glEnable(GL.GL_DEPTH_TEST)

    def _set_line_uniforms(self, mvp, color):
        GL.glUseProgram(self._line_prog)
        GL.glUniformMatrix4fv(
            GL.glGetUniformLocation(self._line_prog, "uMVP"), 1, GL.GL_TRUE,
            mvp)
        GL.glUniform4f(GL.glGetUniformLocation(self._line_prog, "uColor"),
                       *color)

    def _line_width(self, width: float):
        GL.glLineWidth(min(width, getattr(self, "_max_line_width", 1.0)))

    def _draw_lines(self, batch: _LineBatch, mvp, color, width=1.0):
        if not batch or batch.count == 0:
            return
        self._set_line_uniforms(mvp, color)
        self._line_width(width)
        GL.glBindVertexArray(batch.vao)
        GL.glDrawArrays(GL.GL_LINES, 0, batch.count)

    def _texture_for(self, path: str):
        entry = self._image_textures.get(path)
        if entry is not None:
            return entry
        from PySide6.QtGui import QImage
        img = QImage(path)
        if img.isNull():
            self._image_textures[path] = (0, 1.0)
            return self._image_textures[path]
        img = img.convertToFormat(QImage.Format.Format_RGBA8888)
        img = img.mirrored(False, True)
        tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        ptr = img.constBits()
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, img.width(),
                        img.height(), 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE,
                        bytes(ptr))
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER,
                           GL.GL_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER,
                           GL.GL_LINEAR)
        aspect = img.width() / max(img.height(), 1)
        self._image_textures[path] = (tex, aspect)
        return self._image_textures[path]

    def _draw_image_planes(self, mvp):
        planes = getattr(self.scene, "image_planes", [])
        if not planes:
            return
        for plane in planes:
            tex, _ = self._texture_for(plane["path"])
            if not tex:
                continue
            o = np.asarray(plane["origin"], np.float32)
            u = np.asarray(plane["u"], np.float32)
            v = np.asarray(plane["v"], np.float32)
            quad = np.array([
                [*o, 0, 0], [*(o + u), 1, 0], [*(o + u + v), 1, 1],
                [*o, 0, 0], [*(o + u + v), 1, 1], [*(o + v), 0, 1],
            ], np.float32)
            GL.glUseProgram(self._tex_prog)
            GL.glUniformMatrix4fv(
                GL.glGetUniformLocation(self._tex_prog, "uMVP"), 1,
                GL.GL_TRUE, mvp)
            GL.glUniform1f(
                GL.glGetUniformLocation(self._tex_prog, "uAlpha"),
                float(plane.get("alpha", 1.0)))
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
            GL.glUniform1i(
                GL.glGetUniformLocation(self._tex_prog, "uTex"), 0)
            GL.glBindVertexArray(self._tex_vao)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._tex_vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, quad.nbytes, quad,
                            GL.GL_DYNAMIC_DRAW)
            GL.glDepthMask(False)
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, 6)
            GL.glDepthMask(True)

    def _draw_grid(self, mvp):
        # grid geometry lives in plane-local XY; transform by the CPlane
        if not self.cplane.is_world_xy():
            mvp = (mvp @ self.cplane.basis_matrix()).astype(np.float32)
        GL.glDepthMask(False)
        self._draw_lines(self._grid["minor"], mvp, theme.GRID_MINOR)
        self._draw_lines(self._grid["major"], mvp, theme.GRID_MAJOR)
        self._draw_lines(self._grid["axis_x"], mvp, theme.GRID_AXIS_X)
        self._draw_lines(self._grid["axis_y"], mvp, theme.GRID_AXIS_Y)
        GL.glDepthMask(True)

    def set_cplane(self, cplane):
        self.cplane = cplane
        self.update()

    # shapes with at least this many faces mesh in the background
    ASYNC_FACE_COUNT = 48

    def _sync_gpu(self):
        live = set()
        for obj in self.scene.all():
            live.add(obj.id)
            gpu = self._gpu.get(obj.id)
            if not obj.mesh_ready and self._schedule_tess(obj):
                if gpu is not None:
                    gpu.release()
                    del self._gpu[obj.id]
                continue
            self._tess_pending.pop(obj.id, None)
            if gpu is not None and gpu.mesh_id != id(obj.mesh):
                gpu.release()
                gpu = None
                del self._gpu[obj.id]
            if gpu is None:
                self._gpu[obj.id] = _GpuObject(obj.mesh)
        for dead in set(self._gpu) - live:
            self._gpu[dead].release()
            del self._gpu[dead]
        for dead in set(self._tess_pending) - live:
            del self._tess_pending[dead]

    def _schedule_tess(self, obj) -> bool:
        """Queue heavy tessellation on a worker; True while pending."""
        if obj.id in self._tess_pending:
            return True
        from ..core.mesh import MeshShape
        if isinstance(obj.shape, MeshShape):
            return False                    # meshes convert instantly
        try:
            from ..core import geometry as g
            n = 0
            for _ in g.faces_of(obj.shape):
                n += 1
                if n >= self.ASYNC_FACE_COUNT:
                    break
            if n < self.ASYNC_FACE_COUNT:
                return False
            mn, mx = g.bbox(obj.shape)
        except Exception:                                  # noqa: BLE001
            return False
        if self._tess_pool is None:
            from concurrent.futures import ThreadPoolExecutor
            self._tess_pool = ThreadPoolExecutor(
                max_workers=3, thread_name_prefix="serp-tess")
        self._tess_pending[obj.id] = _bbox_segments(mn, mx)

        def work(target=obj):
            try:
                target.mesh                # locks per shape, sets _mesh
            except Exception:              # noqa: BLE001
                pass
            self._tessDone.emit()

        self._tess_pool.submit(work)
        return True

    def _on_tess_done(self):
        self.update()

    def _curvature_range(self) -> float:
        """95th percentile of |curvature| across visible meshes (cached)."""
        rev = self.scene.revision
        cached = getattr(self, "_curv_range_cache", None)
        if cached is not None and cached[0] == rev:
            return cached[1]
        vals = []
        for obj in self.scene.visible_objects():
            c = obj.mesh.curvature
            if len(c):
                vals.append(np.abs(c))
        rng = 1.0
        if vals:
            allv = np.concatenate(vals)
            nz = allv[allv > 1e-9]
            if len(nz):
                rng = float(np.percentile(nz, 95))
        self._curv_range_cache = (rev, max(rng, 1e-9))
        return self._curv_range_cache[1]

    def _draw_objects(self, mvp, view, mode_override=None,
                      light_background=False):
        mode = mode_override or self.display_mode
        fill_alpha = {"shaded": 1.0, "ghosted": 0.35, "wireframe": 0.0,
                      "zebra": 1.0, "curvature": 1.0, "draft": 1.0,
                      "rendered": 1.0}[mode]
        curv_range = self._curvature_range() if mode == "curvature" else 0.0
        objects = self.scene.visible_objects()
        translucent = mode == "ghosted" or any(
            (o.material or {}).get("opacity", 1.0) < 1.0 for o in objects)
        if translucent:
            # translucency composits correctly back-to-front
            eye = np.asarray(self.camera.position, float)

            def _depth(o):
                b = o.mesh.bounds() if o.mesh_ready else None
                if b is None:
                    return 0.0
                centre = (np.asarray(b[0]) + np.asarray(b[1])) / 2
                return -float(np.linalg.norm(centre - eye))
            objects = sorted(objects, key=_depth)
        if mode == "rendered":
            self._draw_ground_shadow(mvp, objects)
        for obj in objects:
            gpu = self._gpu.get(obj.id)
            if gpu is None:
                pend = self._tess_pending.get(obj.id)
                if pend is not None and len(pend):
                    self._preview.update(pend)
                    self._set_line_uniforms(
                        mvp, (*self.scene.color_of(obj), 0.5))
                    self._line_width(1.0)
                    GL.glBindVertexArray(self._preview.vao)
                    GL.glDrawArrays(GL.GL_LINES, 0, len(pend))
                continue
            selected = self.selection.is_selected(obj.id)
            color = theme.SELECTION_COLOR if selected else self.scene.color_of(obj)
            if obj.locked and not selected:
                grey = (color[0] + color[1] + color[2]) / 3 * 0.55 + 0.18
                color = (grey, grey, grey)
            line_color = color
            if light_background and not selected:
                # dark linework on paper-white detail backgrounds
                line_color = (min(color[0], 0.3), min(color[1], 0.3),
                              min(color[2], 0.33))

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
                GL.glUniform1i(
                    GL.glGetUniformLocation(self._mesh_prog, "uZebra"),
                    1 if mode == "zebra" else 0)
                import math as _math
                GL.glUniform1i(
                    GL.glGetUniformLocation(self._mesh_prog, "uDraft"),
                    1 if mode == "draft" else 0)
                GL.glUniform1f(
                    GL.glGetUniformLocation(self._mesh_prog, "uDraftCos"),
                    _math.sin(_math.radians(self.draft_angle)))
                GL.glUniform1f(
                    GL.glGetUniformLocation(self._mesh_prog, "uCurvRange"),
                    curv_range)
                m = obj.material or {}
                opacity = float(m.get("opacity", 1.0))
                GL.glUniform1i(
                    GL.glGetUniformLocation(self._mesh_prog, "uRendered"),
                    1 if mode == "rendered" else 0)
                GL.glUniform1f(
                    GL.glGetUniformLocation(self._mesh_prog, "uMetallic"),
                    float(m.get("metallic", 0.0)))
                GL.glUniform1f(
                    GL.glGetUniformLocation(self._mesh_prog, "uRoughness"),
                    float(m.get("roughness", 0.55)))
                if opacity < 1.0:
                    GL.glUniform1f(
                        GL.glGetUniformLocation(self._mesh_prog, "uAlpha"),
                        fill_alpha * opacity)
                if mode == "ghosted" or opacity < 1.0:
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
                    edge_color = (*line_color, 1.0)
                else:
                    # face edges: darkened object colour
                    edge_color = (line_color[0] * 0.35, line_color[1] * 0.35,
                                  line_color[2] * 0.35, 1.0)
                lw = self.scene.layers.get(obj.layer_id).lineweight
                self._draw_edges(gpu, mvp, edge_color,
                                 2.2 if selected else lw)

            subs = self.selection.subobjects_of(obj.id, "edge") \
                if self.selection.subobjects else []
            if subs and len(obj.mesh.edge_of_segment):
                mask = np.isin(obj.mesh.edge_of_segment, subs)
                if mask.any():
                    segs = obj.mesh.edge_segments[mask].reshape(-1, 3)
                    self._preview.update(segs.astype(np.float32))
                    self._set_line_uniforms(mvp,
                                            (*theme.SELECTION_COLOR, 1.0))
                    self._line_width(3.0)
                    GL.glDisable(GL.GL_DEPTH_TEST)
                    GL.glBindVertexArray(self._preview.vao)
                    GL.glDrawArrays(GL.GL_LINES, 0, len(segs))
                    GL.glEnable(GL.GL_DEPTH_TEST)
            fsubs = self.selection.subobjects_of(obj.id, "face") \
                if self.selection.subobjects else []
            if fsubs and len(obj.mesh.face_of_triangle):
                mask = np.isin(obj.mesh.face_of_triangle, fsubs)
                if mask.any():
                    tris = obj.mesh.triangles[mask]
                    pts = obj.mesh.vertices[tris.ravel()]
                    self._preview.update(pts.astype(np.float32))
                    self._set_line_uniforms(mvp,
                                            (*theme.SELECTION_COLOR, 0.45))
                    GL.glBindVertexArray(self._preview.vao)
                    GL.glDrawArrays(GL.GL_TRIANGLES, 0, len(pts))
            if gpu.iso_count:
                if selected:
                    iso_color = (*theme.SELECTION_COLOR, 0.55)
                elif mode == "wireframe":
                    iso_color = (*color, 0.55)
                else:
                    iso_color = (color[0] * 0.30, color[1] * 0.30,
                                 color[2] * 0.30, 0.8)
                self._set_line_uniforms(mvp, iso_color)
                self._line_width(1.0)
                GL.glBindVertexArray(gpu.iso_vao)
                GL.glDrawArrays(GL.GL_LINES, 0, gpu.iso_count)
        self._line_width(1.0)

    def _draw_ground_shadow(self, mvp, objects):
        """Flatten object triangles onto z=0 as a soft dark stamp."""
        squash = np.eye(4, dtype=np.float32)
        squash[2, 2] = 0.0
        squash[2, 3] = 0.01                 # hair above the plane
        smvp = (mvp @ squash).astype(np.float32)
        GL.glUseProgram(self._line_prog)
        GL.glUniformMatrix4fv(
            GL.glGetUniformLocation(self._line_prog, "uMVP"), 1, GL.GL_TRUE,
            smvp)
        GL.glUniform4f(GL.glGetUniformLocation(self._line_prog, "uColor"),
                       0.02, 0.02, 0.03, 0.30)
        GL.glDepthMask(False)
        for obj in objects:
            gpu = self._gpu.get(obj.id)
            if gpu is None or not gpu.tri_count:
                continue
            b = obj.mesh.bounds() if obj.mesh_ready else None
            if b is None or b[0][2] < -1e-6:
                continue                    # below the plane: no stamp
            GL.glBindVertexArray(gpu.tri_vao)
            GL.glDrawElements(GL.GL_TRIANGLES, gpu.tri_count,
                              GL.GL_UNSIGNED_INT, ctypes.c_void_p(0))
        GL.glDepthMask(True)

    def _draw_edges(self, gpu, mvp, color, width: float):
        """Object edges at a given pixel width. Wide lines fall back to a
        screen-space quad shader where GL_LINES are capped (llvmpipe)."""
        if width <= self._max_line_width + 0.25 or not gpu.thick_count:
            self._set_line_uniforms(mvp, color)
            self._line_width(width)
            GL.glBindVertexArray(gpu.line_vao)
            GL.glDrawArrays(GL.GL_LINES, 0, gpu.line_count)
            return
        prog = self._thick_prog
        GL.glUseProgram(prog)
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(prog, "uMVP"), 1,
                              GL.GL_TRUE, mvp.astype(np.float32))
        GL.glUniform2f(GL.glGetUniformLocation(prog, "uViewport"),
                       float(self.width()), float(self.height()))
        GL.glUniform1f(GL.glGetUniformLocation(prog, "uWidthPx"),
                       float(width))
        GL.glUniform4f(GL.glGetUniformLocation(prog, "uColor"), *color)
        GL.glBindVertexArray(gpu.thick_vao)
        GL.glDrawElements(GL.GL_TRIANGLES, gpu.thick_count,
                          GL.GL_UNSIGNED_INT, ctypes.c_void_p(0))

    def _draw_preview(self, mvp):
        pts = self._preview_data
        markers = self._marker_points
        snap = self._active_snap if self.point_mode else None
        if len(pts) == 0 and not markers and snap is None:
            return
        segs = [pts] if len(pts) else []
        # screen-scaled cross markers at picked points
        if self.space != "model":
            size = 5.0 / max(self.layout_view.px_per_mm, 1e-6)
        else:
            size = self.camera.distance * 0.008
        for m in markers:
            m = np.asarray(m, np.float32)
            for axis in np.eye(3, dtype=np.float32) * size:
                segs.append(np.stack([m - axis, m + axis]))
        GL.glDisable(GL.GL_DEPTH_TEST)
        if segs:
            allpts = np.concatenate(segs).astype(np.float32)
            self._preview.update(allpts)
            self._draw_lines(self._preview, mvp,
                             (*theme.SELECTION_COLOR, 0.9), 1.6)
        if snap is not None:
            segs = _snap_marker(snap[1], np.asarray(snap[0], np.float32),
                                *self.camera.right_up(), size * 0.95)
            self._preview.update(segs)
            self._draw_lines(self._preview, mvp, (1.0, 1.0, 1.0, 0.95), 2.0)
        GL.glEnable(GL.GL_DEPTH_TEST)

    def _draw_control_points(self, mvp):
        if not self.cv_enabled:
            return
        size = self.camera.distance * 0.006
        GL.glDisable(GL.GL_DEPTH_TEST)
        for obj_id in list(self.cv_enabled):
            obj = self.scene.get(obj_id)
            if obj is None:
                self.cv_enabled.discard(obj_id)
                continue
            pts, grid = self._cv_entry(obj)
            if pts is None or len(pts) < 2:
                continue
            # control polygon (or control net for surfaces)
            segs = []
            if grid is None:
                segs.append(np.stack([pts[:-1], pts[1:]], axis=1))
            else:
                nu, nv = grid
                net = pts.reshape(nu, nv, 3)
                for i in range(nu):
                    segs.append(np.stack([net[i, :-1], net[i, 1:]], axis=1))
                for j in range(nv):
                    segs.append(np.stack([net[:-1, j], net[1:, j]], axis=1))
            poly = np.concatenate(segs).reshape(-1, 3)
            self._preview.update(poly.astype(np.float32))
            self._draw_lines(self._preview, mvp, (0.6, 0.62, 0.66, 0.5), 1.0)
            # CV markers as crosses
            segs = []
            for p in pts:
                p = p.astype(np.float32)
                for axis in np.eye(3, dtype=np.float32)[:2] * size:
                    segs.append(np.stack([p - axis, p + axis]))
            self._preview.update(np.concatenate(segs).astype(np.float32))
            self._draw_lines(self._preview, mvp, (1.0, 1.0, 1.0, 0.95), 2.0)
        GL.glEnable(GL.GL_DEPTH_TEST)

    def _draw_combs(self, mvp):
        """Curvature combs: quills perpendicular to the curve, length
        proportional to curvature."""
        if not self.comb_enabled:
            return
        from ..core import geometry as _g
        from OCP.BRepLProp import BRepLProp_CLProps
        GL.glDisable(GL.GL_DEPTH_TEST)
        for obj_id in list(self.comb_enabled):
            obj = self.scene.get(obj_id)
            if obj is None or obj.kind != "curve":
                self.comb_enabled.discard(obj_id)
                continue
            quills = []
            envelope = []
            max_k = 1e-12
            samples = []
            for edge in _g.edges_of(obj.shape):
                ad = _g.occ.edge_adaptor(edge)
                t0, t1 = ad.FirstParameter(), ad.LastParameter()
                props = BRepLProp_CLProps(ad, 2, 1e-9)
                for i in range(81):
                    t = t0 + (t1 - t0) * i / 80
                    props.SetParameter(t)
                    p = props.Value()
                    k = props.Curvature()
                    n = _g.gp_Dir()
                    if k > 1e-12:
                        try:
                            props.Normal(n)
                        except Exception:
                            k = 0.0
                    samples.append((np.array([p.X(), p.Y(), p.Z()]),
                                    np.array([n.X(), n.Y(), n.Z()]), k))
                    max_k = max(max_k, k)
            scale = self.camera.distance * 0.12 / max_k
            prev_tip = None
            for (p, n, k) in samples:
                tip = p - n * k * scale
                quills.append(np.stack([p, tip]))
                if prev_tip is not None:
                    envelope.append(np.stack([prev_tip, tip]))
                prev_tip = tip
            for segs, color, width in (
                    (quills, (0.9, 0.45, 0.85, 0.55), 1.0),
                    (envelope, (0.9, 0.45, 0.85, 0.9), 1.4)):
                if segs:
                    arr = np.concatenate(segs).astype(np.float32)
                    self._preview.update(arr)
                    self._set_line_uniforms(mvp, color)
                    self._line_width(width)
                    GL.glBindVertexArray(self._preview.vao)
                    GL.glDrawArrays(GL.GL_LINES, 0, len(arr))
        GL.glEnable(GL.GL_DEPTH_TEST)

    def _draw_selection_box(self, w, h):
        if not self._box_active or self._press_pos is None \
                or self._box_end is None:
            return
        def ndc(px, py):
            return (2 * px / max(w, 1) - 1, 1 - 2 * py / max(h, 1), 0.0)
        a = ndc(self._press_pos.x(), self._press_pos.y())
        b = ndc(self._box_end.x(), self._box_end.y())
        corners = np.array([
            a, (b[0], a[1], 0), (b[0], a[1], 0), b,
            b, (a[0], b[1], 0), (a[0], b[1], 0), a,
        ], np.float32)
        crossing = self._box_end.x() < self._press_pos.x()
        color = ((0.9, 0.9, 0.9, 0.8) if crossing
                 else (*theme.SELECTION_COLOR, 0.9))
        GL.glDisable(GL.GL_DEPTH_TEST)
        self._preview.update(corners)
        self._draw_lines(self._preview, np.eye(4, dtype=np.float32),
                         color, 1.0)
        GL.glEnable(GL.GL_DEPTH_TEST)

    def _draw_frame_guides(self, w, h):
        """Cinema aspect-ratio frame guides with dimmed letterbox."""
        if not self.frame_aspect:
            return
        margin = 0.04
        avail_w = w * (1 - 2 * margin)
        avail_h = h * (1 - 2 * margin)
        if avail_w / avail_h > self.frame_aspect:
            fh = avail_h
            fw = fh * self.frame_aspect
        else:
            fw = avail_w
            fh = fw / self.frame_aspect
        x0, x1 = (w - fw) / 2, (w + fw) / 2
        y0, y1 = (h - fh) / 2, (h + fh) / 2

        def ndc(px, py):
            return (2 * px / w - 1, 1 - 2 * py / h, 0.0)

        GL.glDisable(GL.GL_DEPTH_TEST)
        # dim outside the frame
        quads = [
            (0, 0, w, y0), (0, y1, w, h),
            (0, y0, x0, y1), (x1, y0, w, y1),
        ]
        for (qx0, qy0, qx1, qy1) in quads:
            a, b = ndc(qx0, qy0), ndc(qx1, qy0)
            c, d = ndc(qx1, qy1), ndc(qx0, qy1)
            tris = np.array([a, b, c, a, c, d], np.float32)
            self._preview.update(tris)
            self._set_line_uniforms(np.eye(4, dtype=np.float32),
                                    (0.02, 0.02, 0.03, 0.55))
            GL.glBindVertexArray(self._preview.vao)
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, 6)
        # frame outline + centre cross
        corners = [ndc(x0, y0), ndc(x1, y0), ndc(x1, y1), ndc(x0, y1)]
        segs = []
        for i in range(4):
            segs.append(np.array([corners[i], corners[(i + 1) % 4]]))
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        cross = min(fw, fh) * 0.03
        segs.append(np.array([ndc(cx - cross, cy), ndc(cx + cross, cy)]))
        segs.append(np.array([ndc(cx, cy - cross), ndc(cx, cy + cross)]))
        pts = np.concatenate(segs).astype(np.float32)
        self._preview.update(pts)
        self._set_line_uniforms(np.eye(4, dtype=np.float32),
                                (0.95, 0.85, 0.55, 0.9))
        self._line_width(1.4)
        GL.glBindVertexArray(self._preview.vao)
        GL.glDrawArrays(GL.GL_LINES, 0, len(pts))
        GL.glEnable(GL.GL_DEPTH_TEST)

    def _draw_axis_triad(self, view, w, h):
        """Small world-axis indicator in the bottom-left corner (NDC space)."""
        rot = view[:3, :3]
        size = 0.055
        aspect = w / max(h, 1)
        cx, cy = -0.92, -0.86
        origin = np.array([cx, cy, 0.0], np.float32)
        segs, colors = [], []
        for axis, color in (((1, 0, 0), theme.GRID_AXIS_X),
                            ((0, 1, 0), theme.GRID_AXIS_Y),
                            ((0, 0, 1), (0.35, 0.55, 0.9, 0.9))):
            d = rot @ np.asarray(axis, np.float32)
            tip = origin + np.array([d[0] * size / aspect, d[1] * size, 0.0],
                                    np.float32)
            segs.append(np.stack([origin, tip]))
            colors.append(color)
        GL.glDisable(GL.GL_DEPTH_TEST)
        identity = np.eye(4, dtype=np.float32)
        for seg, color in zip(segs, colors):
            self._preview.update(seg.astype(np.float32))
            self._set_line_uniforms(identity, color)
            self._line_width(2.0)
            GL.glBindVertexArray(self._preview.vao)
            GL.glDrawArrays(GL.GL_LINES, 0, 2)
        GL.glEnable(GL.GL_DEPTH_TEST)
        self._line_width(1.0)

    # ------------------------------------------------------------- public API

    def set_ghost(self, shape):
        """Translucent preview of a pending command result (or None)."""
        if shape is None:
            if self._ghost is not None:
                self._ghost = None
                self.update()
            return
        try:
            from ..core.tessellate import tessellate
            self._ghost = tessellate(shape)
        except Exception:                                  # noqa: BLE001
            self._ghost = None
        self.update()

    def _draw_ghost(self, mvp):
        dm = self._ghost
        if dm is None or self._preview is None:
            return
        gold = theme.SELECTION_COLOR
        if dm.has_faces and len(dm.triangles):
            pts = dm.vertices[dm.triangles.ravel()]
            self._preview.update(pts.astype(np.float32))
            self._set_line_uniforms(mvp, (*gold, 0.22))
            GL.glDepthMask(False)
            GL.glBindVertexArray(self._preview.vao)
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, len(pts))
            GL.glDepthMask(True)
        if len(dm.edge_segments):
            segs = dm.edge_segments.reshape(-1, 3).astype(np.float32)
            self._preview.update(segs)
            self._set_line_uniforms(mvp, (*gold, 0.85))
            self._line_width(1.6)
            GL.glBindVertexArray(self._preview.vao)
            GL.glDrawArrays(GL.GL_LINES, 0, len(segs))
            self._line_width(1.0)

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
        if mode not in ("shaded", "wireframe", "ghosted", "zebra",
                        "curvature", "technical", "draft", "rendered"):
            raise ValueError(f"Unknown display mode '{mode}'")
        self.display_mode = mode
        self.update()

    def zoom_extents(self):
        self.camera.zoom_extents(self.scene.bbox())
        self.update()

    def zoom_selected(self) -> bool:
        """Frame the selection. False when nothing is selected."""
        objs = [o for i in self.selection.ids
                if (o := self.scene.get(i)) is not None]
        if not objs:
            return False
        from ..core import geometry as g
        mins = np.full(3, np.inf)
        maxs = np.full(3, -np.inf)
        for o in objs:
            mn, mx = g.bbox(o.shape)
            mins = np.minimum(mins, mn)
            maxs = np.maximum(maxs, mx)
        self.camera.zoom_extents((tuple(mins), tuple(maxs)))
        self.update()
        return True

    def zoom_to_points(self, p1, p2):
        """Frame the axis-aligned window spanned by two world points."""
        mn = np.minimum(np.asarray(p1, float), np.asarray(p2, float))
        mx = np.maximum(np.asarray(p1, float), np.asarray(p2, float))
        pad = max(float(np.linalg.norm(mx - mn)) * 0.05, 0.5)
        self.camera.zoom_extents((tuple(mn - pad), tuple(mx + pad)))
        self.update()

    def set_view(self, name: str):
        self.camera.set_standard_view(name)
        self.update()

    def screenshot(self, path: str) -> bool:
        img = self.grabFramebuffer()
        return img.save(path)

    def render_detail_image(self, detail, px_w: int, px_h: int):
        """Render a detail's 3D content offscreen (for PDF export)."""
        from PySide6.QtOpenGL import QOpenGLFramebufferObject
        self.makeCurrent()
        try:
            fbo = QOpenGLFramebufferObject(
                px_w, px_h,
                QOpenGLFramebufferObject.Attachment.CombinedDepthStencil)
            fbo.bind()
            GL.glViewport(0, 0, px_w, px_h)
            GL.glClearColor(0.98, 0.98, 0.97, 1.0)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
            GL.glEnable(GL.GL_DEPTH_TEST)
            self._sync_gpu()
            proj, view = self.layout_view.detail_matrices(detail, px_w, px_h)
            mvp = (proj @ view).astype(np.float32)
            self._draw_objects(mvp, view,
                               mode_override=detail.display_mode,
                               light_background=True)
            img = fbo.toImage()
            fbo.release()
            ratio = self.devicePixelRatioF()
            GL.glViewport(0, 0, int(self.width() * ratio),
                          int(self.height() * ratio))
            return img
        except Exception:
            return None
        finally:
            self.doneCurrent()

    # -------------------------------------------------------------- picking

    def window_checkpoint(self, label: str):
        if self.history is not None:
            self.history.checkpoint(label)

    def window_discard_checkpoint(self):
        if self.history is not None:
            self.history.discard_checkpoint()

    def set_space(self, space: str):
        """Switch between model space and a layout (by id)."""
        self.space = space
        self.layout_view.entered_detail = None
        if space != "model":
            self.layout_view._fitted_for = None
        self.set_preview(None)
        self.update()

    def world_point_at(self, px: float, py: float):
        """Point for the pixel: object snap if near one, else CPlane (z=0).

        In a layout, returns paper coordinates in millimetres (x, y, 0)."""
        if self.space != "model":
            self._active_snap = None
            x, y = self.layout_view.screen_to_paper(px, py)
            if self.grid_snap:
                x, y = round(x), round(y)
            return (float(x), float(y), 0.0)
        if self.point_axis is not None:
            base, axis = (np.asarray(v, float) for v in self.point_axis)
            self._active_snap = None
            origin, direction = self.camera.ray_through(
                px, py, self.width(), self.height())
            t = ray_line_parameter(origin, direction, base, axis)
            if t is None:
                return None
            if self.grid_snap:
                t = round(t / self.grid_snap_step) * self.grid_snap_step
            return tuple(float(c) for c in base + t * normalize(axis))
        snap = self.snaps.find(self.camera, px, py, self.width(),
                               self.height(), base_point=self.snap_base)
        if snap is not None:
            self._active_snap = snap
            return snap[0]
        self._active_snap = None
        origin, direction = self.camera.ray_through(px, py, self.width(),
                                                    self.height())
        hit = ray_plane(origin, direction, self.cplane.origin,
                        self.cplane.normal)
        if hit is None:
            return None
        if self.grid_snap:
            hit = np.asarray(
                self.cplane.snap_to_grid(hit, self.grid_snap_step))
        # ortho: Shift constrains to the dominant CPlane axis from the base
        if (self.snap_base is not None
                and QApplication.queryKeyboardModifiers()
                & Qt.KeyboardModifier.ShiftModifier):
            bu, bv, bw = self.cplane.from_world(self.snap_base)
            u, v, w = self.cplane.from_world(hit)
            if abs(u - bu) >= abs(v - bv):
                hit = np.asarray(self.cplane.to_world(u, bv, w))
            else:
                hit = np.asarray(self.cplane.to_world(bu, v, w))
        return tuple(round(float(c), 9) for c in hit)

    def _pick_reject(self, mesh, x0, y0, x1, y1, w, h) -> bool:
        """True if the mesh's bbox projects fully outside a screen rect."""
        b = mesh.bounds()
        if b is None:
            return True
        mn, mx = b
        corners = np.array([(x, y, z) for x in (mn[0], mx[0])
                            for y in (mn[1], mx[1])
                            for z in (mn[2], mx[2])])
        scr = self.camera.project(corners, w, h)
        if (scr[:, 2] <= 0).any():
            return False                # crosses the camera plane: keep
        return bool(scr[:, 0].max() < x0 or scr[:, 0].min() > x1
                    or scr[:, 1].max() < y0 or scr[:, 1].min() > y1)

    def pick_object(self, px: float, py: float) -> str | None:
        w, h = self.width(), self.height()
        origin, direction = self.camera.ray_through(px, py, w, h)
        best_id, best_depth = None, np.inf

        r = PICK_RADIUS_PX
        for obj in self.scene.visible_objects():
            if not self.scene.is_selectable(obj.id):
                continue
            mesh = obj.mesh
            if self._pick_reject(mesh, px - r, py - r, px + r, py + r, w, h):
                continue
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

    def pick_subobject(self, px: float, py: float):
        """(obj_id, "edge"|"face", index) under the pixel, or None."""
        w, h = self.width(), self.height()
        origin, direction = self.camera.ray_through(px, py, w, h)
        # edges first (they are the smaller target)
        best_edge = None
        best_d2 = PICK_RADIUS_PX ** 2
        r = PICK_RADIUS_PX
        for obj in self.scene.visible_objects():
            if not self.scene.is_selectable(obj.id):
                continue
            mesh = obj.mesh
            if not len(mesh.edge_segments):
                continue
            if self._pick_reject(mesh, px - r, py - r, px + r, py + r, w, h):
                continue
            pts = mesh.edge_segments.reshape(-1, 3)
            scr = self.camera.project(pts, w, h)
            a, b = scr[0::2], scr[1::2]
            d2 = _point_segment_dist2(np.array([px, py]), a[:, :2],
                                      b[:, :2])
            valid = (a[:, 2] > 0) & (b[:, 2] > 0)
            d2[~valid] = np.inf
            i = int(np.argmin(d2))
            if d2[i] < best_d2 and len(mesh.edge_of_segment) > i:
                best_d2 = d2[i]
                best_edge = (obj.id, "edge", int(mesh.edge_of_segment[i]))
        if best_edge is not None:
            return best_edge
        # faces by nearest ray-triangle hit
        best_face = None
        best_t = np.inf
        for obj in self.scene.visible_objects():
            if not self.scene.is_selectable(obj.id):
                continue
            mesh = obj.mesh
            if not mesh.has_faces or not len(mesh.face_of_triangle):
                continue
            tris = mesh.triangles
            t = ray_triangle_hits(origin, direction,
                                  mesh.vertices[tris[:, 0]].astype(float),
                                  mesh.vertices[tris[:, 1]].astype(float),
                                  mesh.vertices[tris[:, 2]].astype(float))
            i = int(np.argmin(t))
            if np.isfinite(t[i]) and t[i] < best_t:
                best_t = t[i]
                best_face = (obj.id, "face",
                             int(mesh.face_of_triangle[i]))
        return best_face

    # ---------------------------------------------------------------- events

    def mouseDoubleClickEvent(self, ev):
        if (self.space != "model" and not self.point_mode
                and ev.button() == Qt.MouseButton.LeftButton):
            pos = ev.position()
            self.layout_view.double_click(pos.x(), pos.y())
            self.update()
            return
        super().mouseDoubleClickEvent(ev)

    def mousePressEvent(self, ev):
        self._last_mouse = ev.position()
        if ev.button() == Qt.MouseButton.LeftButton:
            pos = ev.position()
            if self.point_mode:
                pt = self.world_point_at(pos.x(), pos.y())
                if pt is not None:
                    self.pointPicked.emit(pt)
                return
            if self.space != "model":
                if self.layout_view.click_outside_exits(pos.x(), pos.y()):
                    self.update()
                    return
                if self.layout_view.press(pos.x(), pos.y()):
                    self.update()
                return
            handle = self.gumball.hit_test(pos.x(), pos.y())
            if handle is not None:
                if self.gumball.begin_drag(handle, pos.x(), pos.y(),
                                           ev.modifiers()):
                    self.update()
                    return
            cv = self._cv_hit(pos.x(), pos.y())
            if cv is not None:
                obj_id, index, world = cv
                fwd = (self.camera.target - self.camera.position)
                fwd = fwd / max(np.linalg.norm(fwd), 1e-12)
                self._cv_drag = (obj_id, index, np.asarray(world), fwd)
                self.cvEditBegan.emit()
                return
            self._press_pos = pos
            self._box_active = False

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._last_mouse is None:
            self._last_mouse = pos
        dx = pos.x() - self._last_mouse.x()
        dy = pos.y() - self._last_mouse.y()
        if self.space != "model":
            if ev.buttons() & Qt.MouseButton.LeftButton \
                    and self.layout_view.drag_selected(pos.x(), pos.y()):
                self._last_mouse = pos
                self.update()
                return
            if ev.buttons() & self._nav_button():
                orbit = not (ev.modifiers()
                             & Qt.KeyboardModifier.ShiftModifier)
                self.layout_view.drag(dx, dy, orbit)
                self.update()
            elif self.point_mode:
                pt = self.world_point_at(pos.x(), pos.y())
                if pt is not None:
                    self.mouseWorldMoved.emit(pt)
            self._last_mouse = pos
            return
        if ev.buttons() & self._nav_button():
            speed = (float(self.config.get("mouse", "orbit_speed",
                                           default=1.0))
                     if self.config else 1.0)
            if ev.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self.camera.pan(dx, dy, self.height())
            else:
                self.camera.orbit(dx * speed, dy * speed)
            self.update()
        elif self.gumball.drag is not None:
            label = self.gumball.drag_to(pos.x(), pos.y(), ev.modifiers())
            if label:
                from PySide6.QtWidgets import QMainWindow
                win = self.window()
                if isinstance(win, QMainWindow):
                    win.statusBar().showMessage(label)
            self.update()
        elif (not ev.buttons() and self.space == "model"
                and not self.point_mode):
            if self.gumball.update_hover(pos.x(), pos.y()):
                self.update()
        elif self._cv_drag is not None:
            obj_id, index, plane_pt, normal = self._cv_drag
            origin, direction = self.camera.ray_through(
                pos.x(), pos.y(), self.width(), self.height())
            hit = ray_plane(origin, direction, plane_pt, normal)
            if hit is not None:
                from ..core import geometry as _g
                obj = self.scene.get(obj_id)
                if obj is not None:
                    try:
                        if obj.kind == "surface":
                            new_shape = _g.move_surface_control_point(
                                obj.shape, index, tuple(hit))
                        else:
                            new_shape = _g.move_control_point(
                                obj.shape, index, tuple(hit))
                        self.scene.replace_shape(obj_id, new_shape)
                        self._cv_drag = (obj_id, index, plane_pt, normal)
                    except _g.GeometryError:
                        pass
        elif (self._press_pos is not None
                and ev.buttons() & Qt.MouseButton.LeftButton):
            if (abs(pos.x() - self._press_pos.x()) > 4
                    or abs(pos.y() - self._press_pos.y()) > 4):
                self._box_active = True
                self._box_end = pos
                self.update()
        elif self.point_mode:
            pt = self.world_point_at(pos.x(), pos.y())
            if pt is not None:
                self.mouseWorldMoved.emit(pt)
        self._last_mouse = pos

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.MouseButton.LeftButton:
            if (ev.button() == self._nav_button()
                    and self.display_mode == "technical"):
                self.update()      # navigation ended: recompute HLR view
            return
        if self.space != "model":
            self.layout_view.release_drag()
        if self.gumball.drag is not None:
            self.gumball.end_drag()
            self.update()
            return
        if self._cv_drag is not None:
            self._cv_drag = None
            return
        if self._box_active and self._press_pos is not None:
            x0, y0 = self._press_pos.x(), self._press_pos.y()
            x1, y1 = self._box_end.x(), self._box_end.y()
            crossing = x1 < x0            # drag right-to-left = crossing
            ids = self._box_pick(x0, y0, x1, y1, crossing)
            self._box_active = False
            self._press_pos = None
            self._box_end = None
            self.boxSelected.emit(ids, ev.modifiers())
            self.update()
            return
        if self._press_pos is not None:
            pos = ev.position()
            self._press_pos = None
            if self.point_mode:
                return
            mods = ev.modifiers()
            if (mods & Qt.KeyboardModifier.ControlModifier
                    and mods & Qt.KeyboardModifier.ShiftModifier
                    and self.space == "model"):
                hit = self.pick_subobject(pos.x(), pos.y())
                if hit is not None:
                    self.selection.toggle_subobject(*hit)
                    self.update()
                return
            picked = self.pick_object(pos.x(), pos.y())
            if picked:
                self.objectClicked.emit(picked, ev.modifiers())
            else:
                self.emptyClicked.emit(ev.modifiers())

    def _box_pick(self, x0, y0, x1, y1, crossing: bool) -> list[str]:
        rect = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
        w, h = self.width(), self.height()
        picked = []
        for obj in self.scene.visible_objects():
            if not self.scene.is_selectable(obj.id):
                continue
            mesh = obj.mesh
            if self._pick_reject(mesh, *rect, w, h):
                continue
            if len(mesh.edge_segments):
                pts = mesh.edge_segments.reshape(-1, 3)
            elif len(mesh.vertices):
                pts = mesh.vertices
            else:
                continue
            scr = self.camera.project(pts.astype(float), w, h)
            valid = scr[:, 2] > 0
            if not valid.any():
                continue
            inside = ((scr[:, 0] >= rect[0]) & (scr[:, 0] <= rect[2])
                      & (scr[:, 1] >= rect[1]) & (scr[:, 1] <= rect[3])
                      & valid)
            if crossing:
                if inside.any():
                    picked.append(obj.id)
            else:
                if valid.all() and inside.all():
                    picked.append(obj.id)
        return picked

    # -------------------------------------------------------- control points

    def _cv_points(self, obj) -> np.ndarray | None:
        return self._cv_entry(obj)[0]

    def _cv_entry(self, obj) -> tuple:
        """(points, grid) — grid is (nu, nv) for surfaces, None for curves."""
        from ..core import geometry as _g
        entry = self._cv_cache.get(obj.id)
        key = id(obj.mesh)
        if entry is None or entry[0] != key:
            try:
                if obj.kind == "surface":
                    pts, grid = _g.surface_control_points(obj.shape)
                    pts = np.asarray(pts, float)
                else:
                    pts = np.asarray(_g.get_control_points(obj.shape), float)
                    grid = None
            except _g.GeometryError:
                return (None, None)
            entry = (key, pts, grid)
            self._cv_cache[obj.id] = entry
        return (entry[1], entry[2])

    def _cv_hit(self, px, py):
        """(obj_id, index, world_pos) of a control point near the pixel."""
        w, h = self.width(), self.height()
        best = None
        best_d2 = 8.0 ** 2
        for obj_id in list(self.cv_enabled):
            obj = self.scene.get(obj_id)
            if obj is None:
                self.cv_enabled.discard(obj_id)
                continue
            pts = self._cv_points(obj)
            if pts is None or not len(pts):
                continue
            scr = self.camera.project(pts, w, h)
            d2 = (scr[:, 0] - px) ** 2 + (scr[:, 1] - py) ** 2
            d2[scr[:, 2] <= 0] = np.inf
            i = int(np.argmin(d2))
            if d2[i] < best_d2:
                best_d2 = d2[i]
                best = (obj_id, i, tuple(pts[i]))
        return best

    def _nav_button(self) -> Qt.MouseButton:
        """The mouse button used for orbit/pan (configurable)."""
        name = (self.config.get("mouse", "orbit_button", default="middle")
                if self.config else "middle")
        return (Qt.MouseButton.RightButton if name == "right"
                else Qt.MouseButton.MiddleButton)

    def wheelEvent(self, ev):
        steps = ev.angleDelta().y() / 120.0
        if self.config:
            if self.config.get("mouse", "invert_scroll", default=False):
                steps = -steps
            steps *= float(self.config.get("mouse", "zoom_speed",
                                           default=1.0))
        if self.space != "model":
            pos = ev.position()
            self.layout_view.wheel(steps, pos.x(), pos.y())
            self.update()
            return
        pos = ev.position()
        origin, direction = self.camera.ray_through(
            pos.x(), pos.y(), self.width(), self.height())
        anchor = ray_plane_any(
            origin, direction, self.camera.target,
            normalize(self.camera.target - self.camera.position))
        before = self.camera.distance
        self.camera.zoom(steps)
        if anchor is not None and (self.config is None or self.config.get(
                "mouse", "zoom_to_cursor", default=True)):
            f = self.camera.distance / before
            self.camera.target = anchor + (self.camera.target - anchor) * f
        self.update()

    _NUDGE_KEYS = {
        Qt.Key.Key_Left: (-1, 0, 0), Qt.Key.Key_Right: (1, 0, 0),
        Qt.Key.Key_Down: (0, -1, 0), Qt.Key.Key_Up: (0, 1, 0),
        Qt.Key.Key_PageDown: (0, 0, -1), Qt.Key.Key_PageUp: (0, 0, 1),
    }

    def _nudge(self, direction) -> bool:
        ids = [i for i in self.selection.ids
               if (o := self.scene.get(i)) is not None and not o.locked]
        if not ids:
            return False
        from ..core import geometry as g
        step = self.grid_snap_step if self.grid_snap else 1.0
        mods = QApplication.queryKeyboardModifiers()
        if mods & Qt.KeyboardModifier.ShiftModifier:
            step *= 10.0
        if mods & Qt.KeyboardModifier.ControlModifier:
            step *= 0.1
        vec = (self.cplane.xdir * direction[0]
               + self.cplane.ydir * direction[1]
               + self.cplane.normal * direction[2]) * step
        self.window_checkpoint("nudge")
        for oid in ids:
            obj = self.scene.get(oid)
            self.scene.replace_shape(oid, g.translate(obj.shape, tuple(vec)))
        self.update()
        return True

    def keyPressEvent(self, ev):
        if self.space != "model":
            lv = self.layout_view
            if ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) \
                    and lv.delete_selected():
                self.update()
                return
            if ev.key() == Qt.Key.Key_Escape and lv.selected is not None:
                lv.selected = None
                self.update()
                return
        d = self._NUDGE_KEYS.get(ev.key())
        if d is not None and self.space == "model" and self.selection.ids \
                and self._nudge(d):
            return
        if ev.key() == Qt.Key.Key_Escape:
            if self.gumball.drag is not None:
                self.gumball.cancel_drag()
                self.update()
                return
            self.escapePressed.emit()
        else:
            super().keyPressEvent(ev)


def _bbox_segments(mn, mx) -> np.ndarray:
    """12 AABB edges as GL_LINES vertices (24, 3)."""
    xs = (mn[0], mx[0])
    ys = (mn[1], mx[1])
    zs = (mn[2], mx[2])
    c = [(x, y, z) for x in xs for y in ys for z in zs]
    pairs = [(0, 1), (2, 3), (4, 5), (6, 7),      # z edges
             (0, 2), (1, 3), (4, 6), (5, 7),      # y edges
             (0, 4), (1, 5), (2, 6), (3, 7)]      # x edges
    out = []
    for a, b in pairs:
        out.append(c[a])
        out.append(c[b])
    return np.asarray(out, np.float32)


def _snap_marker(kind: str, c: np.ndarray, right: np.ndarray,
                 up: np.ndarray, s: float) -> np.ndarray:
    """Distinct marker glyph per snap type, as GL_LINES vertex pairs."""
    r = (right * s).astype(np.float32)
    u = (up * s).astype(np.float32)
    c = c.astype(np.float32)

    def loop(pts):
        return [np.stack([pts[i], pts[(i + 1) % len(pts)]])
                for i in range(len(pts))]

    if kind == "end":                     # square
        segs = loop([c - r - u, c + r - u, c + r + u, c - r + u])
    elif kind == "mid":                   # triangle
        segs = loop([c - r - u, c + r - u, c + u])
    elif kind == "center":                # octagon ~ circle
        pts = []
        for k in range(8):
            a = k * np.pi / 4
            pts.append(c + r * np.cos(a) + u * np.sin(a))
        segs = loop(pts)
    elif kind == "quad":                  # diamond
        segs = loop([c - r, c - u, c + r, c + u])
    elif kind == "int":                   # X
        segs = [np.stack([c - r - u, c + r + u]),
                np.stack([c - r + u, c + r - u])]
    elif kind == "perp":                  # perpendicular glyph
        segs = [np.stack([c - r - u, c + r - u]),
                np.stack([c - u, c + u])]
    else:                                 # near: slash
        segs = [np.stack([c - r - u, c + r + u]),
                np.stack([c - r, c + r])]
    return np.concatenate(segs).astype(np.float32)


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
