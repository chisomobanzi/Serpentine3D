"""The app has to start on drivers that go through EGL, not just GLX.

Reported from Manjaro/KDE/Wayland on an RTX 3080: the welcome window
came up spewing `QEGLPlatformContext: Failed to create context: 3009`
(EGL_BAD_MATCH) and New Model did nothing. Two separate faults, both of
them "we assumed GLX".

First, the format. We ask for OpenGL 3.3 **Core profile** but left
`renderableType` at its default, and on the EGL path Qt then binds
OpenGL **ES**, which has no core profile: EGL_BAD_MATCH, every context,
including the one Qt's own widget backing store needs.

Second, PyOpenGL, which picks its driver binding once, at import, by
reading the environment: EGL if the session says Wayland, GLX
otherwise. Qt picks its own, by asking the driver. When the two guesses
disagree, PyOpenGL's `GetCurrentContext()` asks a binding that cannot
see Qt's context, it answers null, and the first GL call in
`initializeGL` raises "Attempt to retrieve context when no valid
context" - the viewport never draws, which is what "New Model does
nothing" looked like from outside.

They disagree in both directions: X11 where Qt went to EGL (NVIDIA, or
QT_XCB_GL_INTEGRATION=xcb_egl, which is how this was reproduced here),
and a Wayland session where Qt could not get a Wayland surface and fell
back to XWayland and GLX. So Qt is asked and PyOpenGL is told, rather
than both being left to guess.
"""

from __future__ import annotations

import inspect
import os

import pytest

pytest.importorskip("PySide6")

from PySide6.QtGui import QSurfaceFormat  # noqa: E402

from serpentine3d import launcher  # noqa: E402
from serpentine3d.utils import glsetup  # noqa: E402
from serpentine3d.utils.glsetup import set_default_gl_format  # noqa: E402


@pytest.fixture
def restore_default_format():
    """The default format is process-wide; put it back afterwards."""
    before = QSurfaceFormat.defaultFormat()
    yield
    QSurfaceFormat.setDefaultFormat(before)


@pytest.fixture
def unset_pyopengl_platform():
    """Also process-wide, and leaking it would send every later GL test
    at a binding that cannot see the context."""
    before = os.environ.get("PYOPENGL_PLATFORM")
    os.environ.pop("PYOPENGL_PLATFORM", None)
    yield
    os.environ.pop("PYOPENGL_PLATFORM", None)
    if before is not None:
        os.environ["PYOPENGL_PLATFORM"] = before


def test_the_format_asks_for_desktop_gl_not_es(restore_default_format):
    set_default_gl_format()
    got = QSurfaceFormat.defaultFormat()
    assert got.renderableType() == QSurfaceFormat.RenderableType.OpenGL, \
        ("renderableType left at the default: on EGL Qt binds OpenGL ES "
         "and a core-profile context comes back EGL_BAD_MATCH (3009)")


def test_it_still_asks_for_what_the_shaders_need(restore_default_format):
    set_default_gl_format()
    got = QSurfaceFormat.defaultFormat()
    assert (got.majorVersion(), got.minorVersion()) == (3, 3)
    assert got.profile() == QSurfaceFormat.OpenGLContextProfile.CoreProfile
    assert got.samples() == 4
    assert got.depthBufferSize() >= 24


def test_the_launcher_does_not_keep_its_own_copy_of_the_format():
    """There were two hand-rolled copies of this format, and a fix to
    one would not have reached the other. There is one now."""
    src = inspect.getsource(launcher.main)
    assert "set_default_gl_format()" in src
    assert "setProfile" not in src, "the launcher is rolling its own again"


def test_the_viewport_helper_is_the_same_one():
    from serpentine3d.ui import viewport as vp_mod
    assert vp_mod.set_default_gl_format is set_default_gl_format


def test_the_helper_is_cheap_to_import():
    """The launcher calls this before the splash, so it must not drag
    the geometry kernel in with it."""
    import ast

    tree = ast.parse(inspect.getsource(glsetup))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.add(node.module or "")
    heavy = {n for n in names
             if n.split(".")[0] in {"OpenGL", "OCP", "numpy", "ezdxf"}
             or n.startswith(("serpentine3d.core", "serpentine3d.ui"))
             or ".core" in n or ".ui" in n}
    assert not heavy, f"{sorted(heavy)} imported on the startup path"


