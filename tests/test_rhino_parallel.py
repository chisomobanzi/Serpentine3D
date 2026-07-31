"""Converting a .3dm across processes (GitHub #3).

A 65259-object file took about fifteen minutes to open on a 22-core machine.
Almost all of that is rhino3dm's Python binding — reading one vertex costs
about 25 us, and a survey mesh has millions — so it is Python-side work that
holds the GIL. Threads cannot help; processes can, because each object
converts on its own.

The wrinkle is that the app cannot fork: its tessellation threads hold locks
a forked child would inherit and wait on forever. So one thread-free process
is spawned to read the file, and it forks the converters, which inherit the
model copy-on-write instead of re-reading it.
"""

import sys

import numpy as np
import pytest
import rhino3dm as r3

from serpentine3d.core import geometry
from serpentine3d.core.mesh import MeshShape
from serpentine3d.fileio import rhino
from serpentine3d.fileio import rhino_parallel as rp
from serpentine3d.fileio.progress import Cancelled, Progress


def _boxes_3dm(path, n, layer="Walls"):
    """A .3dm of `n` brep boxes on one named layer."""
    model = r3.File3dm()
    rl = r3.Layer()
    rl.Name = layer
    rl.Color = (200, 100, 50, 255)
    index = model.Layers.Add(rl)
    for i in range(n):
        box = r3.Box(r3.BoundingBox(r3.Point3d(i * 10, 0, 0),
                                    r3.Point3d(i * 10 + 5, 5, 5)))
        attrs = r3.ObjectAttributes()
        attrs.LayerIndex = index
        attrs.Name = f"box {i}"
        model.Objects.AddBrep(r3.Brep.CreateFromBox(box), attrs)
    assert model.Write(path, 8)
    return path


def _survey_3dm(path, side=40, boxes=3):
    """A .3dm whose weight is all in one mesh, the way a survey file's is.

    Quads and triangles both, so a piece boundary has to fall in the middle
    of each kind.
    """
    model = r3.File3dm()
    m = r3.Mesh()
    for i in range(side):
        for j in range(side):
            m.Vertices.Add(float(i), float(j), float((i * j) % 7))
    for i in range(side - 1):
        for j in range(side - 1):
            a = i * side + j
            if (i + j) % 3:
                m.Faces.AddFace(a, a + 1, a + side + 1, a + side)
            else:
                m.Faces.AddFace(a, a + 1, a + side)
    attrs = r3.ObjectAttributes()
    attrs.Name = "the survey"
    model.Objects.AddMesh(m, attrs)
    for i in range(boxes):
        box = r3.Box(r3.BoundingBox(r3.Point3d(i * 10, 0, 0),
                                    r3.Point3d(i * 10 + 5, 5, 5)))
        small = r3.ObjectAttributes()
        small.Name = f"box {i}"
        model.Objects.AddBrep(r3.Brep.CreateFromBox(box), small)
    assert model.Write(path, 8)
    return path


# ------------------------------------------------------------------ batching

def test_batches_cover_every_object_exactly_once():
    batches = rp._batches(100, 8)
    flat = sorted(i for b in batches for i in b)
    assert flat == list(range(100))


def test_batches_interleave_rather_than_slicing_the_file_in_blocks():
    """A drawing keeps its meshes together, so contiguous blocks hand one
    worker every expensive object — measured as 6.5x collapsing to 1.5x."""
    batches = rp._batches(100, 10)
    assert all(len(set(b)) == len(b) for b in batches)
    assert max(b[0] for b in batches) < 10, "first batch took a whole block"
    for b in batches:
        assert max(b) - min(b) > 50, f"{b} came from one region of the file"


def test_no_objects_means_no_batches():
    assert rp._batches(0, 8) == []


# ------------------------------------------------- shapes crossing the pipe

def test_a_mesh_survives_the_trip_between_processes():
    mesh = MeshShape(np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0]]),
                     np.array([[0, 1, 2]], np.uint32))
    back = rp._decode(rp._encode(mesh))
    assert isinstance(back, MeshShape)
    assert np.allclose(back.vertices, mesh.vertices)
    assert np.array_equal(back.triangles, mesh.triangles)


def test_an_occ_solid_survives_the_trip_between_processes():
    """TopoDS_Shape does not pickle at all; it goes as a BinTools archive."""
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    box = BRepPrimAPI_MakeBox(2., 3., 4.).Shape()
    back = rp._decode(rp._encode(box))
    assert not back.IsNull()
    assert geometry.volume(back) == pytest.approx(24.0, rel=1e-6)


