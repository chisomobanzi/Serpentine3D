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

  * **Share out the one object nobody else can help with.** Sharing objects
    out means a drawing converts no faster than its dearest single object. A
    survey file ends in two meshes of 6.6 million vertices, fifty seconds
    each, and the last fifty-eight seconds of a seventy-four second import
    were fifteen workers watching one read a mesh. Past SPLIT_VERTICES a mesh
    is read in vertex ranges by the whole pool instead: 74 s to 32 s, and the
    object itself 59.5 s to 6.2 s.

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
import sys
import traceback

import numpy as np
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

# Vertices past which one mesh is read by several workers instead of one.
# Objects are shared out, so a drawing converts as fast as its dearest single
# object: the cave file's last two are 6.6 million vertices each, fifty
# seconds apiece, and for those fifty seconds fifteen of the sixteen workers
# had nothing to do and the bar sat at 93%. Below the threshold the round trip
# through the pool costs more than the reading.
SPLIT_VERTICES = 200_000


def _available_cores() -> int:
    """Cores this process may actually run on, not the ones the box has.

    A container, a cgroup or a taskset can leave us with fewer, and a worker
    per core we cannot be scheduled on only adds contention.
    """
    try:
        return len(os.sched_getaffinity(0))
    except AttributeError:                          # not Linux
        return os.cpu_count() or 1


def _spawn_executable() -> str | None:
    """The interpreter a spawned helper should run, or None if there isn't one.

    Inside an AppImage `sys.executable` is the AppImage, not python:
    python-appimage sets it that way so re-running it reproduces the whole
    environment. multiprocessing takes it at face value and starts the child
    as `TheApp.AppImage -c "...spawn_main()..."`, which the AppImage's launcher
    hands to the app as arguments — so every worker opened another window,
    none of them ran the helper, and the import waited on a pipe forever.

    Naming the real interpreter fixes it. If it cannot be found we say so
    rather than guess, and the caller stays on the single-process path.

    Everywhere else the answer is the interpreter already running — not
    sys._base_executable, which in a virtualenv is the system python: it has
    none of our dependencies and never runs the venv's editable-install hook,
    so helpers died on import and every parallel import quietly became a
    serial one.
    """
    exe = sys.executable
    bundle = os.environ.get("APPIMAGE")
    if not bundle or os.path.realpath(exe) != os.path.realpath(bundle):
        return exe

    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    for prefix in (sys.prefix, sys.base_prefix):
        candidate = os.path.join(prefix, "bin", version)
        if os.access(candidate, os.X_OK):
            return candidate
    return None


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


def split_vertices(requested: int | None = None) -> int:
    """Vertices past which a mesh is worth more than one worker.

    SERP3D_IMPORT_SPLIT_VERTICES overrides it. The reader is a process of its
    own, so that is also how a test says so.
    """
    if requested is None:
        requested = os.environ.get("SERP3D_IMPORT_SPLIT_VERTICES")
    if requested:
        try:
            return max(1, int(requested))
        except (TypeError, ValueError):
            pass
    return SPLIT_VERTICES


def _piece_count(vertices: int, workers: int, limit: int) -> int:
    """How many pieces one mesh is worth.

    A piece of `limit` vertices, rather than one worker's share of the mesh:
    more pieces than workers pack the pool tighter when several meshes are
    split at once, and each one is a line on the dialog, so the sentence
    changes every second or two instead of once a wave. The ceiling is there
    to stop a preposterous mesh from becoming thousands of round trips.
    """
    if limit <= 0 or vertices <= limit:
        return 1
    return max(2, min(4 * workers, math.ceil(vertices / limit)))


