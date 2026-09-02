"""The two GL decisions that can only be made at one moment each.

Both of them are about agreeing with the driver before anything draws,
and both have exactly one window in the startup sequence in which they
can still be made: the surface format before the QApplication exists,
the PyOpenGL binding after it does but before the viewport is imported.
That is why they live here and not in the viewport, which the launcher
will not import until the splash is up (it drags the geometry kernel in
behind it).

Neither of them mattered while everyone was on GLX. On EGL, which is
what Wayland gives you, both are the difference between an app and a
window full of nothing.
"""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QSurfaceFormat
from PySide6.QtWidgets import QApplication


def set_default_gl_format():
    """These GL settings are only read as QApplication is built, so this
    has to be called before one exists."""
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.OpenGLContextProfile.CoreProfile)
    # Say desktop GL out loud. On GLX there is nothing else and this is
    # free, but on EGL (Wayland, and NVIDIA under X too) Qt otherwise
    # binds OpenGL ES, which has no core profile, and every context
    # comes back EGL_BAD_MATCH (3009): ours, and the one Qt's widget
    # backing store needs, so even a plain window renders to nothing.
    fmt.setRenderableType(QSurfaceFormat.RenderableType.OpenGL)
    fmt.setSamples(4)
    fmt.setDepthBufferSize(24)
    QSurfaceFormat.setDefaultFormat(fmt)

    # One share group for every viewport's context: a mesh is uploaded
    # once however many views show it. See ui.gpu_share.
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)


def match_pyopengl_to_qt() -> str | None:
    """Make PyOpenGL talk to the driver through the same door Qt did.

    PyOpenGL picks a binding once, when `OpenGL.platform` is imported,
    from the environment: EGL if the session says Wayland, GLX
    otherwise. Qt picks its own by asking the driver. Everything
    PyOpenGL does per context - keeping an array alive across a
    `glVertexAttribPointer`, caching an extension lookup - it keys on
    that binding's idea of the current context, so when the two
    disagree it sees no context at all, and the first GL call raises
    "Attempt to retrieve context when no valid context" from inside
    `initializeGL`. That surfaces as a hundred frames of "Error calling
    Python override of ..." and a viewport that never draws.

    They disagree in both directions - X11 where Qt went to EGL, and a
    Wayland session that fell back to XWayland and GLX - so the answer
    is stated either way rather than left to agree by luck.

    Returns the binding it pinned, or None if it left the guess alone.
    Call it once the QApplication exists (the probe needs a context to
    make current) and before anything imports the viewport.
    """
    if os.environ.get("PYOPENGL_PLATFORM"):
        return None                     # someone chose by hand
    if _pyopengl_already_chose():
        return None                     # the variable is dead letter now
    binding = _qt_gl_binding()
    if binding is None:
        return None                     # nothing to measure, nothing to say
    os.environ["PYOPENGL_PLATFORM"] = binding
    return binding


def _pyopengl_already_chose() -> bool:
    return "OpenGL.platform" in sys.modules


def _qt_gl_binding() -> str | None:
    """"egl", "glx", or None if there is no GL here to ask about.

    Answered by making a context current and seeing whether GLX knows
    it, which is the only question that matters and the only terms that
    matter: whether the binding PyOpenGL is about to choose can see the
    context it is about to be handed.
    """
    from PySide6.QtGui import QOffscreenSurface, QOpenGLContext

    ctx = QOpenGLContext()
    if not ctx.create():
        return None         # no GL to speak of; nothing to correct
    surface = QOffscreenSurface()
    surface.setFormat(ctx.format())
    surface.create()
    if not surface.isValid() or not ctx.makeCurrent(surface):
        return None
    try:
        return "egl" if _glx_sees_no_context() else "glx"
    finally:
        ctx.doneCurrent()


def _glx_sees_no_context() -> bool:
    """`glXGetCurrentContext()`, which is PyOpenGL's GLX binding's whole
    idea of where it is. Nothing current, no libGL, no such symbol: all
    of them mean the same thing here, that GLX cannot tell us where we
    are."""
    import ctypes

    try:
        gl = ctypes.CDLL("libGL.so.1")
        current = gl.glXGetCurrentContext
    except (OSError, AttributeError):
        return True
    current.restype = ctypes.c_void_p
    current.argtypes = []
    return not current()