def test_a_decoded_shape_keeps_its_concrete_class():
    """BinTools hands back a bare TopoDS_Shape whatever went in, and OCCT's
    bindings reject one where they want a TopoDS_Edge. The scene must not be
    able to tell which process built an object."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    edge = BRepBuilderAPI_MakeEdge(gp_Pnt(0, 0, 0), gp_Pnt(1, 1, 1)).Edge()
    assert type(rp._decode(rp._encode(edge))) is type(edge)

    solid = geometry.occ.to_solid(BRepPrimAPI_MakeBox(1., 1., 1.).Shape())
    assert type(rp._decode(rp._encode(solid))) is type(solid)


def test_encoded_shapes_are_picklable():
    """Whatever crosses the pipe has to survive pickle, which a raw
    TopoDS_Shape does not — it aborts the interpreter."""
    import pickle
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    payload = rp._encode(BRepPrimAPI_MakeBox(1., 1., 1.).Shape())
    assert geometry.volume(rp._decode(pickle.loads(pickle.dumps(payload)))) \
        == pytest.approx(1.0, rel=1e-6)


# -------------------------------------------------------------- end to end

def test_parallel_import_gives_the_same_objects_as_serial(tmp_path):
    path = _boxes_3dm(str(tmp_path / "boxes.3dm"), 12)
    serial = rhino.import_3dm(path)
    parallel = rp.import_3dm_parallel(path, workers=3)

    assert [n for n, _, _ in parallel] == [n for n, _, _ in serial]
    assert [m for _, _, m in parallel] == [m for _, _, m in serial]
    assert [geometry.volume(s) for _, s, _ in parallel] \
        == pytest.approx([geometry.volume(s) for _, s, _ in serial], rel=1e-6)


def test_parallel_import_agrees_about_colour(tmp_path):
    """Colour is resolved in the worker, which is a different process holding

    its own copy of the model. The two paths disagreeing would be worse than
    either being wrong.
    """
    path = str(tmp_path / "coloured.3dm")
    model = r3.File3dm()
    layer = r3.Layer()
    layer.Name = "everything"
    layer.Color = (220, 30, 30, 255)
    model.Layers.Add(layer)
    mat = r3.Material()
    mat.DiffuseColor = (40, 90, 240, 255)
    mat.Transparency = 0.25
    model.Materials.Add(mat)
    for i in range(6):
        box = r3.Box(r3.BoundingBox(r3.Point3d(i * 10, 0, 0),
                                    r3.Point3d(i * 10 + 5, 5, 5)))
        attrs = r3.ObjectAttributes()
        attrs.Name = f"box {i}"
        if i % 3 == 1:
            attrs.ObjectColor = (30, 200, 60, 255)
            attrs.ColorSource = r3.ObjectColorSource.ColorFromObject
        elif i % 3 == 2:
            attrs.MaterialIndex = 0
            attrs.MaterialSource = r3.ObjectMaterialSource.MaterialFromObject
            attrs.ColorSource = r3.ObjectColorSource.ColorFromMaterial
        model.Objects.AddBrep(r3.Brep.CreateFromBox(box), attrs)
    assert model.Write(path, 8)

    serial = {n: m for n, _, m in rhino.import_3dm(path)}
    parallel = {n: m for n, _, m in rp.import_3dm_parallel(path, workers=3)}
    assert parallel == serial
    assert serial["box 1"]["color"] == pytest.approx((30 / 255, 200 / 255,
                                                      60 / 255), abs=1e-3)
    assert serial["box 2"]["material"]["opacity"] == pytest.approx(0.75,
                                                                   abs=1e-3)


def test_parallel_import_reports_progress(tmp_path):
    path = _boxes_3dm(str(tmp_path / "boxes.3dm"), 12)
    seen = []
    rp.import_3dm_parallel(path, progress=Progress(
        lambda f, m: seen.append((f, m))), workers=3)

    assert seen, "no progress at all"
    fractions = [f for f, _ in seen]
    assert fractions == sorted(fractions), "progress went backwards"
    assert all(0.0 <= f <= 1.0 for f in fractions), fractions
    assert all(m for _, m in seen), "an update carried no message"


def test_cancelling_a_parallel_import_raises_and_stops(tmp_path):
    path = _boxes_3dm(str(tmp_path / "boxes.3dm"), 12)

    def stop(fraction, message):
        return fraction < 0.5

    with pytest.raises(Cancelled):
        rp.import_3dm_parallel(path, progress=Progress(stop), workers=3)


def test_a_reader_that_dies_silently_raises_rather_than_importing_nothing():
    """A child can die before it can report why — a bundle where the spawned
    interpreter cannot find the kernel, say. All the parent sees then is the
    pipe closing, and an empty import looks exactly like a file of nothing.
    It has to raise, so the serial path gets its turn."""
    with pytest.raises(Exception) as caught:
        rp._assemble([], Progress())
    assert not isinstance(caught.value, Cancelled)


def test_an_empty_file_is_not_mistaken_for_a_dead_reader():
    """A reader that got as far as counting the objects did its job, even
    when the answer was none."""
    assert rp._assemble([("total", 0)], Progress()) == []


def test_a_broken_file_raises_rather_than_returning_nothing(tmp_path):
    bad = tmp_path / "not-really.3dm"
    bad.write_bytes(b"3D Geometry File Format nope")
    with pytest.raises(IOError):
        rp.import_3dm_parallel(str(bad), workers=2)


# ------------------------------------------ one object bigger than a worker

def test_a_mesh_too_big_for_one_worker_is_shared_out():
    """The cave file ends in two meshes of 6.6 million vertices each. Handing
    one to a single worker held the bar at 93% for forty-eight seconds while
    fifteen of the sixteen had nothing left to do."""
    assert rp._piece_count(6_619_136, 16, 200_000) == 34


def test_a_preposterous_mesh_does_not_become_thousands_of_round_trips():
    assert rp._piece_count(10**10, 16, 200_000) == 64


def test_a_mesh_one_worker_can_manage_is_left_alone():
    """Below the threshold the round trip costs more than the reading."""
    assert rp._piece_count(1_000, 16, 200_000) == 1
    assert rp._piece_count(200_000, 16, 200_000) == 1


def test_pieces_cover_every_item_exactly_once_and_in_order():
    """Contiguous, not interleaved as the batches are: the pieces are
    concatenated back together and a face indexes its vertices by position."""
    ranges = rp._pieces(1000, 7)
    assert len(ranges) == 7
    assert [i for lo, hi in ranges for i in range(lo, hi)] == list(range(1000))


def test_there_are_as_many_pieces_as_asked_for_even_of_almost_nothing():
    """The vertex ranges and the face ranges are paired off, so a mesh with
    fewer faces than workers must still answer with a range apiece."""
    assert len(rp._pieces(3, 8)) == 8
    assert len(rp._pieces(0, 4)) == 4


def test_a_mesh_read_in_pieces_comes_back_whole(tmp_path, monkeypatch):
    """Vertex for vertex and triangle for triangle what one process reads."""
    path = _survey_3dm(str(tmp_path / "survey.3dm"))
    serial = rhino.import_3dm(path)
    # The reader is a separate process, so the threshold travels in the
    # environment rather than by patching this one.
    monkeypatch.setenv("SERP3D_IMPORT_SPLIT_VERTICES", "50")
    parallel = rp.import_3dm_parallel(path, workers=3)

    assert [n for n, _, _ in parallel] == [n for n, _, _ in serial]
    meshes = [(a, b) for (_, a, _), (_, b, _) in zip(parallel, serial)
              if isinstance(b, MeshShape)]
    assert meshes, "the fixture stopped holding a mesh"
    for got, want in meshes:
        assert isinstance(got, MeshShape)
        assert np.array_equal(got.vertices, want.vertices)
        assert np.array_equal(got.triangles, want.triangles)


def test_the_bar_keeps_moving_while_one_object_is_being_read(tmp_path,
                                                             monkeypatch):
    """The object count cannot move while a single object is in hand, so the
    pieces report for it. Otherwise the dialog says 11631 of 11759 and sits
    there, which is the complaint that started this."""
    path = _survey_3dm(str(tmp_path / "survey.3dm"))
    monkeypatch.setenv("SERP3D_IMPORT_SPLIT_VERTICES", "50")
    seen = []
    rp.import_3dm_parallel(path, progress=Progress(
        lambda f, m: seen.append((f, m))), workers=3)

    during = [f for f, m in seen if "piece" in m]
    assert len(set(during)) > 1, seen
    assert during == sorted(during), "progress went backwards"
    assert max(during) <= 1.0


def test_a_split_mesh_is_still_the_object_it_was(tmp_path, monkeypatch):
    """Name and layer belong to the object, not to whichever worker happened
    to read its first thousand vertices."""
    path = _survey_3dm(str(tmp_path / "survey.3dm"))
    monkeypatch.setenv("SERP3D_IMPORT_SPLIT_VERTICES", "50")
    names = [n for n, _, _ in rp.import_3dm_parallel(path, workers=3)]
    assert names[0] == "the survey"
    assert names[1:] == ["box 0", "box 1", "box 2"]


def test_a_brep_too_big_for_one_worker_is_shared_out(tmp_path, monkeypatch):
    """A 19105-face unioned polysurface took ~2 minutes on a single worker
    while the rest of the pool sat idle — the mesh treatment (share the one
    object nobody else can help with), but for faces (GitHub #5)."""
    path = _boxes_3dm(str(tmp_path / "boxes.3dm"), 3)
    serial = rhino.import_3dm(path)
    # A box brep has 6 faces; a threshold of 2 forces every box to split.
    monkeypatch.setenv("SERP3D_IMPORT_SPLIT_FACES", "2")
    parallel = rp.import_3dm_parallel(path, workers=3)

    assert [n for n, _, _ in parallel] == [n for n, _, _ in serial]
    assert [m for _, _, m in parallel] == [m for _, _, m in serial]
    # Volume equality means the faces were not just collected but sewn back
    # into the closed solid the serial path builds.
    assert [geometry.volume(s) for _, s, _ in parallel] \
        == pytest.approx([geometry.volume(s) for _, s, _ in serial], rel=1e-6)


def test_the_bar_keeps_moving_while_a_brep_is_being_shared(tmp_path,
                                                           monkeypatch):
    path = _boxes_3dm(str(tmp_path / "boxes.3dm"), 3)
    monkeypatch.setenv("SERP3D_IMPORT_SPLIT_FACES", "2")
    seen = []
    rp.import_3dm_parallel(path, progress=Progress(
        lambda f, m: seen.append((f, m))), workers=3)
    during = [f for f, m in seen if "piece" in m]
    assert len(set(during)) > 1, seen
    assert during == sorted(during), "progress went backwards"


def test_face_split_thresholds_reuse_the_mesh_piece_policy():
    """The cab's 19105-face brep against the default threshold: enough
    pieces that sixteen workers all get some, not thousands of round trips."""
    assert 16 <= rp._piece_count(19_105, 16, rp.split_faces()) <= 64
    assert rp._piece_count(100, 16, rp.split_faces()) == 1


def test_face_split_threshold_travels_in_the_environment(monkeypatch):
    monkeypatch.setenv("SERP3D_IMPORT_SPLIT_FACES", "17")
    assert rp.split_faces() == 17
    monkeypatch.delenv("SERP3D_IMPORT_SPLIT_FACES")
    assert rp.split_faces() == rp.SPLIT_FACES


# ---------------------------------------- keeping the window alive meanwhile

class _Idle:
    """A pipe with nothing to say, then nothing at all."""

    def __init__(self, quiet=3):
        self.quiet = quiet

    def poll(self, timeout=None):
        self.quiet -= 1
        return self.quiet < 0

    def recv(self):
        raise EOFError


def test_waiting_on_the_helper_still_lets_the_window_repaint():
    """The caller drives this on its UI thread. A blocking recv() meant the
    window stopped painting and Cancel stopped answering for as long as a
    batch took — which on a 522 MB file is most of the import."""
    assert list(rp._messages(_Idle(3), interval=0.0)) == [("waiting",)] * 3


def test_a_heartbeat_repaints_without_moving_the_bar():
    seen = []
    rp._assemble([("total", 4), ("batch", 2, 4, []), ("waiting",),
                  ("waiting",)], Progress(lambda f, m: seen.append((f, m))))
    assert seen[-1] == seen[-2] == seen[-3], seen


def test_cancel_is_answered_while_the_helper_is_busy():
    """Cancel used to do nothing at all until a batch happened to land."""
    with pytest.raises(Cancelled):
        rp._assemble([("total", 4), ("waiting",)],
                     Progress(lambda f, m: False))


# ------------------------------------------------- letting the reader go

class _Reader:
    """A reader process that never gets around to exiting."""

    def __init__(self):
        self.waited = []
        self.terminated = False

    def join(self, timeout=None):
        self.waited.append(timeout)

    def is_alive(self):
        return not self.terminated

    def terminate(self):
        self.terminated = True


class _Cancel:
    def __init__(self):
        self.set_ = False

    def set(self):
        self.set_ = True


def test_a_finished_reader_is_not_waited_on():
    """Closing the pipe is the reader's last act after stopping its pool, so
    what is left is a spawned interpreter unloading OCP and rhino3dm — two
    seconds we used to spend inside a join, which reports nothing, so the
    dialog sat frozen at 95% with the work already done."""
    proc, cancel = _Reader(), _Cancel()
    rp._stop(proc, cancel, finished=True)
    assert sum(t for t in proc.waited[:1]) < 0.5, proc.waited
    assert proc.terminated


def test_bailing_out_gives_the_reader_time_to_take_its_workers_with_it():
    """Cancel arrives mid-file, with a pool of forked converters below the
    reader. Killing it outright reparents them onto init, still chewing
    through the file with nobody left to read the answers."""
    proc, cancel = _Reader(), _Cancel()
    rp._stop(proc, cancel, finished=False)
    assert cancel.set_, "the reader was never asked to stop"
    assert proc.waited[0] >= 1, proc.waited


# --------------------------------------------- which interpreter to spawn

def _fake_appimage(tmp_path, monkeypatch, with_interpreter=True):
    """An AppImage's idea of itself: sys.executable is the bundle, not python."""
    appimage = tmp_path / "Serpentine3D.AppImage"
    appimage.write_text("")
    monkeypatch.setenv("APPIMAGE", str(appimage))
    monkeypatch.setattr(sys, "executable", str(appimage))
    monkeypatch.setattr(sys, "_base_executable", str(appimage))
    monkeypatch.setattr(sys, "prefix", str(tmp_path / "mount"))
    monkeypatch.setattr(sys, "base_prefix", str(tmp_path / "mount"))
    if not with_interpreter:
        return None
    real = (tmp_path / "mount" / "bin"
            / f"python{sys.version_info.major}.{sys.version_info.minor}")
    real.parent.mkdir(parents=True)
    real.write_text("")
    real.chmod(0o755)
    return real


def test_a_helper_never_re_runs_the_appimage(tmp_path, monkeypatch):
    """python-appimage points sys.executable at the bundle, so that re-running
    it reproduces the environment. multiprocessing takes that literally: it
    launched the whole app again, one window per worker, and the import waited
    forever on a pipe none of them knew to write to."""
    real = _fake_appimage(tmp_path, monkeypatch)
    assert rp._spawn_executable() == str(real)


def test_the_ordinary_case_spawns_the_interpreter_already_running(monkeypatch):
    """The one running, not the one it was built from. In a virtualenv
    sys._base_executable is the system python, which has none of our
    dependencies and never runs the venv's editable-install hook — pointing
    helpers at it turned every parallel import into a silent serial one."""
    monkeypatch.delenv("APPIMAGE", raising=False)
    assert rp._spawn_executable() == sys.executable


def test_no_interpreter_to_spawn_means_the_serial_path(tmp_path, monkeypatch):
    """Better slow than a screenful of windows and an import that never ends."""
    _fake_appimage(tmp_path, monkeypatch, with_interpreter=False)
    assert rp._spawn_executable() is None

    path = _boxes_3dm(str(tmp_path / "boxes.3dm"), 2)
    monkeypatch.setattr(rhino, "MIN_PARALLEL_BYTES", 0)
    assert not rhino._worth_parallelising(path)


# ------------------------------------------------------- choosing the path

def test_small_files_stay_on_the_serial_path(tmp_path, monkeypatch):
    """Spawning a process costs seconds; most .3dm files do not take that
    long to convert in the first place."""
    path = _boxes_3dm(str(tmp_path / "small.3dm"), 3)
    monkeypatch.setattr(rhino, "import_3dm_parallel",
                        lambda *a, **k: pytest.fail("spawned for a tiny file"))
    assert len(rhino.import_3dm(path)) == 3


def test_one_worker_is_asked_for_when_the_environment_says_so(monkeypatch):
    monkeypatch.setenv("SERP3D_IMPORT_WORKERS", "1")
    assert rp.worker_count() == 1


def test_worker_count_is_at_least_one_and_no_more_than_the_cores(monkeypatch):
    monkeypatch.delenv("SERP3D_IMPORT_WORKERS", raising=False)
    import os
    assert 1 <= rp.worker_count() <= max(1, os.cpu_count() or 1)


def test_worker_count_counts_the_cores_we_may_actually_use(monkeypatch):
    """A container or a taskset can leave us fewer cores than the box has,
    and starting a worker per core we cannot run on only adds contention."""
    monkeypatch.delenv("SERP3D_IMPORT_WORKERS", raising=False)
    monkeypatch.setattr(rp, "_available_cores", lambda: 3)
    assert rp.worker_count() == 3
