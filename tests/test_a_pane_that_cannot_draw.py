"""A frame that fails must not surface as someone else's error.

An exception let out of `paintGL` is an exception let out of a Qt virtual
call. Qt keeps going, and the next Python override called from C++ (a size
hint, an event filter, anything) is the one that reports it, as a
SystemError about a QSize "returned with an exception set". The traceback
you get names a widget that has nothing to do with it, and the real error
is gone. `initializeGL` already says as much about the OpenGL 3.3 check,
and exits rather than raise; a frame has somewhere better to go.

So: keep it inside, say what happened once, and stop drawing that pane.
"""

import pytest
from OpenGL.error import GLError

from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.ui.viewport import Viewport


@pytest.fixture
def pane():
    """Never shown, and the draw is stubbed out before it reaches GL: the
    offscreen platform has no usable context to call one on."""
    scene = Scene()
    return Viewport(scene, SelectionManager(scene))


def _breaks(pane, exc):
    calls = []

    def boom():
        calls.append(1)
        raise exc

    pane._reset_gl_state = boom          # the first thing a frame does
    return calls


def test_the_driver_refusing_a_frame_stays_in_the_frame(pane):
    _breaks(pane, GLError(err=1285))     # GL_OUT_OF_MEMORY, as a dead
    pane.paintGL()                       # context reports a draw
    assert pane.paint_failed


def test_it_does_not_try_again_every_frame(pane):
    """Otherwise a broken context is a wall of identical tracebacks, one
    per repaint, for as long as the window is open."""
    calls = _breaks(pane, GLError(err=1285))
    for _ in range(5):
        pane.paintGL()
    assert len(calls) == 1


def test_a_bug_in_the_draw_path_is_still_loud(pane, capsys):
    """Caught is not swallowed. The traceback is the whole point of
    catching it: it is what the SystemError was throwing away."""
    _breaks(pane, AttributeError("no such thing"))
    pane.paintGL()
    err = capsys.readouterr().err
    assert "AttributeError: no such thing" in err
    assert "paintGL" in err or "_paint_frame" in err


def test_a_new_context_gets_another_go(pane):
    """Docking a pane destroys its context and builds another, which is
    where a viewport that gave up has reason to try again."""
    import inspect
    src = inspect.getsource(Viewport.initializeGL)
    assert "_paint_failed = False" in src