def _pieces(count: int, parts: int) -> list[tuple[int, int]]:
    """`count` items as exactly `parts` contiguous [lo, hi) ranges.

    Contiguous, unlike the batches: the pieces are concatenated back together
    in order, and a face indexes its vertices by position. Exactly `parts` of
    them, empty ones included, so a mesh's vertex ranges and its face ranges
    pair off even when it has fewer faces than there are workers.
    """
    parts = max(1, parts)
    edges = [count * k // parts for k in range(parts + 1)]
    return list(zip(edges[:-1], edges[1:]))


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
        return ("mesh", shape.vertices, shape.triangles, shape.normals)
    from OCP.BinTools import BinTools
    buf = io.BytesIO()
    BinTools.Write_s(shape, buf)
    return ("occ", buf.getvalue(), None, None)


def _decode(payload):
    kind, first, second, third = payload
    if kind == "mesh":
        return MeshShape(first, second, third)
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
    """[(index, name, layer index, [encoded shape], size)] for one batch.

    A mesh too big for one worker is not converted here. Its vertex and face
    counts come back instead, as `size`, and the reader shares the reading of
    it out; everything else answers with `size` None and its shapes.
    """
    from . import rhino

    limit = split_vertices()
    out = []
    for i in indices:
        obj = _MODEL.Objects[i]
        geo = obj.Geometry
        attrs = obj.Attributes
        if isinstance(geo, r3.Mesh) and len(geo.Vertices) > limit:
            out.append((i, attrs.Name or "", attrs.LayerIndex, [],
                        (len(geo.Vertices), len(geo.Faces))))
            continue
        try:
            shapes = rhino.object_to_shapes(geo)
        except Exception:                                       # noqa: BLE001
            shapes = []
        encoded = [_encode(s) for s in shapes
                   if s is not None and not s.IsNull()]
        out.append((i, attrs.Name or "", attrs.LayerIndex, encoded, None))
    return out


def _read_piece(job):
    """One slice of one mesh: (object index, piece number, vertices, tris).

    Indexed, not iterated, because a worker starting part way in has no
    cheaper way to get there: skipping to the middle with islice costs nearly
    half what reading it does. Index once per vertex and read the three
    coordinates off what comes back — `vl[i].X, vl[i].Y, vl[i].Z` builds three
    points and costs twice as much as building one.
    """
    index, part, vlo, vhi, flo, fhi = job
    mesh = _MODEL.Objects[index].Geometry
    vl = mesh.Vertices
    rows = []
    for i in range(vlo, vhi):
        v = vl[i]
        rows.append((v.X, v.Y, v.Z))
    fl = mesh.Faces
    tris = []
    for i in range(flo, fhi):
        a, b, c, d = fl[i]
        tris.append((a, b, c))
        if d != c:
            tris.append((a, c, d))
    return (index, part,
            np.array(rows, float).reshape(-1, 3),
            np.array(tris, np.uint32).reshape(-1, 3))


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
    deferred = {}
    with ctx.Pool(min(workers, len(batches)),
                  initializer=_init_worker, initargs=(path,)) as pool:
        for results in pool.imap_unordered(_convert, batches):
            if cancel is not None and cancel.is_set():
                pool.terminate()
                return
            rows = []
            for index, name, layer, encoded, size in results:
                if size is None:
                    rows.append((index, name, layer, encoded))
                else:
                    deferred[index] = (name, layer, size)
            done += len(rows)
            yield ("batch", done, total, rows)
        if deferred:
            yield from _share_out(pool, deferred, done, total, workers, cancel)


def _share_out(pool, deferred, done, total, workers, cancel):
    """Read the objects too big for one worker across the whole pool.

    They are left till last because nothing knows an object's size until a
    worker has looked at it, and asking beforehand means the reader walking
    the file alone. By the time they come round the pool is otherwise idle,
    so the pieces of every deferred mesh go in together and the last object
    finishes in about the time one worker would have needed for a sixteenth
    of it.
    """
    limit = split_vertices()
    jobs, held = [], {}
    for index, (_, _, (vertices, faces)) in deferred.items():
        parts = _piece_count(vertices, workers, limit)
        spans = zip(_pieces(vertices, parts), _pieces(faces, parts))
        held[index] = [None] * parts
        for part, ((vlo, vhi), (flo, fhi)) in enumerate(spans):
            jobs.append((index, part, vlo, vhi, flo, fhi))

    # The object count cannot move while a single object is in hand, so the
    # pieces report instead — a bar that stops is a bar that has hung.
    lo, span = done / (total or 1), len(deferred) / (total or 1)
    for k, (index, part, verts, tris) in enumerate(
            pool.imap_unordered(_read_piece, jobs), 1):
        if cancel is not None and cancel.is_set():
            pool.terminate()
            return
        pieces = held[index]
        pieces[part] = (verts, tris)
        yield ("status", lo + span * k / len(jobs),
               f"Reading a large mesh, {k} of {len(jobs)} pieces")
        if all(piece is not None for piece in pieces):
            shape = MeshShape(
                np.concatenate([piece[0] for piece in pieces]),
                np.concatenate([piece[1] for piece in pieces]))
            del held[index]
            name, layer, _ = deferred[index]
            done += 1
            yield ("batch", done, total,
                   [(index, name, layer, [_encode(shape)])])


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

def _messages(conn, interval: float = 0.05):
    """The reader's messages, with a heartbeat while it has nothing to say.

    The caller drives this from its UI thread, so a plain blocking recv()
    froze the window and deafened Cancel for as long as a batch took. On the
    file that started all this that was the whole import: a dialog that never
    painted, then a bar that stopped at 98% with no way out.
    """
    while True:
        if not conn.poll(interval):
            yield ("waiting",)
            continue
        try:
            yield conn.recv()
        except EOFError:
            return


def _assemble(messages, report, opening: str = "") -> list[tuple[str, object,
                                                                dict]]:
    """Turn the reader's message stream into what import_3dm returns.

    Shapes are decoded as they land rather than at the end, so the bytes are
    freed while the workers are still busy and the parent is not left holding
    the whole file twice over.
    """
    layers, total, rows = {}, None, []
    # What to repaint between messages. The bar must not creep while the
    # helper is thinking, so a heartbeat repeats the last real update rather
    # than inventing one.
    # The helper takes a moment to start, and a dialog with no words in it
    # reads as a hang. We know the filename without asking it.
    latest = (0.0, opening)
    for message in messages:
        kind = message[0]
        if kind == "batch":
            _, done, total, results = message
            rows.extend((index, name, layer,
                         [_decode(payload) for payload in encoded])
                        for index, name, layer, encoded in results)
            latest = (done / (total or 1),
                      f"Converting object {done} of {total}")
            report(*latest)
        elif kind == "waiting":
            report(*latest)
        elif kind == "status":
            latest = (message[1], message[2])
            report(*latest)
        elif kind == "layers":
            layers = message[1]
        elif kind == "total":
            total = message[1]
        elif kind == "error":
            exc, text = message[1], message[2]
            raise exc if isinstance(exc, BaseException) else RuntimeError(text)

    # A reader can die before it can say why — a bundle whose spawned
    # interpreter cannot find the kernel, an OOM kill. The pipe simply closes,
    # and an import of nothing is indistinguishable from a file of nothing.
    # Counting the objects is the reader's first act after opening the file,
    # so having no count at all means it never got that far.
    if total is None:
        raise RuntimeError("the import helper stopped before reading the file")

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
    interpreter = _spawn_executable()
    if interpreter is None:
        raise RuntimeError("no interpreter to run the import helper")
    ctx.set_executable(interpreter)
    cancel = ctx.Event()
    receiver, sender = ctx.Pipe(duplex=False)
    # Not daemonic: a daemon may not have children, and the reader's whole
    # job is to fork some. The `finally` below stops it instead, and if the
    # app dies outright the pipe breaks under the reader's next send.
    proc = ctx.Process(target=_read_file,
                       args=(path, worker_count(workers), sender, cancel))
    proc.start()
    sender.close()          # or the parent never sees the pipe close
    finished = False
    try:
        # _assemble returns only once the message stream ends, which is the
        # reader closing the pipe — so a normal return means it got to the end.
        items = _assemble(_messages(receiver), report,
                          f"Reading {os.path.basename(path)}…")
        finished = True
        return items
    finally:
        _stop(proc, cancel, finished)
        receiver.close()


def _stop(proc, cancel, finished: bool) -> None:
    """Let the reader go.

    Closing the pipe is its last act after stopping its pool, so a reader that
    got that far has nothing of ours left running in it — only a spawned
    interpreter unloading OCP and rhino3dm, which takes about two seconds. We
    used to spend them inside a join, and a join reports nothing, so the bar
    sat frozen at 95% with every object already converted. Nobody is waiting
    on that exit, so we stop watching it.

    Bailing out is the opposite. The reader is mid-file with a pool of forked
    converters below it, and killing it there reparents them onto init, still
    chewing through the file with nobody left to read their answers. So it is
    asked to stop and given time to take its children with it.
    """
    cancel.set()
    proc.join(timeout=0.2 if finished else 2)
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=5)
