"""Converting a .3dm across several processes (GitHub #3).

A 65259-object file took about fifteen minutes to open on a 22-core machine,
and the machine was almost idle throughout. The cost is not our arithmetic and
not OpenCASCADE: it is rhino3dm's Python binding, where reading one float off
a point costs 11 us and reaching one mesh vertex costs 25 us — against 0.25 us
for a plain attribute and 1.67 us for the equivalent OCCT call. A survey mesh
has millions of vertices, so mesh reading alone is 90% of an import.

That work is Python-side, so it holds the GIL and threads cannot touch it.
Processes can: objects convert independently. Three things make the difference
between a fix and a disappointment, all of them measured:

  * **Fork, don't re-read.** A worker that opens the file itself pays ten
    seconds and a private copy of the model. Forked workers inherit the
    parent's copy-on-write instead — sixteen of them peaked at 0.32 GB each
    against a 0.47 GB parent.

  * **Interleave, don't slice.** A drawing keeps its meshes together, so
    handing each worker a contiguous block of the file gives one of them every
    expensive object: 6.5x collapsed to 1.5x until the batches were strided.

  * **Spawn the reader.** The app cannot fork: its tessellation threads hold
    locks a forked child would inherit already locked and wait on forever. So
    one thread-free process is spawned, and *it* reads the file and forks the
    converters.

Shapes come back down a pipe. A MeshShape is numpy and pickles as it stands;
a TopoDS_Shape does not pickle at all — it aborts the interpreter — so it
travels as a BinTools archive, about 6 KB and half a millisecond each.

On a 10474-object file this took conversion from 86 s to 8 s.
"""

from __future__ import annotations

import io
import math
import multiprocessing as mp
import os
import traceback

import rhino3dm as r3

from ..core.mesh import MeshShape
from .progress import Progress

# Set once in the reader process; forked converters inherit it, and on
# platforms without fork each fills it in for itself.
_MODEL = None

# Spawning a process and importing the kernel into it costs a couple of
# seconds, which most .3dm files do not take to convert in the first place.
MIN_PARALLEL_BYTES = 8 * 1024 * 1024

# Objects per task. Small enough that progress moves and the pool can even
# out a straggler, large enough that the per-task overhead disappears.
BATCH = 64

# Past about sixteen the pipe, not the conversion, is the limit.
MAX_WORKERS = 16

# Without fork every worker holds its own copy of the model, so the ceiling
# is memory rather than cores.
MAX_WORKERS_WITHOUT_FORK = 4


def _available_cores() -> int:
    """Cores this process may actually run on, not the ones the box has.

    A container, a cgroup or a taskset can leave us with fewer, and a worker
    per core we cannot be scheduled on only adds contention.
    """
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:                          # not Linux
        return os.cpu_count() or 1


def worker_count(requested: int | None = None) -> int:
    """How many converters to run. SERP3D_IMPORT_WORKERS=1 forces serial."""
    if requested is None:
        requested = os.environ.get("SERP3D_IMPORT_WORKERS")
    if requested:
        try:
            return max(1, int(requested))
        except (TypeError, ValueError):
            pass
    cap = MAX_WORKERS if hasattr(os, "fork") else MAX_WORKERS_WITHOUT_FORK
    return max(1, min(cap, _available_cores()))


def _batches(total: int, size: int = BATCH) -> list[list[int]]:
    """Object indices in `total // size` interleaved batches.

    Strided rather than sliced: batch k is every count'th object, so each one
    samples the whole drawing and no single batch inherits the region where
    the scanned meshes live.
    """
    if total <= 0:
        return []
    count = max(1, math.ceil(total / size))
    return [list(range(k, total, count)) for k in range(count)]


# ---------------------------------------------------------- down the pipe

def _downcasts() -> dict:
    """{shape type: core.occ downcast function name}. Built once, lazily,
    so importing this module does not drag the kernel in."""
    from ..core import occ
    return {occ.VERTEX: "to_vertex", occ.EDGE: "to_edge", occ.WIRE: "to_wire",
            occ.FACE: "to_face", occ.SHELL: "to_shell",
            occ.SOLID: "to_solid", occ.COMPOUND: "to_compound"}


_DOWNCAST = None


def _encode(shape):
    """A shape as something pickle can carry."""
    if isinstance(shape, MeshShape):
        return ("mesh", shape.vertices, shape.triangles)
    from OCP.BinTools import BinTools
    buf = io.BytesIO()
    BinTools.Write_s(shape, buf)
    return ("occ", buf.getvalue(), None)


def _decode(payload):
    kind, first, second = payload
    if kind == "mesh":
        return MeshShape(first, second)
    from OCP.BinTools import BinTools
    from OCP.TopoDS import TopoDS_Shape
    shape = TopoDS_Shape()
    BinTools.Read_s(shape, io.BytesIO(first))
    # BinTools answers a bare TopoDS_Shape whatever it was handed, and OCCT's
    # bindings reject one where they want a TopoDS_Edge. Put the class back,
    # so nothing downstream can tell which process built the object.
    global _DOWNCAST
    if _DOWNCAST is None:
        _DOWNCAST = _downcasts()
    cast = _DOWNCAST.get(shape.ShapeType())
    if cast is None:
        return shape
    from ..core import occ
    return getattr(occ, cast)(shape)


