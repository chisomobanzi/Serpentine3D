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
