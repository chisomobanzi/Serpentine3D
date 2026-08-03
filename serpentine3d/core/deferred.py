"""Geometry that has been read from a file but not converted yet.

A working drawing is mostly switched off. The survey layers, the
consultant's model, the setting-out grid: all in the file, none of it on
screen, and until now all of it converted into OCC geometry at open time
whether or not anything would ever look at it. On a 61 MB survey file the
hidden objects are 3% of the count and 24% of the import, because what
people switch off is the heavy reference geometry (GitHub #5).

A `DeferredShape` stands in the object's place holding two things: the
kind the file claimed, so the scene can count and name it, and a callable
that will do the conversion. Nothing here decides when to call it; the
scene does, and only when something asks.
"""

from __future__ import annotations

import threading


class DeferredShape:
    """A stand-in for geometry that has not been converted yet.

    `build` returns the list of shapes the object converts to, which is
    usually one, occasionally two (a sewn brep and a mesh fallback beside
    it) and quite often none at all. `Scene.realise` is what deals with
    each of those; this only promises to do the work once.
    """

    __slots__ = ("_build", "_shapes", "_lock", "kind")

    def __init__(self, build, kind: str = "solid"):
        self._build = build
        self._shapes: list | None = None
        self._lock = threading.Lock()
        self.kind = kind

    @property
    def ready(self) -> bool:
        """Whether the conversion has already happened."""
        return self._shapes is not None

    def shapes(self) -> list:
        """Convert, or hand back what an earlier call converted.

        Locked because a clone in an undo snapshot shares this object, and
        because tessellation runs on worker threads: two of them arriving
        together should wait for one conversion rather than each doing it.
        """
        if self._shapes is not None:
            return self._shapes
        with self._lock:
            if self._shapes is None:
                shapes = self._build() or []
                self._shapes = [s for s in shapes if s is not None]
                self._build = None      # let the file geometry go
        return self._shapes