# -------------------------------------------------------------- converting

def _init_worker(path: str):
    """Fill in the model only where fork did not hand one over."""
    global _MODEL
    if _MODEL is None:
        _MODEL = r3.File3dm.Read(path)


def _convert(indices: list[int]):
    """[(index, name, layer index, [encoded shape])] for one batch."""
    from . import rhino

    out = []
    for i in indices:
        obj = _MODEL.Objects[i]
        try:
            shapes = rhino.object_to_shapes(obj.Geometry)
        except Exception:                                       # noqa: BLE001
            shapes = []
        encoded = [_encode(s) for s in shapes
                   if s is not None and not s.IsNull()]
        attrs = obj.Attributes
        out.append((i, attrs.Name or "", attrs.LayerIndex, encoded))
    return out


def _convert_in_pool(path: str, workers: int, cancel=None):
    """Read the file, convert it across `workers` processes, yield as it goes.

    Messages are ("status", fraction, text), ("layers", dict), ("total", n)
    and ("batch", done, total, results). Runs in the spawned reader process,
    but is a plain generator so it can also be driven in-process.
    """
    global _MODEL

    yield ("status", 0.0, f"Reading {os.path.basename(path)}…")
    _MODEL = r3.File3dm.Read(path)
    if _MODEL is None:
        raise IOError(f"Could not read 3dm file: {path}")

    from . import rhino
    yield ("layers", rhino.read_layers(_MODEL))

    total = len(_MODEL.Objects)
    yield ("total", total)
    batches = _batches(total)
    if not batches:
        return

    ctx = mp.get_context("fork" if hasattr(os, "fork") else "spawn")
    done = 0
    with ctx.Pool(min(workers, len(batches)),
                  initializer=_init_worker, initargs=(path,)) as pool:
        for results in pool.imap_unordered(_convert, batches):
            if cancel is not None and cancel.is_set():
                pool.terminate()
                return
            done += len(results)
            yield ("batch", done, total, results)


def _read_file(path: str, workers: int, conn, cancel):
    """The spawned reader: forward the conversion down the pipe.

    Errors travel too. A file that will not open has to raise in the caller,
    not come back as an import that found nothing.
    """
    stream = _convert_in_pool(path, workers, cancel)
    try:
        for message in stream:
            conn.send(message)
    except BaseException as exc:                                # noqa: BLE001
        report = traceback.format_exc()
        try:
            conn.send(("error", exc, report))
        except Exception:                                       # noqa: BLE001
            conn.send(("error", None, report))                  # unpicklable
    finally:
        stream.close()          # unwinds the `with`, so the pool is stopped
        conn.close()


# ---------------------------------------------------------------- assembly

def _messages(conn):
    while True:
        try:
            yield conn.recv()
        except EOFError:
            return


def _assemble(messages, report) -> list[tuple[str, object, dict]]:
    """Turn the reader's message stream into what import_3dm returns.

    Shapes are decoded as they land rather than at the end, so the bytes are
    freed while the workers are still busy and the parent is not left holding
    the whole file twice over.
    """
    layers, total, rows = {}, 1, []
    for message in messages:
        kind = message[0]
        if kind == "batch":
            _, done, total, results = message
            rows.extend((index, name, layer,
                         [_decode(payload) for payload in encoded])
                        for index, name, layer, encoded in results)
            report(done / (total or 1),
                   f"Converting object {done} of {total}")
        elif kind == "status":
            report(message[1], message[2])
        elif kind == "layers":
            layers = message[1]
        elif kind == "total":
            total = message[1] or 1
        elif kind == "error":
            exc, text = message[1], message[2]
            raise exc if isinstance(exc, BaseException) else RuntimeError(text)

    # Batches finish out of order; the scene should not depend on which
    # worker was quickest, and the fallback names count in file order.
    rows.sort(key=lambda row: row[0])
    out, counter = [], 0
    for _, name, layer, shapes in rows:
        for shape in shapes:
            counter += 1
            out.append((name or f"3dm object {counter:02d}",
                        shape, layers.get(layer, {})))
    return out


def import_3dm_parallel(path: str, progress=None,
                        workers: int | None = None
                        ) -> list[tuple[str, object, dict]]:
    """import_3dm's answer, converted across processes.

    The reader is spawned rather than forked because the caller is a running
    Qt app whose tessellation threads hold locks a forked child would inherit
    held. The reader has no threads, so it can fork its own converters.
    """
    report = progress or Progress()
    ctx = mp.get_context("spawn")
    cancel = ctx.Event()
    receiver, sender = ctx.Pipe(duplex=False)
    # Not daemonic: a daemon may not have children, and the reader's whole
    # job is to fork some. The `finally` below stops it instead, and if the
    # app dies outright the pipe breaks under the reader's next send.
    proc = ctx.Process(target=_read_file,
                       args=(path, worker_count(workers), sender, cancel))
    proc.start()
    sender.close()          # or the parent never sees the pipe close
    try:
        return _assemble(_messages(receiver), report)
    finally:
        # Ask first: a reader killed outright leaves its forked converters
        # orphaned and still chewing through the file.
        cancel.set()
        proc.join(timeout=2)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)
        receiver.close()
