"""3D OpenGL viewport: rendering, navigation, picking."""

from __future__ import annotations

import ctypes
import math
import os
import sys

import numpy as np
from OpenGL import GL
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor, QSurfaceFormat
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QApplication, QMessageBox

from ..core import linetype as _lt
from ..core import spatial
from ..utils import config as _cfg
from ..utils import units as _units
from ..utils.math3d import (normalize, ray_line_parameter, ray_plane, ray_plane_any, ray_triangle_hits)
from . import theme
from .camera import Camera

PICK_RADIUS_PX = 7.0

# Two edges this close to each other on screen are both taken to be under the
# cursor, and the one in front wins. Without a band, depth alone would let an
# edge seven pixels away steal a click aimed squarely at one you can see; with
# it, only edges you could plausibly have meant compete, and among those the
# front-most is the one you meant.
PICK_DEPTH_BAND_PX = 4.0

# which end of a bounding box each of its eight corners takes per axis
_BOX_CORNERS = np.array([(x, y, z) for x in (False, True)
                         for y in (False, True)
                         for z in (False, True)])

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
uniform int uClipCount;
uniform vec4 uClips[4];
out float gl_ClipDistance[4];
void main() {
    gl_Position = uMVP * vec4(pos, 1.0);
    for (int i = 0; i < uClipCount; ++i)
        gl_ClipDistance[i] = dot(uClips[i], vec4(pos, 1.0));

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
uniform int uClipCount;
uniform vec4 uClips[4];
out float gl_ClipDistance[4];
void main() {
    gl_Position = uMVP * vec4(pos, 1.0);
    for (int i = 0; i < uClipCount; ++i)
        gl_ClipDistance[i] = dot(uClips[i], vec4(pos, 1.0));
}
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
uniform int uClipCount;
uniform vec4 uClips[4];
out float gl_ClipDistance[4];
void main() {
    for (int i = 0; i < uClipCount; ++i)
        gl_ClipDistance[i] = dot(uClips[i], vec4(pos, 1.0));

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


def _dashed_edge_segments(mesh, pattern, scale):
    """Rebuild the object's edge segments as dash segments: regroup the
    flattened GL_LINES back into per-edge polylines (via edge_of_segment) and
    run each through the linetype dasher."""
    from ..core.linetype import dash_polyline
    segs = mesh.edge_segments
    eos = getattr(mesh, "edge_of_segment", None)
    if eos is None or not len(segs):
        return segs
    out = []
    eos = np.asarray(eos)
    for edge_id in np.unique(eos):
        es = segs[eos == edge_id]                 # (n, 2, 3) in edge order
        poly = np.vstack([es[:, 0, :], es[-1:, 1, :]])
        out.extend(dash_polyline(poly, pattern, scale))
    if not out:
        return np.zeros((0, 2, 3), np.float32)
    return np.asarray(out, np.float32)


class _GpuObject:
    """GPU buffers for one scene object."""

    def __init__(self, mesh, dash=None, dash_key=None):
        # The mesh's own serial, not id(mesh): the question "are these
        # buffers still current?" is asked after the mesh they came from may
        # have been freed, and an address gets recycled. See DisplayMesh.uid.
        self.mesh_key = mesh.uid
        self.dash_key = dash_key                  # linetype identity for cache
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
        edge_segments = mesh.edge_segments
        if dash and dash[0]:                          # (pattern, scale)
            edge_segments = _dashed_edge_segments(mesh, dash[0], dash[1])
        if len(edge_segments):
            self.line_vao, self.line_count = self._make_line_vao(
                edge_segments)
            self.thick_vao, self.thick_count = self._make_thick_vao(
                edge_segments)
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
    tabPressed = Signal()                   # Tab while a point is wanted
    enterShortcut = Signal()                # right-click without dragging
    popupRequested = Signal()               # middle-click without dragging
    chordActivated = Signal(str)            # a bound mouse chord: command
    displayModeChanged = Signal()           # shaded/rendered/... changed
    viewChanged = Signal(str)               # named view set (top/perspective/…)
    layoutSelectionChanged = Signal()       # sheet items picked or dropped
    detailEntered = Signal(object)           # stepped into a detail mid-command
    _tessDone = Signal()                    # a background mesh finished

    def __init__(self, scene, selection, config=None, parent=None):
        super().__init__(parent)
        self.scene = scene
        self.selection = selection
        self.config = config
        self.camera = Camera()
        self.display_mode = "shaded"        # shaded | wireframe | ghosted
        self._view_name = "perspective"     # last-picked named view (for HUD)
        self.grid_visible = True
        self.point_mode = False             # command wants a point click
        from ..core.cplane import CPlane
        self.cplane = CPlane()
        from .layout_view import LayoutView
        self.space = "model"                # "model" | layout id
        self.layout_view = LayoutView(self)
        from .gumball import Gumball
        self.gumball = Gumball(self)
        from PySide6.QtWidgets import QLabel
        self._gumball_readout = QLabel(self)
        self._gumball_readout.setStyleSheet(
            "QLabel { background: rgba(20,21,24,225); color: #e6d896;"
            " border: 1px solid #4a4b52; border-radius: 4px;"
            " padding: 2px 7px; font-family: monospace; }")
        self._gumball_readout.setVisible(False)
        self._gumball_readout.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._draw_readout = QLabel(self)   # length of the rubber-band leg
        self._draw_readout.setStyleSheet(
            "QLabel { background: rgba(20,21,24,225); color: #e6d896;"
            " border: 1px solid #4a4b52; border-radius: 4px;"
            " padding: 2px 7px; font-family: monospace; }")
        self._draw_readout.setVisible(False)
        self._draw_readout.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._draw_span = None              # (from, to) of the open leg
        self._draw_frame = None             # (sides, corner) when it is a box
        from .viewport_hud import ViewportHud
        self._hud = ViewportHud(self)       # top-left view/display chips
        self.history = None                 # set by the main window
        from ..core.snaps import SnapIndex
        self.snaps = SnapIndex(scene, config)
        self._active_snap = None            # (point, kind) under cursor
        self.snap_base = None               # reference point for perp snap
        self.point_axis = None              # (base, axis) while axis-locked
        self.dir_lock = None                # (base, dir) frozen by Tab
        self.pending_points = []            # the run being drawn, if any
        self.picked_points = []             # every point picked this command
        # what the running command's points mean: "model" coordinates or
        # "paper" millimetres. Only a sheet can tell the two apart.
        self.point_space = "model"
        self.frame_aspect = None            # cinema frame guide (e.g. 2.39)
        self.grid_snap = bool(config.get("grid_snap")) if config else False
        self.grid_snap_step = (float(config.get("grid_snap_step",
                                                default=1.0))
                               if config else 1.0)
        self.ortho = bool(config.get("ortho")) if config else False
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
        self._grid_params = (
            int(config.get("display", "grid_extent", default=100))
            if config else 100,
            int(config.get("display", "grid_major", default=10))
            if config else 10)
        self._cam_bounds_key = None         # see _refresh_camera_bounds
        # heavy shapes tessellate off the UI thread; bbox shown meanwhile
        self._tess_pool = None                     # created on first use
        # id -> (the shape being meshed, its bbox segments)
        self._tess_pending: dict[str, tuple] = {}
        self._tessDone.connect(self._on_tess_done,
                               Qt.ConnectionType.QueuedConnection)
        self._preview: _LineBatch | None = None
        self._preview_data = np.zeros((0, 3), np.float32)
        self._ghost = None                     # DisplayMesh of pending result
        self._marker_points: list = []
        self._last_mouse = None
        self._mesh_prog = self._line_prog = self._bg_prog = 0
        self._thick_prog = 0
        self._max_line_width = 1.0          # real cap read back in initializeGL
        self._uloc_cache: dict = {}
        # what the GL context is already set to, so the draw loop can stop
        # re-sending it. _reset_gl_state() drops all of it.
        self._mvp_state: dict = {}
        self._bound_color: dict = {}
        self._bound_uniform: dict = {}
        self._bound_prog = -1
        self._bound_width = -1.0
        self._bg_vao = 0
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        scene.add_listener(self.update)
        selection.add_listener(self.update)

    # ---------------------------------------------------------------- GL setup

    def initializeGL(self):
        self._uloc_cache.clear()      # programs below are about to be relinked
        self._reset_gl_state()
        if not GL.glCreateProgram:
            # a legacy context (e.g. Windows GDI GL 1.1 in a VM or over
            # remote desktop) has no shader entry points. Raising here
            # poisons Qt's event delivery with an unrelated-looking
            # error, so report cleanly and exit instead.
            ver = None
            try:
                ver = GL.glGetString(GL.GL_VERSION)
            except Exception:
                pass
            got = (f"this system only provides OpenGL {ver.decode()}"
                   if ver else "no capable OpenGL driver was found")
            msg = (f"Serpentine3D needs OpenGL 3.3, but {got}.\n\n"
                   "Update your GPU drivers. In a virtual machine, enable "
                   "3D acceleration; over remote desktop, a software "
                   "renderer (Mesa llvmpipe) is required.")
            print(f"serp3d: {msg}", file=sys.stderr)
            QMessageBox.critical(None, "OpenGL not available", msg)
            # raising here would surface as an unrelated shiboken error
            # mid event delivery — exit hard instead, message delivered
            os._exit(1)
        # runs again after reparenting (dock/undock) destroys the context:
        # every GPU-side cache from the old context is stale, drop it all
        self._gpu = {}
        self._grid = None
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
        self._build_grid(extent=self._grid_params[0],
                         major=self._grid_params[1])
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
        # QPainter overlays (dots, layout text) reset GL state behind our
        # back — re-assert what every frame relies on.
        self._reset_gl_state()
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glClearColor(*theme.VIEWPORT_BG_BOTTOM, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)

        # gradient background
        GL.glDisable(GL.GL_DEPTH_TEST)
        self._use(self._bg_prog)
        GL.glUniform3f(self._uloc(self._bg_prog, "uTop"),
                       *theme.VIEWPORT_BG_TOP)
        GL.glUniform3f(self._uloc(self._bg_prog, "uBottom"),
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
            self._draw_pending(self.layout_view._paper_mvp())
            self._draw_gumball_in_detail()
            self._draw_selection_box(w, h)   # sweeping inside a detail
            self._update_gumball_readout()
            GL.glBindVertexArray(0)
            self._use(0)
            GL.glDisable(GL.GL_SCISSOR_TEST)
            GL.glDisable(GL.GL_DEPTH_TEST)
            painter.endNativePainting()
            self.layout_view.paint_overlay(painter)
            painter.end()
            self._reset_gl_state()      # QPainter bound its own program
            self._update_draw_readout()  # follow the paper when the view moves
            return

        self._refresh_camera_bounds()
        view = self.camera.view_matrix()
        mvp = (self.camera.proj_matrix(w, h) @ view).astype(np.float32)

        if self.display_mode == "technical":
            self._paint_technical(w, h)
            self._draw_pending(mvp)
            self._draw_selection_box(w, h)
            return

        if self.grid_visible:
            self._draw_grid(mvp)
        self._draw_image_planes(mvp)
        self._sync_gpu()
        self._draw_objects(mvp, view)
        self._draw_pending(mvp)
        self._draw_control_points(mvp)
        self._draw_combs(mvp)
        self.gumball.paint(mvp)
        self._draw_axis_triad(view, w, h)
        self._draw_frame_guides(w, h)
        self._draw_selection_box(w, h)
        self._update_gumball_readout()
        self._update_draw_readout()
        self._paint_dots(w, h)

    def _paint_dots(self, w, h):
        """Annotation dots: screen-space label bubbles over their anchors."""
        dots = [o for o in self.scene.visible_objects()
                if o.annotation and len(o.mesh.points)]
        if not dots:
            return
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QColor, QFont, QPainter, QPen
        GL.glBindVertexArray(0)
        self._use(0)
        GL.glDisable(GL.GL_DEPTH_TEST)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        font = QFont(self.font())
        font.setPointSizeF(9.0)
        painter.setFont(font)
        fm = painter.fontMetrics()
        for obj in dots:
            anchor = obj.mesh.points[0].astype(float)
            scr = self.camera.project(anchor.reshape(1, 3), w, h)[0]
            if scr[2] <= 0:
                continue
            text = str(obj.annotation.get("text", ""))
            tw = fm.horizontalAdvance(text)
            th = fm.height()
            pad = 5.0
            rect = QRectF(scr[0] - tw / 2 - pad, scr[1] - th / 2 - 3,
                          tw + 2 * pad, th + 6)
            selected = self.selection.is_selected(obj.id)
            if selected:
                border = QColor.fromRgbF(*theme.SELECTION_COLOR)
                fill = QColor(58, 48, 22, 235)
            else:
                col = self.scene.color_of(obj)
                border = QColor.fromRgbF(col[0] * 0.75, col[1] * 0.75,
                                         col[2] * 0.75)
                fill = QColor(38, 38, 42, 225)
            painter.setPen(QPen(border, 2.0 if selected else 1.2))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 4, 4)
            painter.setPen(QColor(235, 235, 235))
            painter.drawText(rect, 0x84, text)  # AlignHCenter | AlignVCenter
        painter.end()
        GL.glEnable(GL.GL_DEPTH_TEST)
        self._reset_gl_state()      # QPainter bound its own program

    def _draw_gumball_in_detail(self):
        """The gumball on a sheet: drawn on the paper, over everything, since
        it is a handle on the drawing rather than part of it."""
        if self.layout_view._entered() is None:
            return
        self.gumball.paint(self.layout_view._paper_mvp())

    def _update_gumball_readout(self):
        """Position the value-readout label by the gumball (a real child
        widget, so it always composites and is testable)."""
        info = self.gumball.readout() if self.gumball.drag is not None \
            else None
        if info is None:
            if not self._gumball_readout.isHidden():
                self._gumball_readout.setVisible(False)
            return
        text, (x, y) = info
        self._gumball_readout.setText(text)
        self._gumball_readout.adjustSize()
        h = self._gumball_readout.height()
        x = max(2, min(x, self.width() - self._gumball_readout.width() - 2))
        y = max(2, min(y - h, self.height() - h - 2))
        self._gumball_readout.move(x, y)
        self._gumball_readout.setVisible(True)
        self._gumball_readout.raise_()

    def _readout_anchor(self, pt):
        """Where on screen a number about `pt` belongs, or None when the point
        is not on screen to sit beside."""
        if self.space == "model":
            scr = self.camera.project(np.asarray([pt], float),
                                      self.width(), self.height())[0]
            if scr[2] <= 0:                     # the point is behind the camera
                return None
            return float(scr[0]), float(scr[1])
        # A sheet has no model camera on screen, so the label is placed on the
        # paper the point was drawn on.
        end = self._on_paper([pt])[0]
        return self.layout_view.paper_to_screen(float(end[0]), float(end[1]))

    def _readout_length(self, length: float) -> str:
        """In the units it was drawn in: the model's through a detail or in the
        model window, millimetres on the paper itself."""
        if self.space == "model" or self._drawing_through() is not None:
            return self.scene.format_length(length)
        return _units.format_length(length, "mm")

    def _update_draw_readout(self):
        """Show how long the leg under the cursor is while a command is
        picking points — the number you are actually aiming for, without
        looking away from what you are drawing."""
        span = self._draw_span
        ghost = (self.layout_view.ghost_detail if self.space != "model"
                 else None)
        frame = self._draw_frame
        length = float(np.linalg.norm(span[1] - span[0])) if span else 0.0
        if not length and ghost is None and frame is None:
            if not self._draw_readout.isHidden():
                self._draw_readout.setVisible(False)
            return
        if ghost is not None:
            # A detail is a frame, not a leg: its width and height are the
            # numbers being aimed for, the scale beside them is what says
            # whether the model will fit inside them, and the corner they meet
            # at is where they belong — there is no band to hang them off.
            cx, cy = self.layout_view.paper_to_screen(ghost.x + ghost.w,
                                                      ghost.y + ghost.h)
            text = (f"{ghost.w:.1f} × {ghost.h:.1f} mm"
                    f" · {ghost.scale_text()}")
        elif frame is not None:
            # Anything else dragged out as a frame, for the same reason: two
            # sides at the corner they meet at, rather than one number about a
            # diagonal nobody asked for.
            lengths, at = frame
            anchor = self._readout_anchor(at)
            if anchor is None:
                self._draw_readout.setVisible(False)
                return
            cx, cy = anchor
            text = " × ".join(self._readout_length(v) for v in lengths)
        else:
            anchor = self._readout_anchor(span[1])
            if anchor is None:              # cursor point behind the camera
                self._draw_readout.setVisible(False)
                return
            cx, cy = anchor
            text = self._readout_length(length)
        self._draw_readout.setText(text)
        self._draw_readout.adjustSize()
        w, h = self._draw_readout.width(), self._draw_readout.height()
        x = max(2, min(int(cx) + 18, self.width() - w - 2))
        y = max(2, min(int(cy) - 14 - h, self.height() - h - 2))
        self._draw_readout.move(x, y)
        self._draw_readout.setVisible(True)
        self._draw_readout.raise_()

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

    def _cull(self, mvp, objects: list) -> list:
        """`objects`, minus the ones wholly outside the view.

        Every object used to cost a draw call whether or not it was on screen,
        and a survey drawing is mostly off screen: the cave file spans 60000
        units and you work inside it a room at a time.

        The test is the standard one — read the six clip planes off the MVP,
        and for each plane check the box corner furthest along its normal. If
        even that corner is behind the plane the whole box is. It is done for
        every object in one array operation rather than per object, because
        per-object numpy would cost more than the draw calls it saves.

        Boxes are padded by a little of the camera distance: point markers and
        the like are drawn at a screen-relative size around a box that may be
        a single point, and clipping those at the frame edge is worse than
        drawing a few objects that turn out to contribute nothing.
        """
        if not objects:
            return objects
        bounds = [obj.mesh.bounds() if obj.mesh_ready else None
                  for obj in objects]
        boxes = [(i, b) for i, b in enumerate(bounds) if b is not None]
        if not boxes:
            return objects              # nothing to judge them on: draw them
        m = np.asarray(mvp, dtype=np.float64)
        planes = np.array([m[3] + m[0], m[3] - m[0],
                           m[3] + m[1], m[3] - m[1],
                           m[3] + m[2], m[3] - m[2]])
        pad = abs(getattr(self.camera, "distance", 0.0)) * 0.02 + 1e-6
        mins = np.array([b[0] for _, b in boxes], float) - pad
        maxs = np.array([b[1] for _, b in boxes], float) + pad
        normals, offsets = planes[:, :3], planes[:, 3]
        # the corner furthest along each plane normal, per object per plane
        corner = np.where(normals[None, :, :] > 0,
                          maxs[:, None, :], mins[:, None, :])
        inside = ((corner * normals[None, :, :]).sum(-1)
                  + offsets >= 0).all(axis=1)
        # keep the incoming order: it is the draw order, and coincident
        # surfaces and translucency both depend on it
        dropped = {i for (i, _), ok in zip(boxes, inside) if not ok}
        return [obj for i, obj in enumerate(objects) if i not in dropped]

    def _uloc(self, prog: int, name: str) -> int:
        """A uniform's location, looked up once per program.

        `glGetUniformLocation` is a string lookup inside the driver, and
        through PyOpenGL it costs a ctypes round trip on top. Called from the
        per-object draw loop it was the largest single line item in the
        profile: a 5900-object scene spent about a third of every frame asking
        the driver where `uColor` lives. Locations are fixed for the life of a
        linked program, so ask once. -1 (no such uniform, usually optimised
        out) caches like any other answer.
        """
        key = (prog, name)
        loc = self._uloc_cache.get(key)
        if loc is None:
            loc = GL.glGetUniformLocation(prog, name)
            self._uloc_cache[key] = loc
        return loc

    def _set_mvp(self, prog: int, mvp):
        """Upload uMVP, unless this very matrix is already the one in place.

        Every object's edges were re-sending the same camera matrix — 5900
        uploads of 16 identical floats per frame, each one a trip through
        PyOpenGL's array marshalling. Matrices are built fresh per frame and
        never written into afterwards, so object identity is enough to tell
        "the same matrix" from "a new one"; keeping a reference to the one we
        uploaded stops its id being recycled underneath us.
        """
        if self._mvp_state.get(prog) is mvp:
            return
        GL.glUniformMatrix4fv(self._uloc(prog, "uMVP"), 1, GL.GL_TRUE, mvp)
        self._mvp_state[prog] = mvp

    def _set_line_uniforms(self, mvp, color):
        self._use(self._line_prog)
        self._set_mvp(self._line_prog, mvp)
        self._set_color4(self._line_prog, color)

    def _reset_gl_state(self):
        """Forget what the context is believed to hold.

        The skips above are only sound while nothing else touches the state
        they shadow, and something else does: the QPainter overlays reset GL
        behind our back between frames. So the shadow lasts exactly one frame
        and every frame starts by assuming nothing. Uniform *locations* are
        not state and survive — those belong to the program.
        """
        self._mvp_state.clear()
        self._bound_color.clear()
        self._bound_uniform.clear()
        self._bound_prog = -1
        self._bound_width = -1.0

    def _use(self, prog: int):
        """Bind a shader program, unless it is already the bound one."""
        if self._bound_prog != prog:
            GL.glUseProgram(prog)
            self._bound_prog = prog

    def _line_width(self, width: float):
        w = min(width, self._max_line_width)
        if w != self._bound_width:
            GL.glLineWidth(w)
            self._bound_width = w

    def _set_uniform(self, prog: int, name: str, setter, *values):
        """Set a scalar uniform, unless it already holds those values."""
        key = (prog, name)
        if self._bound_uniform.get(key) == values:
            return
        setter(self._uloc(prog, name), *values)
        self._bound_uniform[key] = values

    def _set_color4(self, prog: int, color):
        """Set a program's uColor, unless it already holds that colour.

        Objects are drawn in scene order and a drawing is mostly runs of
        objects on the same layer, so consecutive objects usually share a
        colour — this skips most of the uploads for the cost of a tuple
        compare.
        """
        c = tuple(color)
        if self._bound_color.get(prog) == c:
            return
        GL.glUniform4f(self._uloc(prog, "uColor"), *c)
        self._bound_color[prog] = c

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
            self._use(self._tex_prog)
            GL.glUniformMatrix4fv(
                self._uloc(self._tex_prog, "uMVP"), 1,
                GL.GL_TRUE, mvp)
            GL.glUniform1f(
                self._uloc(self._tex_prog, "uAlpha"),
                float(plane.get("alpha", 1.0)))
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
            GL.glUniform1i(
                self._uloc(self._tex_prog, "uTex"), 0)
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

    # Vertices past which a mesh goes to the background too. Shading one
    # costs about 0.8us a vertex, so this is roughly a frame: below it the
    # round trip, and the box standing in meanwhile, cost more than just
    # building the thing. On the cave file it defers 48 of 182 meshes and
    # moves 24 of their 25 seconds off the thread that draws.
    ASYNC_MESH_VERTICES = 20_000

    def _layer_linetypes(self) -> dict:
        """Every layer's dash style, by id.

        A drawing is thousands of objects over a few dozen layers, so
        resolving "ByLayer" per object asked for the same handful of answers
        once per object per frame. Built fresh each pass rather than kept
        between them: there are two orders of magnitude fewer layers than
        objects, so rebuilding costs nothing, and a map that cannot go stale
        needs no invalidating. There is nothing to hang invalidation off in
        any case — `LayerManager.set_linetype` mutates the layer without
        notifying the scene, so `scene.revision` does not move.
        """
        return {lay.id: lay.linetype for lay in self.scene.layers.all()}

    def _effective_linetype(self, obj, layer_types: dict | None = None) -> str:
        """The object's dash style, resolving 'ByLayer' against its layer.

        `layer_types` is `_layer_linetypes()`, passed in by callers looping
        over the scene; without it the layer is fetched per call.
        """
        if layer_types is None:
            layer_types = self._layer_linetypes()
        return _lt.resolve(getattr(obj, "linetype", "ByLayer"),
                           layer_types.get(obj.layer_id) or "Continuous")

    def _sync_gpu(self):
        live = set()
        layer_types = self._layer_linetypes()
        for obj in self.scene.all():
            live.add(obj.id)
            gpu = self._gpu.get(obj.id)
            if not obj.mesh_ready and self._schedule_tess(obj):
                if gpu is not None:
                    gpu.release()
                    del self._gpu[obj.id]
                continue
            self._tess_pending.pop(obj.id, None)
            lt_name = self._effective_linetype(obj, layer_types)
            if gpu is not None and (gpu.mesh_key != obj.mesh.uid
                                    or gpu.dash_key != lt_name):
                gpu.release()
                gpu = None
                del self._gpu[obj.id]
            if gpu is None:
                dash = ((_lt.pattern_for(lt_name), 1.0)
                        if lt_name != "Continuous" else None)
                self._gpu[obj.id] = _GpuObject(obj.mesh, dash=dash,
                                               dash_key=lt_name)
                self._warm_pick_index(obj.mesh)
        for dead in set(self._gpu) - live:
            self._gpu[dead].release()
            del self._gpu[dead]
        for dead in set(self._tess_pending) - live:
            del self._tess_pending[dead]

    def _worker_pool(self):
        if self._tess_pool is None:
            from concurrent.futures import ThreadPoolExecutor
            self._tess_pool = ThreadPoolExecutor(
                max_workers=3, thread_name_prefix="serp-tess")
        return self._tess_pool

    def _warm_pick_index(self, mesh):
        """Build a big mesh's pick indexes now, off the thread that clicks.

        Indexing costs about a second per million primitives. Spent on the
        click that needs it, that is exactly the freeze the index exists to
        remove — and the first thing anyone does with a model they have just
        opened is click on it. So it happens when the mesh first reaches the
        screen, while they are still looking at it.

        Racing the click is harmless: both sides would build the same index
        and one would simply be discarded.
        """
        if (len(mesh.triangles) < spatial.MIN_PRIMITIVES
                and len(mesh.edge_segments) < spatial.MIN_PRIMITIVES):
            return                         # most of a drawing, and never worth

        def work():
            try:
                mesh.triangle_index()
                mesh.segment_index()
            except Exception:              # noqa: BLE001
                pass                       # picking still works, just slower
        self._worker_pool().submit(work)

    def _schedule_tess(self, obj) -> bool:
        """Queue heavy tessellation on a worker; True while pending.

        Pending is per shape, not per object: edit something while its mesh
        is still being built and the work in flight is for geometry that no
        longer exists. Taken as "already in hand" it would strand the object
        — nobody meshes what replaced it, and the box drawn in the meantime
        stays where the old shape was. Holding the shape itself keeps the
        `is` honest; an address on its own would get recycled.
        """
        pending = self._tess_pending.get(obj.id)
        if pending is not None and pending[0] is obj.shape:
            return True
        from ..core.mesh import MeshShape
        try:
            from ..core import geometry as g
            if isinstance(obj.shape, MeshShape):
                # Arriving as a mesh is not the same as arriving ready to
                # draw. Rhino's own vertex normals are deliberately not read
                # — 36us each is 239 seconds for one survey scan — so the
                # shading is worked out from the geometry here instead, and
                # welding and shading 6.6 million vertices takes ten of them.
                # Small meshes really do convert instantly, which is why this
                # was skipped for all of them.
                if len(obj.shape.vertices) < self.ASYNC_MESH_VERTICES:
                    return False
            else:
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
        self._tess_pending[obj.id] = (obj.shape, _bbox_segments(mn, mx))

        def work(target=obj):
            try:
                target.mesh                # locks per shape, sets _mesh
            except Exception:              # noqa: BLE001
                pass
            self._tessDone.emit()

        self._worker_pool().submit(work)
        return True

    def _on_tess_done(self):
        self.update()

    def _refresh_camera_bounds(self):
        """Tell the camera what the drawing spans, so the clip planes wrap
        the model instead of the zoom (GitHub #5).

        Recomputed only when something changed: the bbox sweep is a Python
        loop over every visible object, which at cave-file scale is too dear
        to pay per frame. The grid rides along because it is drawn with the
        same projection — a far plane snug around a small model would
        otherwise crop the grid it sits on.
        """
        key = (self.scene.revision, self._grid_params, self.grid_visible)
        if self._cam_bounds_key == key:
            return
        self._cam_bounds_key = key
        box = self.scene.bbox()
        if self.grid_visible:
            extent = float(self._grid_params[0])
            grid = ((-extent, -extent, 0.0), (extent, extent, 0.0))
            if box is None:
                box = grid
            else:
                box = (tuple(min(a, b) for a, b in zip(box[0], grid[0])),
                       tuple(max(a, b) for a, b in zip(box[1], grid[1])))
        self.camera.scene_bounds = box

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
        # Higher draw_order on top: with GL_LESS the first-drawn wins coincident
        # depth ties, so draw front-most first. Stable, so equal-order objects
        # keep insertion order (unchanged default behaviour).
        objects = sorted(self.scene.visible_objects(),
                         key=lambda o: -getattr(o, "draw_order", 0))
        clips = self._clip_vectors() if self.space == "model" else []
        for i in range(len(clips)):
            GL.glEnable(GL.GL_CLIP_DISTANCE0 + i)
        for prog in (self._mesh_prog, self._line_prog, self._thick_prog):
            self._set_clip_uniforms(prog, clips)
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
            # before culling: an object above the frustum can still stamp a
            # shadow that is inside it
            self._draw_ground_shadow(mvp, objects)
        objects = self._cull(mvp, objects)
        # Uniform state belongs to the program, not the draw call, and these
        # are the same for every object in the frame — the camera and the
        # display mode. Only the colour and the material change per object.
        self._use(self._mesh_prog)
        GL.glUniformMatrix4fv(self._uloc(self._mesh_prog, "uMVP"), 1,
                              GL.GL_TRUE, mvp)
        GL.glUniformMatrix4fv(self._uloc(self._mesh_prog, "uView"), 1,
                              GL.GL_TRUE, view.astype(np.float32))
        GL.glUniform1i(self._uloc(self._mesh_prog, "uZebra"),
                       1 if mode == "zebra" else 0)
        GL.glUniform1i(self._uloc(self._mesh_prog, "uDraft"),
                       1 if mode == "draft" else 0)
        GL.glUniform1f(self._uloc(self._mesh_prog, "uDraftCos"),
                       math.sin(math.radians(self.draft_angle)))
        GL.glUniform1f(self._uloc(self._mesh_prog, "uCurvRange"), curv_range)
        GL.glUniform1i(self._uloc(self._mesh_prog, "uRendered"),
                       1 if mode == "rendered" else 0)
        for obj in objects:
            gpu = self._gpu.get(obj.id)
            if gpu is None:
                entry = self._tess_pending.get(obj.id)
                pend = entry[1] if entry is not None else None
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
            surface = color
            if mode == "rendered" and not selected and not obj.locked:
                # An imported object can display one colour and render
                # another; edges stay on the one it displays, the way Rhino
                # draws them.
                surface = self.scene.render_color_of(obj)
            # Surfaces are shaded by multiplying this colour, so a near-black
            # one leaves nothing to shade. Lift the fill only — edges keep the
            # object's real colour, so black stays black in wireframe.
            fill_color = theme.shaded_fill(surface)
            if light_background and not selected:
                # dark linework on paper-white detail backgrounds
                line_color = (min(color[0], 0.3), min(color[1], 0.3),
                              min(color[2], 0.33))

            if obj.clip_plane is not None:
                fill_alpha_obj = 0.18
            else:
                fill_alpha_obj = fill_alpha
            if fill_alpha_obj > 0 and gpu.tri_count:
                self._use(self._mesh_prog)
                GL.glUniform3f(
                    self._uloc(self._mesh_prog, "uColor"),
                    *fill_color)
                GL.glUniform1f(
                    self._uloc(self._mesh_prog, "uAlpha"),
                    fill_alpha_obj)
                m = obj.material or {}
                opacity = float(m.get("opacity", 1.0))
                GL.glUniform1f(
                    self._uloc(self._mesh_prog, "uMetallic"),
                    float(m.get("metallic", 0.0)))
                GL.glUniform1f(
                    self._uloc(self._mesh_prog, "uRoughness"),
                    float(m.get("roughness", 0.55)))
                if opacity < 1.0:
                    GL.glUniform1f(
                        self._uloc(self._mesh_prog, "uAlpha"),
                        fill_alpha * opacity)
                if mode == "ghosted" or opacity < 1.0 \
                        or obj.clip_plane is not None:
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
            if obj.clip_plane is not None and clips:
                for prog in (self._mesh_prog, self._line_prog,
                             self._thick_prog):
                    self._set_clip_uniforms(prog, clips)
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
            if len(obj.mesh.points) and not obj.annotation:
                self._draw_point_markers(mvp, obj.mesh.points,
                                         (*line_color, 1.0), selected)
        self._line_width(1.0)
        self._end_clips(clips)

    def _draw_point_markers(self, mvp, points, color, selected: bool):
        """Point objects as fixed-ish size crosses (always visible)."""
        size = self.camera.distance * (0.009 if selected else 0.007)
        segs = []
        axes = np.eye(3, dtype=np.float32) * size
        for p in np.asarray(points, np.float32):
            for axis in axes:
                segs.append(np.stack([p - axis, p + axis]))
        self._preview.update(np.concatenate(segs).astype(np.float32))
        self._set_line_uniforms(mvp, color)
        self._line_width(2.6 if selected else 1.8)
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glBindVertexArray(self._preview.vao)
        GL.glDrawArrays(GL.GL_LINES, 0, len(segs) * 2)
        GL.glEnable(GL.GL_DEPTH_TEST)

    def _end_clips(self, clips):
        for i in range(len(clips)):
            GL.glDisable(GL.GL_CLIP_DISTANCE0 + i)
        for prog in (self._mesh_prog, self._line_prog, self._thick_prog):
            self._set_clip_uniforms(prog, [])

    def _draw_ground_shadow(self, mvp, objects):
        """Flatten object triangles onto z=0 as a soft dark stamp."""
        squash = np.eye(4, dtype=np.float32)
        squash[2, 2] = 0.0
        squash[2, 3] = 0.01                 # hair above the plane
        smvp = (mvp @ squash).astype(np.float32)
        self._use(self._line_prog)
        # through _set_mvp, so the squashed matrix is recorded as what the
        # program holds — the edge pass after this one has to know to put the
        # real one back
        self._set_mvp(self._line_prog, smvp)
        self._set_color4(self._line_prog, (0.02, 0.02, 0.03, 0.30))
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
        self._use(prog)
        # asarray, not astype: astype copies even when the dtype already
        # matches, and a fresh array every object defeated _set_mvp entirely —
        # this is the path llvmpipe takes for every wide line it draws.
        self._set_mvp(prog, np.asarray(mvp, np.float32))
        self._set_uniform(prog, "uViewport", GL.glUniform2f,
                          float(self.width()), float(self.height()))
        self._set_uniform(prog, "uWidthPx", GL.glUniform1f, float(width))
        self._set_color4(prog, color)
        GL.glBindVertexArray(gpu.thick_vao)
        GL.glDrawElements(GL.GL_TRIANGLES, gpu.thick_count,
                          GL.GL_UNSIGNED_INT, ctypes.c_void_p(0))

    def _drawing_through(self):
        """The detail the running command is drawing through, or None.

        Never for a paper command: one of those inside a detail is still
        writing on the paper. A curve command says "any" and means it — in a
        detail it draws in the model, on bare paper it draws on the sheet — so
        the entered detail is what decides for it. Everything that has to turn
        one space into the other asks this, so there is one answer.
        """
        if self.space == "model" or self.point_space == "paper":
            return None
        return self.layout_view._entered()

    def active_cplane(self):
        """The plane being drawn on right now.

        Inside a detail that is the plane the detail looks at, because that is
        where its picks land: on the world plane instead, a rectangle drawn in
        a front view has both corners on one line of it and comes out
        degenerate, and a circle comes out lying flat, edge-on to the view it
        was drawn in.
        """
        detail = self._drawing_through()
        if detail is None:
            return self.cplane
        from .layout_view import detail_plane
        return detail_plane(detail)

    def _detail_eye(self):
        """The detail everything is being seen through, as a camera, or None.

        Unlike `_drawing_through` this does not care what a running command
        wants: picking an object inside a detail is looking at the model
        whether anything is running or not.
        """
        if self.space == "model":
            return None
        detail = self.layout_view._entered()
        if detail is None:
            return None
        from .layout_view import DetailEye
        return DetailEye(self.layout_view, detail)

    def _eye(self):
        """What screen positions are measured through: a detail, or the
        camera. Everything that projects to pick or to snap asks this."""
        return self._detail_eye() or self.camera

    def _pick_mode(self) -> str:
        """The display mode picking should believe.

        Inside a detail that is the detail's own: a wireframe view has no
        faces to hit, whatever the model window behind it is set to.
        """
        if self.space != "model":
            detail = self.layout_view._entered()
            if detail is not None:
                return detail.display_mode
        return self.display_mode

    def _on_paper(self, pts) -> np.ndarray:
        """Points as paper millimetres, wherever they came from.

        A model point picked through a detail has to come back out through
        the same window it went in, or it lands on the sheet at the model's
        own numbers.
        """
        arr = np.asarray(pts, np.float32).reshape(-1, 3)
        entered = self._drawing_through()
        if entered is None:
            return arr
        from ..core.layout import detail_project
        out = np.zeros_like(arr)
        for i, p in enumerate(arr):
            out[i, :2] = detail_project(entered, p)
        return out

    def _draw_preview(self, mvp):
        pts = self._preview_data
        markers = self._marker_points
        if self.space != "model" and self._drawing_through() is not None:
            pts = self._on_paper(pts) if len(pts) else pts
            markers = [self._on_paper([m])[0] for m in markers]
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
            # A snap inside a detail is a model point drawn on the paper, so
            # the marker comes back out through the window like the rest of
            # the preview and is squared to the paper, not to the model.
            if self.space != "model" and self._drawing_through() is not None:
                at = self._on_paper([snap[0]])[0]
                axes = (np.array([1.0, 0.0, 0.0], np.float32),
                        np.array([0.0, 1.0, 0.0], np.float32))
            else:
                at = np.asarray(snap[0], np.float32)
                axes = self.camera.right_up()
            segs = _snap_marker(snap[1], at, *axes, size * 0.95)
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
        """Translucent preview of a pending command result (or None).

        A pending detail view is a window onto the model rather than a shape,
        so there is nothing to tessellate: the sheet draws it the way it draws
        the details already on it.
        """
        from ..core.layout import DetailView
        if isinstance(shape, DetailView):
            self.layout_view.set_ghost_detail(shape)
            self._update_draw_readout()   # the frame's size is the readout
            self.update()
            return
        self.layout_view.set_ghost_detail(None)
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

    def _clip_vectors(self) -> list:
        """vec4 clip equations from enabled clipping-plane objects.
        Keeps the half-space behind each plane's normal."""
        cache = getattr(self, "_clip_cache", None)
        if cache is not None and cache[0] == self.scene.revision:
            return cache[1]
        from ..core import geometry as g
        vecs = []
        for obj in self.scene.visible_objects():
            if not (obj.clip_plane and obj.clip_plane.get("enabled")):
                continue
            try:
                face = next(iter(g.faces_of(obj.shape)))
                n = np.asarray(g.face_normal(face), float)
                o = np.asarray(g.centroid(obj.shape), float)
                vecs.append(np.array([-n[0], -n[1], -n[2],
                                      float(np.dot(n, o))], np.float32))
            except Exception:                              # noqa: BLE001
                continue
            if len(vecs) == 4:
                break
        self._clip_cache = (self.scene.revision, vecs)
        return vecs

    def _set_clip_uniforms(self, prog, clips):
        self._use(prog)
        GL.glUniform1i(self._uloc(prog, "uClipCount"),
                       len(clips))
        if clips:
            GL.glUniform4fv(self._uloc(prog, "uClips"),
                            len(clips), np.asarray(clips, np.float32))

    def _ghost_geometry(self):
        """The pending result's triangles and lines, where they are drawn.

        The same journey the rubber band makes: a ghost of model geometry
        drawn through a detail has to come back out through that detail, or
        it lands on the sheet at the model's own numbers.
        """
        dm = self._ghost
        if dm is None:
            return None, None
        tris = (dm.vertices[dm.triangles.ravel()]
                if dm.has_faces and len(dm.triangles) else None)
        segs = (dm.edge_segments.reshape(-1, 3)
                if len(dm.edge_segments) else None)
        if self.space != "model" and self._drawing_through() is not None:
            tris = None if tris is None else self._on_paper(tris)
            segs = None if segs is None else self._on_paper(segs)
        return tris, segs

    def _draw_ghost(self, mvp):
        if self._preview is None:
            return
        tris, segs = self._ghost_geometry()
        if tris is None and segs is None:
            return
        gold = theme.SELECTION_COLOR
        # on a sheet everything is flat at z=0, so the order it is drawn in is
        # the only thing that says what is on top — same reason the rubber
        # band stops testing depth
        flat = self.space != "model"
        if flat:
            GL.glDisable(GL.GL_DEPTH_TEST)
        if tris is not None:
            pts = tris.astype(np.float32)
            self._preview.update(pts)
            self._set_line_uniforms(mvp, (*gold, 0.22))
            GL.glDepthMask(False)
            GL.glBindVertexArray(self._preview.vao)
            GL.glDrawArrays(GL.GL_TRIANGLES, 0, len(pts))
            GL.glDepthMask(True)
        if segs is not None:
            segs = segs.astype(np.float32)
            self._preview.update(segs)
            self._set_line_uniforms(mvp, (*gold, 0.85))
            self._line_width(1.6)
            GL.glBindVertexArray(self._preview.vao)
            GL.glDrawArrays(GL.GL_LINES, 0, len(segs))
            self._line_width(1.0)
        if flat:
            GL.glEnable(GL.GL_DEPTH_TEST)

    def _draw_pending(self, mvp):
        """What the running command would make, and where you are drawing it.

        One call, because a paint path that draws the rubber band and forgets
        the ghost turns a rectangle into a line from corner to corner.
        """
        self._draw_ghost(mvp)
        self._draw_preview(mvp)

    def set_preview(self, segments: np.ndarray | None,
                    markers: list | None = None):
        """Segments: (K,2,3) rubber-band lines; markers: picked points."""
        if segments is None or len(segments) == 0:
            self._preview_data = np.zeros((0, 3), np.float32)
            self._draw_span = None
        else:
            arr = np.asarray(segments, np.float32)
            # the last leg runs from the newest picked point to the cursor:
            # that is the length worth showing while you draw
            self._draw_span = (arr[-1][0].astype(float),
                               arr[-1][1].astype(float))
            self._preview_data = arr.reshape(-1, 3)
        self._marker_points = list(markers or [])
        # A leg and a frame are two answers to the same question, so setting
        # either one puts the other away. This is the one every command comes
        # through, and it runs first.
        self._draw_frame = None
        # move the label with the preview that owns it, so it is already in
        # the right place when the frame goes out; paintGL repeats this only
        # to follow the camera when the view moves mid-pick
        self._update_draw_readout()
        self.update()

    def set_frame_readout(self, sides, at):
        """The sides of a box being dragged out, to read at the corner `at`.

        What a rubber band would have said, for the commands that cannot have
        one: their ghost is already under the cursor, so a band could only cut
        across it, and its length would measure a diagonal rather than the
        thing being drawn.
        """
        self._draw_frame = ((tuple(sides), at)
                            if sides and at is not None
                            and all(s > 1e-9 for s in sides) else None)
        self._update_draw_readout()

    def set_point_mode(self, on: bool):
        self.point_mode = on
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor if on
                               else Qt.CursorShape.ArrowCursor))
        if not on:
            self.set_preview(None)
            self.dir_lock = None

    def _locked_axis(self):
        """The Tab lock, if it still belongs to the point being picked.

        The lock is stored with the base it was taken from rather than
        being cleared by whoever moves on, so a command that picks a run of
        points does not have to know the lock exists: the moment it sets a
        new base the old direction stops applying.
        """
        if self.dir_lock is None:
            return None
        if self.snap_base is None or not np.allclose(
                np.asarray(self.dir_lock[0], float),
                np.asarray(self.snap_base, float), atol=1e-9):
            self.dir_lock = None
            return None
        return self.dir_lock

    def toggle_direction_lock(self, px: float | None = None,
                              py: float | None = None) -> bool:
        """Freeze (or release) the direction from the base to the cursor.

        Ortho covers the four CPlane directions; this covers the one the
        cursor is actually in, which is what drawing off an existing wall
        needs. Returns True if a direction is now locked.
        """
        if self._locked_axis() is not None:
            self.dir_lock = None
            self.update()
            return False
        # a command that picks along its own axis already owns the
        # direction — there is nothing left for Tab to decide
        if self.snap_base is None or self.point_axis is not None:
            return False
        if px is None:
            if self._last_mouse is None:
                return False
            px, py = self._last_mouse.x(), self._last_mouse.y()
        aim = self.world_point_at(px, py)
        if aim is None:
            return False
        base = np.asarray(self.snap_base, float)
        d = np.asarray(aim, float) - base
        if np.linalg.norm(d) < 1e-9:
            return False                    # cursor is on the base point
        self.dir_lock = (tuple(base), tuple(normalize(d)))
        self.update()
        return True

    def set_display_mode(self, mode: str):
        if mode not in ("shaded", "wireframe", "ghosted", "zebra",
                        "curvature", "technical", "draft", "rendered"):
            raise ValueError(f"Unknown display mode '{mode}'")
        if mode == "curvature":
            from ..core import tessellate as _tess
            if not _tess.curvature_enabled():
                _tess.set_curvature_enabled(True)
            # cached meshes without curvature data must regenerate
            for obj in self.scene.all():
                m = obj._mesh
                if m is not None and m.has_faces and not m.has_curvature:
                    obj._mesh = None
        self.display_mode = mode
        self.displayModeChanged.emit()
        self.update()

    def _aspect(self) -> float:
        """The window's width over its height, which the fit needs: a wide
        window has room at the sides that a square one does not."""
        return self.width() / max(self.height(), 1)

    def _zooms_the_sheet(self):
        """The layout view, when a zoom means what is on screen and not the
        camera.

        On a sheet the camera is the one thing you cannot see, so a zoom that
        drove it moved nothing and looked broken. Answered here rather than in
        each command, because everything that zooms — the commands, the RPC,
        opening a file — comes through these three methods.
        """
        return None if self.space == "model" else self.layout_view

    def zoom_extents(self):
        lv = self._zooms_the_sheet()
        if lv is not None and lv.zoom_extents():
            return
        self.camera.zoom_extents(self.scene.bbox(), self._aspect())
        self.update()

    def selected_bbox(self):
        """The selection's model-space bounds, None when nothing is picked."""
        objs = [o for i in self.selection.ids
                if (o := self.scene.get(i)) is not None]
        if not objs:
            return None
        # o.bbox(), not geometry.bbox(o.shape): objects remember their own
        # bounds, and zooming to a whole drawing would otherwise measure
        # every one of them again.
        boxes = np.array([o.bbox() for o in objs], float)
        return (tuple(boxes[:, 0].min(axis=0)),
                tuple(boxes[:, 1].max(axis=0)))

    def zoom_selected(self) -> bool:
        """Frame the selection. False when nothing is selected."""
        lv = self._zooms_the_sheet()
        if lv is not None:
            return lv.zoom_selected()
        box = self.selected_bbox()
        if box is None:
            return False
        self.camera.zoom_extents(box, self._aspect())
        self.update()
        return True

    def zoom_to_points(self, p1, p2):
        """Frame the axis-aligned window spanned by two picked points."""
        lv = self._zooms_the_sheet()
        if lv is not None and lv.zoom_window(p1, p2):
            return
        mn = np.minimum(np.asarray(p1, float), np.asarray(p2, float))
        mx = np.maximum(np.asarray(p1, float), np.asarray(p2, float))
        pad = max(float(np.linalg.norm(mx - mn)) * 0.05, 0.5)
        self.camera.zoom_extents((tuple(mn - pad), tuple(mx + pad)),
                                 self._aspect())
        self.update()

    def zoom_steps(self, steps: float):
        """Zoom in or out about the middle of the view, as the wheel does."""
        lv = self._zooms_the_sheet()
        if lv is not None and lv.zoom_steps(steps):
            return
        self.camera.zoom(steps)
        self.update()

    def set_view(self, name: str):
        self.camera.set_standard_view(name)
        self._view_name = name
        self.viewChanged.emit(name)
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
            self._reset_gl_state()        # a different target, a fresh start
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

        On a sheet this is paper millimetres (x, y, 0) — except inside an
        entered detail, where a command asking for a model point gets the
        model point that detail is showing. `point_space` is what says which
        of the two the caller means."""
        if self.space != "model":
            self._active_snap = None
            x, y = self.layout_view.screen_to_paper(px, py)
            entered = self._drawing_through()
            if entered is not None:
                # Inside a detail you are picking in the model, so the model's
                # own features are what to land on — through the detail,
                # because that is where they appear on screen. Before the grid,
                # for the reason it is before it in the model: the grid is
                # where a point goes when nothing better is near it.
                snap = self.snaps.find(
                    self._eye(), px, py, self.width(), self.height(),
                    base_point=self.snap_base,
                    pending_points=self.pending_points,
                    picked_points=self.picked_points)
                if snap is not None:
                    self._active_snap = snap
                    return snap[0]
                from ..core.layout import detail_model_point
                return detail_model_point(
                    entered, x, y,
                    self.grid_snap_step if self.grid_snap else 0.0)
            if self.grid_snap:
                x, y = round(x), round(y)
            return (float(x), float(y), 0.0)
        locked = self._locked_axis() or self.point_axis
        if locked is not None:
            base, axis = (np.asarray(v, float) for v in locked)
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
                               self.height(), base_point=self.snap_base,
                               pending_points=self.pending_points,
                               picked_points=self.picked_points)
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
        # ortho constrains to the dominant CPlane axis from the base point;
        # Shift is the momentary override (toggles the persistent setting)
        shift = bool(QApplication.queryKeyboardModifiers()
                     & Qt.KeyboardModifier.ShiftModifier)
        if self.snap_base is not None and (self.ortho != shift):
            bu, bv, bw = self.cplane.from_world(self.snap_base)
            u, v, w = self.cplane.from_world(hit)
            if abs(u - bu) >= abs(v - bv):
                hit = np.asarray(self.cplane.to_world(u, bv, w))
            else:
                hit = np.asarray(self.cplane.to_world(bu, v, w))
        return tuple(round(float(c), 9) for c in hit)

    def _reject_boxes(self, boxes: list, x0, y0, x1, y1, w, h) -> np.ndarray:
        """Mask over `boxes`: True where one projects clear of the rect.

        Every box at once, in one projection, because clicking asks this of
        every object in the scene. Projecting eight corners is a few dozen
        flops wrapped in enough numpy call overhead to dwarf them, so done
        per object the overhead *is* the cost of the click — the same reason
        `_cull` tests the whole draw list in a single array operation.
        """
        if not len(boxes):
            return np.zeros(0, bool)
        return self._reject_extents(np.array([b[0] for b in boxes], float),
                                    np.array([b[1] for b in boxes], float),
                                    x0, y0, x1, y1, w, h)

    def _reject_extents(self, mins, maxs, x0, y0, x1, y1, w, h) -> np.ndarray:
        """The same test over boxes already in (N, 3) min/max arrays."""
        n = len(mins)
        if not n:
            return np.zeros(0, bool)
        corners = np.where(_BOX_CORNERS[None, :, :],
                           maxs[:, None, :], mins[:, None, :])
        scr = self._eye().project(corners.reshape(-1, 3),
                                  w, h).reshape(n, 8, 3)
        xs, ys = scr[:, :, 0], scr[:, :, 1]
        outside = ((xs.max(axis=1) < x0) | (xs.min(axis=1) > x1)
                   | (ys.max(axis=1) < y0) | (ys.min(axis=1) > y1))
        behind = scr[:, :, 2] <= 0
        # A box crossing the camera plane projects nonsense, so the screen
        # test above cannot be trusted for it and it has to be kept. One
        # wholly behind the camera is not that case: it cannot be under the
        # cursor at all. Working inside a model, that is most of the model.
        return (outside & ~behind.any(axis=1)) | behind.all(axis=1)

    def _pick_reject(self, mesh, x0, y0, x1, y1, w, h) -> bool:
        """True if the mesh's bbox projects fully outside a screen rect."""
        b = mesh.bounds()
        if b is None:
            return True
        return bool(self._reject_boxes([b], x0, y0, x1, y1, w, h)[0])

    def _pick_candidates(self, objects: list, x0, y0, x1, y1, w, h) -> list:
        """`objects`, minus the ones whose bounds project clear of the rect.

        Callers filter for selectability first: asking an object for its mesh
        tessellates it, and one that can never be picked should not be made
        to pay for that.
        """
        boxed = [(obj, obj.mesh.bounds()) for obj in objects]
        boxed = [(obj, b) for obj, b in boxed if b is not None]
        if not boxed:
            return []
        drop = self._reject_boxes([b for _, b in boxed], x0, y0, x1, y1, w, h)
        return [obj for (obj, _), d in zip(boxed, drop) if not d]

    def _near_primitives(self, index, x0, y0, x1, y1, w, h):
        """Which of an indexed mesh's primitives can reach a screen rect.

        Narrowing the drawing to the objects near the cursor does nothing
        when one object *is* the drawing — a scanned mesh of millions of
        triangles. Its chunks are rejected by exactly the test that rejects
        whole objects, so a chunk straddling the camera plane is kept for
        the same reason an object is.

        None means "all of them": either the mesh is small enough to have no
        index, or nothing was rejected and subsetting would be pure cost.
        """
        if index is None:
            return None
        drop = self._reject_extents(index.mins, index.maxs,
                                    x0, y0, x1, y1, w, h)
        if not drop.any():
            return None
        return index.gather(~drop)

    def _near_triangles(self, mesh, x0, y0, x1, y1, w, h) -> tuple:
        """(triangles worth testing, where each sits in the mesh or None).

        The second half matters wherever the answer is an index — a winner
        found at position 3 of a narrowed set is not triangle 3 of the mesh.
        """
        sub = self._near_primitives(mesh.triangle_index(),
                                    x0, y0, x1, y1, w, h)
        return (mesh.triangles if sub is None else mesh.triangles[sub]), sub

    def _near_segments(self, mesh, x0, y0, x1, y1, w, h) -> tuple:
        """(edge segments worth testing, where each sits in the mesh)."""
        sub = self._near_primitives(mesh.segment_index(),
                                    x0, y0, x1, y1, w, h)
        return ((mesh.edge_segments if sub is None
                 else mesh.edge_segments[sub]), sub)

    def pick_object(self, px: float, py: float) -> str | None:
        w, h = self.width(), self.height()
        eye = self._eye()
        origin, direction = eye.ray_through(px, py, w, h)
        best_id, best_depth = None, np.inf

        r = PICK_RADIUS_PX
        selectable = [obj for obj in self.scene.visible_objects()
                      if self.scene.is_selectable(obj.id)
                      and self.selection.filter_allows(obj.kind)]
        for obj in self._pick_candidates(selectable, px - r, py - r,
                                         px + r, py + r, w, h):
            mesh = obj.mesh
            depth = np.inf
            hit = False
            if mesh.has_faces and self._pick_mode() != "wireframe":
                tris, _ = self._near_triangles(mesh, px - r, py - r,
                                               px + r, py + r, w, h)
                t = ray_triangle_hits(origin, direction,
                                      mesh.vertices[tris[:, 0]].astype(float),
                                      mesh.vertices[tris[:, 1]].astype(float),
                                      mesh.vertices[tris[:, 2]].astype(float))
                tmin = t.min() if len(t) else np.inf
                if np.isfinite(tmin):
                    depth = tmin
                    hit = True
            if len(mesh.edge_segments):
                segs, _ = self._near_segments(mesh, px - r, py - r,
                                              px + r, py + r, w, h)
                pts = segs.reshape(-1, 3)
                scr = eye.project(pts, w, h)
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
            if len(mesh.points):
                scr = eye.project(mesh.points.astype(float), w, h)
                d2 = ((scr[:, 0] - px) ** 2 + (scr[:, 1] - py) ** 2)
                near = d2 < PICK_RADIUS_PX ** 2
                if near.any():
                    pt_depth = scr[near, 2].min()
                    if pt_depth > 0:
                        # points win ties: they're drawn on top
                        pt_depth *= 0.998
                        if pt_depth < depth:
                            depth = pt_depth
                        hit = True
            if hit and depth < best_depth:
                best_depth = depth
                best_id = obj.id
        return best_id

    def pick_subobject(self, px: float, py: float):
        """(obj_id, "edge"|"face", index) under the pixel, or None."""
        w, h = self.width(), self.height()
        eye = self._eye()
        origin, direction = eye.ray_through(px, py, w, h)
        # edges first (they are the smaller target)
        r = PICK_RADIUS_PX
        selectable = [obj for obj in self.scene.visible_objects()
                      if self.scene.is_selectable(obj.id)]
        near_cursor = self._pick_candidates(selectable, px - r, py - r,
                                            px + r, py + r, w, h)
        # Every segment under the cursor, gathered before anything is chosen:
        # which edge wins depends on how close the closest one came, and that
        # is not known until all the objects have been looked at.
        found = []
        for obj in near_cursor:
            mesh = obj.mesh
            if not len(mesh.edge_segments):
                continue
            segs, sub = self._near_segments(mesh, px - r, py - r,
                                            px + r, py + r, w, h)
            if not len(segs):
                continue
            scr = eye.project(segs.reshape(-1, 3), w, h)
            a, b = scr[0::2], scr[1::2]
            d2 = _point_segment_dist2(np.array([px, py]), a[:, :2],
                                      b[:, :2])
            near = (a[:, 2] > 0) & (b[:, 2] > 0) & (d2 <= PICK_RADIUS_PX ** 2)
            if not near.any():
                continue
            # Sorted by how close to the cursor, so the band below is a slice.
            order = np.flatnonzero(near)
            order = order[np.argsort(d2[order], kind="stable")]
            found.append((obj, mesh, sub, order, d2[order],
                          np.minimum(a[:, 2], b[:, 2])))

        if found:
            closest = math.sqrt(min(float(f[4][0]) for f in found))
            band = (closest + PICK_DEPTH_BAND_PX) ** 2
            best_edge, best_depth = None, np.inf
            for obj, mesh, sub, order, sorted_d2, depth in found:
                k = int(np.searchsorted(sorted_d2, band, side="right"))
                if not k:
                    continue
                within = order[:k]
                seg = int(within[np.argmin(depth[within])])
                if float(depth[seg]) >= best_depth:
                    continue
                i = int(sub[seg]) if sub is not None else seg
                if len(mesh.edge_of_segment) > i:
                    best_depth = float(depth[seg])
                    best_edge = (obj.id, "edge",
                                 int(mesh.edge_of_segment[i]))
            if best_edge is not None:
                return best_edge
        # faces by nearest ray-triangle hit
        best_face = None
        best_t = np.inf
        for obj in near_cursor:             # same rect, already narrowed
            mesh = obj.mesh
            if not mesh.has_faces or not len(mesh.face_of_triangle):
                continue
            tris, sub = self._near_triangles(mesh, px - r, py - r,
                                             px + r, py + r, w, h)
            if not len(tris):
                continue
            t = ray_triangle_hits(origin, direction,
                                  mesh.vertices[tris[:, 0]].astype(float),
                                  mesh.vertices[tris[:, 1]].astype(float),
                                  mesh.vertices[tris[:, 2]].astype(float))
            i = int(np.argmin(t))
            if np.isfinite(t[i]) and t[i] < best_t:
                best_t = t[i]
                if sub is not None:
                    i = int(sub[i])          # back to the mesh's own numbering
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
        if ev.button() == Qt.MouseButton.RightButton:
            self._rmb_press = ev.position()
        if ev.button() == Qt.MouseButton.MiddleButton:
            self._mmb_press = ev.position()
        if ev.button() == Qt.MouseButton.LeftButton:
            pos = ev.position()
            # resolve a gumball armed for numeric entry before anything else
            if self.gumball.drag is not None and \
                    self.gumball.drag.get("armed"):
                if not self.gumball.commit_typed():
                    self.gumball.cancel_drag()
                self.update()
            if self.point_mode:
                # On a sheet, a command that can draw in the model needs a way
                # into a detail while it is running: without one its clicks
                # land on the paper, which is how a rectangle meant for the
                # model ends up drawn on the sheet.
                if self.space != "model" and self.point_space != "paper":
                    detail = self.layout_view.step_into_detail(pos.x(),
                                                               pos.y())
                    if detail is not None:
                        self.detailEntered.emit(detail)
                        self.update()
                        return
                pt = self.world_point_at(pos.x(), pos.y())
                if pt is not None:
                    self.pointPicked.emit(pt)
                return
            if self.space != "model":
                # Before anything the sheet does with a click: a handle
                # reaches past the frame it belongs to, and taking hold of one
                # there is not a click outside the detail.
                if self._take_gumball(pos, ev):
                    return
                if self.layout_view.click_outside_exits(pos.x(), pos.y()):
                    self.update()
                    return
                # Anything still inside an entered detail is a click on the
                # model seen through it, so it is taken the way a click in the
                # model window is: held until release, which is what tells a
                # pick from the start of a band.
                if self.layout_view._entered() is not None:
                    self._press_pos = pos
                    self._box_active = False
                    return
                add = bool(ev.modifiers() & (
                    Qt.KeyboardModifier.ShiftModifier
                    | Qt.KeyboardModifier.ControlModifier))
                if self.layout_view.press(pos.x(), pos.y(), add=add):
                    self.layoutSelectionChanged.emit()
                    self.update()
                return
            if self._take_gumball(pos, ev):
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
            if self._move_gumball(pos, ev):  # dragging or lighting a handle
                self._last_mouse = pos
                return
            if ev.buttons() & Qt.MouseButton.LeftButton \
                    and self._press_pos is not None:
                self._track_band(pos)        # sweeping the model in a detail
                self._last_mouse = pos
                return
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
            from .camera import drag_pans
            shift = bool(ev.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            if drag_pans(self.camera.projection, shift):
                self.camera.pan(dx, dy, self.height())
            else:
                self.camera.orbit(dx * speed, dy * speed)
            self.update()
        elif self._move_gumball(pos, ev):
            pass
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
            self._track_band(pos)
        elif self.point_mode:
            pt = self.world_point_at(pos.x(), pos.y())
            if pt is not None:
                self.mouseWorldMoved.emit(pt)
        self._last_mouse = pos

    def _take_gumball(self, pos, ev) -> bool:
        """Whether this press took hold of a gumball handle.

        The same on a sheet as in the model window: inside a detail the
        handles are drawn on the same objects, through the same eye, so a
        press on one means what it means anywhere else.
        """
        handle = self.gumball.hit_test(pos.x(), pos.y())
        if handle is None:
            return False
        if not self.gumball.begin_drag(handle, pos.x(), pos.y(),
                                       ev.modifiers()):
            return False
        self._gumball_press = pos
        self.update()
        return True

    def _move_gumball(self, pos, ev) -> bool:
        """Whether the mouse move was the gumball's: a drag, or a hover."""
        if self.gumball.drag is not None \
                and ev.buttons() & Qt.MouseButton.LeftButton:
            label = self.gumball.drag_to(pos.x(), pos.y(), ev.modifiers())
            if label:
                from PySide6.QtWidgets import QMainWindow
                win = self.window()
                if isinstance(win, QMainWindow):
                    win.statusBar().showMessage(label)
            self.update()
            return True
        if not ev.buttons() and not self.point_mode:
            if self.gumball.update_hover(pos.x(), pos.y()):
                self.update()
            # Only a cursor actually on a handle is the gumball's: a sheet has
            # its own things to light up under one that is not.
            return self.gumball.hover is not None
        return False

    def _track_band(self, pos):
        """Grow the selection band, once the press has moved far enough to be
        a sweep rather than a click."""
        if (abs(pos.x() - self._press_pos.x()) > 4
                or abs(pos.y() - self._press_pos.y()) > 4):
            self._box_active = True
            self._box_end = pos
            self.update()

    def _fire_chord(self, ev) -> bool:
        """Run the command bound to this button-and-modifiers, if any.

        Asked on release rather than on press, because these are the same
        buttons that orbit and pan: acting the moment the button went down
        would mean holding the modifiers cost you the drag. Nothing is
        bound out of the box, so this changes nothing until someone asks
        for it.
        """
        chords = (self.config.get("mouse", "chords", default={}) or {}
                  if self.config else {})
        if not chords:
            return False
        button = {Qt.MouseButton.MiddleButton: "middle",
                  Qt.MouseButton.RightButton: "right"}.get(ev.button())
        if button is None:
            return False
        mods = ev.modifiers()
        command = _cfg.chord_command(chords, _cfg.chord_key(
            button,
            ctrl=bool(mods & Qt.KeyboardModifier.ControlModifier),
            shift=bool(mods & Qt.KeyboardModifier.ShiftModifier),
            alt=bool(mods & Qt.KeyboardModifier.AltModifier)))
        if not command:
            return False
        self.chordActivated.emit(command)
        return True

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.MouseButton.RightButton:
            press = getattr(self, "_rmb_press", None)
            self._rmb_press = None
            pos = ev.position()
            if press is not None and \
                    (pos - press).manhattanLength() <= 4:
                # a click, not an orbit/pan drag
                if self._fire_chord(ev):
                    return
                self.enterShortcut.emit()      # Rhino-style Enter
                return
        if ev.button() == Qt.MouseButton.MiddleButton:
            press = getattr(self, "_mmb_press", None)
            self._mmb_press = None
            if press is not None and \
                    (ev.position() - press).manhattanLength() <= 4:
                # a click, not an orbit drag
                if self._fire_chord(ev):
                    return
                self.popupRequested.emit()     # recent commands
                return
        if ev.button() != Qt.MouseButton.LeftButton:
            if (ev.button() == self._nav_button()
                    and self.display_mode == "technical"):
                self.update()      # navigation ended: recompute HLR view
            return
        if self.space != "model":
            if self.gumball.drag is not None:
                self._release_gumball(ev)   # let go of a handle in a detail
                return
            if self._press_pos is not None or self._box_active:
                self._finish_pick(ev)      # the press was inside a detail
                self.update()
                return
            self.layout_view.release_drag()
            self.layoutSelectionChanged.emit()
            self.update()
            return
        if self.gumball.drag is not None:
            self._release_gumball(ev)
            return
        if self._cv_drag is not None:
            self._cv_drag = None
            return
        self._finish_pick(ev)

    def _release_gumball(self, ev):
        """Letting go of a handle: end the drag, or keep it live to type in.

        A click that never moved is someone asking to type an exact value, so
        the handle stays armed and Enter commits it.
        """
        press = getattr(self, "_gumball_press", None)
        moved = (press is not None
                 and (ev.position() - press).manhattanLength() > 4)
        d = self.gumball.drag
        if d["typed"] or (not moved and self.gumball.accepts_typing()):
            self.gumball.arm()
        else:
            self.gumball.end_drag()
        self.update()

    def _finish_pick(self, ev):
        """What a left release does to the selection, band or single click.

        The same on a sheet as in the model window, because inside a detail it
        is the same objects being picked through the same kind of projection.
        """
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
                    and mods & Qt.KeyboardModifier.ShiftModifier):
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
        eye = self._eye()
        picked = []
        selectable = [obj for obj in self.scene.visible_objects()
                      if self.scene.is_selectable(obj.id)
                      and self.selection.filter_allows(obj.kind)]
        for obj in self._pick_candidates(selectable, *rect, w, h):
            mesh = obj.mesh
            if len(mesh.edge_segments):
                segs = mesh.edge_segments
                if crossing:
                    # a crossing box asks whether *any* point falls inside,
                    # so the ones nowhere near it change no answer. A window
                    # box asks whether *every* point does, and a narrowed set
                    # would answer yes for a mesh hanging out of the box.
                    segs, _ = self._near_segments(mesh, *rect, w, h)
                    if not len(segs):
                        continue
                pts = segs.reshape(-1, 3)
            elif len(mesh.vertices):
                pts = mesh.vertices
            else:
                continue
            scr = eye.project(pts.astype(float), w, h)
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
        key = obj.mesh.uid            # not id(obj.mesh) — see DisplayMesh.uid
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

    def event(self, ev):
        # Qt spends Tab on focus navigation before keyPressEvent is reached,
        # so the direction lock has to be claimed here or clicking in the
        # viewport mid-pick would quietly cost you the key
        if (ev.type() == ev.Type.KeyPress and ev.key() == Qt.Key.Key_Tab
                and self.point_mode and self.space == "model"):
            self.tabPressed.emit()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev):
        # while a gumball drag is live, type an exact distance/angle/factor
        if self.gumball.drag is not None:
            key = ev.key()
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                if self.gumball.commit_typed():
                    self.update()
                    return
            elif key == Qt.Key.Key_Escape:
                self.gumball.cancel_drag()
                self.update()
                return
            elif key == Qt.Key.Key_Backspace:
                if self.gumball.type_char("back"):
                    self.update()
                    return
            elif ev.text() in "0123456789.-" and ev.text() \
                    and self.gumball.accepts_typing():
                self.gumball.type_char(ev.text())
                self.update()
                return
        if self.space != "model":
            lv = self.layout_view
            if ev.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) \
                    and lv.delete_selected():
                self.update()
                return
            if ev.key() == Qt.Key.Key_Escape and (lv.selected or lv.corners):
                # A first Escape lets go of the corner, a second of the
                # detail it belongs to.
                if lv.corners:
                    lv.corners = []
                else:
                    lv.selected = []
                self.layoutSelectionChanged.emit()
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
