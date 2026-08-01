"""One copy of a mesh's vertex data, however many viewports show it.

Every viewport used to upload its own buffers for every object, which on the
cave file costs about 676 MB per extra view — quad nearly doubled resident
memory. Buffers can be shared between contexts in a share group, so they are
uploaded once and handed out; VAOs cannot be shared and stay per viewport.

The registry is tested with fake buffers: the reference counting is where the
bugs live, and it is pure bookkeeping. Whether the handles it hands out draw
anything is a question only a real GL context can answer, and that is what
the viewport benchmark is for.
"""

import pytest

from serpentine3d.ui import gpu_share


@pytest.fixture(autouse=True)
def _empty_registry():
    gpu_share.reset()
    yield
    gpu_share.reset()


class FakeBuffers:
    def __init__(self, tag="x", nbytes=0):
        self.tag = tag
        self.nbytes = nbytes
        self.released = 0

    def release(self):
        self.released += 1


def test_second_acquire_reuses_the_first_upload():
    builds = []

    def build():
        builds.append(1)
        return FakeBuffers()

    a = gpu_share.acquire("mesh-1", build)
    b = gpu_share.acquire("mesh-1", build)
    assert a is b
    assert len(builds) == 1, "the second viewport re-uploaded the mesh"


def test_buffers_outlive_a_single_release():
    buf = FakeBuffers()
    gpu_share.acquire("mesh-1", lambda: buf)
    gpu_share.acquire("mesh-1", lambda: buf)
    gpu_share.release("mesh-1")
    assert buf.released == 0, "freed while another viewport was still drawing it"
    gpu_share.release("mesh-1")
    assert buf.released == 1


def test_freed_key_builds_again():
    """Released for the last time means gone, not merely unreferenced: the
    next acquire has to upload rather than hand back a dead handle."""
    first, second = FakeBuffers("first"), FakeBuffers("second")
    gpu_share.acquire("mesh-1", lambda: first)
    gpu_share.release("mesh-1")
    got = gpu_share.acquire("mesh-1", lambda: second)
    assert got is second


def test_distinct_keys_do_not_collide():
    a = gpu_share.acquire("mesh-1", lambda: FakeBuffers("a"))
    b = gpu_share.acquire("mesh-2", lambda: FakeBuffers("b"))
    assert a is not b
    assert gpu_share.count() == 2


def test_releasing_an_unknown_key_is_quiet():
    """A viewport tearing down after the registry was cleared, or twice over
    — neither is worth an exception on the way out."""
    gpu_share.release("never-acquired")
    gpu_share.acquire("mesh-1", lambda: FakeBuffers())
    gpu_share.release("mesh-1")
    gpu_share.release("mesh-1")
    assert gpu_share.count() == 0


def test_a_failed_build_leaves_no_entry():
    """An upload that raises must not leave a half-made entry behind that
    every later acquire would hand out."""
    with pytest.raises(RuntimeError):
        gpu_share.acquire("mesh-1", _raise)
    assert gpu_share.count() == 0
    good = FakeBuffers("good")
    assert gpu_share.acquire("mesh-1", lambda: good) is good


def _raise():
    raise RuntimeError("upload failed")


def test_count_tracks_distinct_meshes_not_viewports():
    for _ in range(4):                       # four viewports, one mesh
        gpu_share.acquire("mesh-1", lambda: FakeBuffers())
    assert gpu_share.count() == 1


def test_total_bytes_counts_each_mesh_once():
    """What the model costs on the GPU. Counted per mesh, not per viewport —
    that is the whole point, and it is the number to watch when a layout is
    blamed for memory."""
    gpu_share.acquire("mesh-1", lambda: FakeBuffers(nbytes=1000))
    gpu_share.acquire("mesh-1", lambda: FakeBuffers(nbytes=1000))
    gpu_share.acquire("mesh-2", lambda: FakeBuffers(nbytes=250))
    assert gpu_share.total_bytes() == 1250
    gpu_share.release("mesh-2")
    assert gpu_share.total_bytes() == 1000


# --- the contexts have to be in a share group for any of this to work ------

def test_share_contexts_is_set_before_the_application_exists():
    """AA_ShareOpenGLContexts is what puts every viewport's context in one
    share group, and it is only read when QApplication is constructed. Set it
    late and the buffers handed between viewports are not valid in the
    context that draws them — which shows up as an empty viewport, not as an
    error, so it is worth a test rather than a comment."""
    import inspect

    from serpentine3d import launcher

    src = inspect.getsource(launcher)
    assert "AA_ShareOpenGLContexts" in src
    flag = src.index("AA_ShareOpenGLContexts")
    made = src.index("QApplication(")
    assert flag < made, "share group set after the application was created"


# --- dropping a viewport's arrays without dropping the claim ---------------

def test_forget_gives_up_the_share_claim_without_deleting_arrays():
    """Undocking destroys a viewport's context, taking its vertex arrays with
    it. Their names must not be deleted — they are gone, and the handles are
    meaningless in the new context — but the claim on the shared buffers has
    to be given back, or the mesh is pinned in GPU memory for good.

    Built by hand rather than by drawing: the point is the bookkeeping, and a
    real _GpuObject needs a GL context an offscreen test has no way to make.
    """
    from serpentine3d.ui.viewport import _GpuObject

    other, buf = FakeBuffers("kept"), FakeBuffers()
    gpu_share.acquire(("mesh-0", None), lambda: other)   # a second viewport
    gpu_share.acquire(("mesh-0", None), lambda: other)
    gpu_share.acquire(("mesh-1", None), lambda: buf)     # only this one

    for key in (("mesh-1", None), ("mesh-0", None)):
        gpu = object.__new__(_GpuObject)
        gpu._share_key = key
        gpu.tri_vao = gpu.line_vao = gpu.iso_vao = gpu.thick_vao = 7
        gpu.forget()
        assert (gpu.tri_vao, gpu.line_vao, gpu.iso_vao, gpu.thick_vao) \
            == (0, 0, 0, 0)

    assert buf.released == 1, "last claim gone, but the mesh is still resident"
    assert other.released == 0, "freed while another viewport was drawing it"
    assert gpu_share.count() == 1


def test_a_lost_context_forgets_rather_than_drops_its_objects():
    """initializeGL runs again after a dock or undock. Clearing the cache
    outright used to be free; now every entry holds a claim on shared buffers,
    and dropping one silently pins that mesh in GPU memory for good."""
    import inspect

    from serpentine3d.ui.viewport import Viewport

    src = inspect.getsource(Viewport.initializeGL)
    assert "forget()" in src, "lost-context path drops its share claims"


# --- pure geometry: the wide-line quads ------------------------------------

def test_thick_arrays_makes_two_triangles_per_segment():
    import numpy as np

    from serpentine3d.ui.viewport import _thick_arrays

    segs = np.array([[[0, 0, 0], [1, 0, 0]],
                     [[1, 0, 0], [1, 1, 0]]], np.float32)
    verts, idx = _thick_arrays(segs)
    assert verts.shape == (8, 7), "four corners of seven floats per segment"
    assert len(idx) == 12, "two triangles per segment"
    assert idx.max() == 7

    # Each corner carries its own end, the other end, and which side it is
    # offset to — the shader widens the line from that.
    assert list(verts[0, :3]) == [0, 0, 0]
    assert list(verts[0, 3:6]) == [1, 0, 0]
    assert {verts[0, 6], verts[1, 6]} == {1.0, -1.0}
