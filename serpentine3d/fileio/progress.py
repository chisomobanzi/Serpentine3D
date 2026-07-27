"""Progress reporting and cancellation for long imports.

A set-design .3dm can take minutes, and until it finished the app looked hung
with no way out but killing it. Importers therefore take a reporter and call
it as they go; the caller decides what to draw and when to stop.
"""

import time


def throttled(callback, interval: float = 0.05, clock=time.monotonic):
    """A progress callback that fires at most once every `interval` seconds.

    Importers report per face, which on a 7921-face polysurface means the
    repainting would cost more than the conversion. The first update always
    lands, so a dialog appears straight away, and so does completion, so the
    bar doesn't stop short. Skipped updates answer None rather than False —
    not asking the user is not the same as being told to stop.
    """
    last = [None]

    def tick(fraction: float, message: str = ""):
        now = clock()
        if last[0] is not None and fraction < 1.0 \
                and now - last[0] < interval:
            return None
        last[0] = now
        return callback(fraction, message)

    return tick


class Cancelled(Exception):
    """The progress callback asked for the work to stop."""


class Progress:
    """A progress callback plus the arithmetic importers would otherwise
    repeat.

    Importers count in their own units — objects, faces — while the caller
    wants one fraction and a sentence, so `part` maps a nested job's own 0..1
    onto a slice of its parent's. A callback answering False cancels, and that
    becomes an exception rather than a return value an importer could quietly
    ignore mid-loop. Any other answer (including None, which is what a
    recording lambda returns) means carry on.

    A reporter with no callback is inert, so importers need no None checks.
    """

    def __init__(self, callback=None, label: str = "",
                 lo: float = 0.0, hi: float = 1.0):
        self._callback = callback
        self.label = label
        self._lo = lo
        self._hi = hi

    def __call__(self, fraction: float = 0.0, message: str = "") -> None:
        if self._callback is None:
            return
        f = min(max(fraction, 0.0), 1.0)
        overall = self._lo + (self._hi - self._lo) * f
        if self._callback(overall, message or self.label) is False:
            raise Cancelled(message or self.label)

    def done(self, message: str = "") -> None:
        """Report completion, ignoring a stop answer. The work is already
        finished; throwing it away because Cancel was clicked on the last
        object would be worse than letting the click go unanswered."""
        if self._callback is not None:
            self._callback(self._hi, message or self.label)

    def part(self, lo: float, hi: float, label: str = "") -> "Progress":
        """A reporter whose own 0..1 covers [lo, hi] of this one."""
        span = self._hi - self._lo
        return Progress(self._callback, label or self.label,
                        self._lo + span * lo, self._lo + span * hi)
