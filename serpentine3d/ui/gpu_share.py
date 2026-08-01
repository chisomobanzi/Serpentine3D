"""One upload of a mesh's vertex data for the whole application.

A viewport used to own its buffers, so opening a second view of the same
model uploaded the same vertices again — on the cave file about 676 MB a
view, which made the four-viewport layout nearly double resident memory.

OpenGL buffers are shared between contexts in a share group, so they are
uploaded once and handed to every viewport that draws the mesh. Vertex array
objects are *not* shareable and stay per viewport; they are container state,
and cost nothing worth counting.

Keys are whatever identifies "the same buffers": in practice a mesh uid and
the linetype its dashes were built for. Entries are reference counted, since
the last viewport to stop drawing a mesh is the one that must free it, and
which viewport that is depends on the order the user closes things.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass
class _Entry:
    buffers: Any
    refs: int = 0


_SHARED: dict[Any, _Entry] = {}


def acquire(key: Any, build: Callable[[], Any]) -> Any:
    """The buffers for `key`, built by `build` the first time they are asked
    for. Every caller must pair this with exactly one `release`."""
    entry = _SHARED.get(key)
    if entry is None:
        # Built before the entry is recorded: an upload that raises leaves
        # nothing behind, rather than an empty entry every later acquire
        # would hand out as if it were real.
        entry = _Entry(build())
        _SHARED[key] = entry
    entry.refs += 1
    return entry.buffers


def release(key: Any) -> None:
    """Give up one claim on `key`, freeing the buffers with the last one.

    Quiet about a key it does not know: a viewport tearing down after the
    registry was cleared has nothing useful to say about it."""
    entry = _SHARED.get(key)
    if entry is None:
        return
    entry.refs -= 1
    if entry.refs <= 0:
        del _SHARED[key]
        entry.buffers.release()


def count() -> int:
    """Distinct meshes currently uploaded — the number that should stay flat
    as viewports are added."""
    return len(_SHARED)


def total_bytes() -> int:
    """Vertex data on the GPU, counting each mesh once however many viewports
    draw it. The honest measure of what a layout costs: resident memory moves
    for too many other reasons to read a buffer figure off it."""
    return sum(getattr(e.buffers, "nbytes", 0) for e in _SHARED.values())


def reset() -> None:
    """Drop every entry without freeing. For tests only: releasing GL
    handles needs the context that made them, which a test does not have."""
    _SHARED.clear()