# --- PyOpenGL has to end up on the same binding Qt chose ---------------

def test_glx_is_asked_the_very_question_pyopengl_will_ask():
    """The probe is not a guess about the platform, it is the exact call
    PyOpenGL's GLX binding makes. Nothing is current here, so it has to
    come back empty - and above all it has to answer, not raise."""
    assert glsetup._glx_sees_no_context() is True


def test_pyopengl_is_pinned_to_egl_when_qt_is(monkeypatch,
                                              unset_pyopengl_platform):
    monkeypatch.setattr(glsetup, "_pyopengl_already_chose", lambda: False)
    monkeypatch.setattr(glsetup, "_qt_gl_binding", lambda: "egl")
    assert glsetup.match_pyopengl_to_qt() == "egl"
    assert os.environ["PYOPENGL_PLATFORM"] == "egl"


def test_pyopengl_is_pinned_to_glx_when_qt_is(monkeypatch,
                                              unset_pyopengl_platform):
    """Left to itself PyOpenGL reads XDG_SESSION_TYPE, so in a Wayland
    session it assumes EGL - including when Qt could not get a Wayland
    surface and quietly fell back to XWayland, where Qt is on GLX. That
    is this bug with the two halves swapped, and it breaks just as
    completely, so the binding is stated either way rather than left to
    agree by luck."""
    monkeypatch.setattr(glsetup, "_pyopengl_already_chose", lambda: False)
    monkeypatch.setattr(glsetup, "_qt_gl_binding", lambda: "glx")
    assert glsetup.match_pyopengl_to_qt() == "glx"
    assert os.environ["PYOPENGL_PLATFORM"] == "glx"


def test_nothing_is_pinned_when_there_is_no_context_to_measure(
        monkeypatch, unset_pyopengl_platform):
    """Offscreen, or a machine with no GL at all. We know nothing, so we
    say nothing and let PyOpenGL guess as it always did."""
    monkeypatch.setattr(glsetup, "_pyopengl_already_chose", lambda: False)
    monkeypatch.setattr(glsetup, "_qt_gl_binding", lambda: None)
    assert glsetup.match_pyopengl_to_qt() is None
    assert "PYOPENGL_PLATFORM" not in os.environ


def test_a_binding_chosen_by_hand_wins(monkeypatch, unset_pyopengl_platform):
    """Someone debugging a driver sets this; we do not argue."""
    os.environ["PYOPENGL_PLATFORM"] = "osmesa"
    monkeypatch.setattr(glsetup, "_pyopengl_already_chose", lambda: False)
    monkeypatch.setattr(glsetup, "_qt_gl_binding", lambda: "egl")
    assert glsetup.match_pyopengl_to_qt() is None
    assert os.environ["PYOPENGL_PLATFORM"] == "osmesa"


def test_it_does_not_pretend_once_pyopengl_has_already_chosen(
        monkeypatch, unset_pyopengl_platform):
    """PyOpenGL reads the variable as `OpenGL.platform` is imported and
    never again. Setting it after that would change nothing while
    looking like it had."""
    monkeypatch.setattr(glsetup, "_pyopengl_already_chose", lambda: True)
    monkeypatch.setattr(glsetup, "_qt_gl_binding", lambda: "egl")
    assert glsetup.match_pyopengl_to_qt() is None
    assert "PYOPENGL_PLATFORM" not in os.environ


def test_the_launcher_picks_the_binding_at_the_one_moment_it_can():
    """After the QApplication, because the probe needs a context to make
    current; before the app is imported, because that import is what
    pulls PyOpenGL in and freezes its choice."""
    src = inspect.getsource(launcher.main)
    assert "match_pyopengl_to_qt()" in src, \
        "nothing tells PyOpenGL which binding Qt picked"
    assert (src.index("QApplication(sys.argv)")
            < src.index("match_pyopengl_to_qt()")
            < src.index("from .app import run_app"))
