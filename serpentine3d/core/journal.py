"""The session journal: what was actually done, written down as it happens.

The command history is an echo for people; this is a recipe for machines.
Every value a command receives — the click already resolved through snaps,
the typed number already parsed, the objects a selection answered with —
is appended to a JSONL file together with the plane and aim it was
resolved against, so that core.replay can re-execute the session headless
and land on the same geometry.

Edits that happen outside any command (a gumball drag, a control point
nudged) are caught by watching the scene while the processor is idle.
Not every idle change is an edit, though: a deferred shape converting on
first read swaps geometry without anyone touching it. The discriminator
is the undo checkpoint — every real edit route checkpoints first, so a
change that arrives without one is bookkeeping and only refreshes the
shadow. A change that arrives with one is written as a delta of exact
BREPs, one delta per checkpoint, so undo peels the same layers on replay
that it peeled live.
"""

from __future__ import annotations

import base64
import functools
import json
import os
import sys
import time

from . import geometry

JOURNAL_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME",
                   os.path.expanduser("~/.local/share")),
    "serpentine3d", "journals")

# A session anybody modelled in is never deleted. Only the litter goes:
# a journal that recorded no work at all, left behind by a crash that
# never reached close(). Anything younger than this may still belong to
# a window that is open right now and has yet to do its first thing.
STUB_GRACE = 86400.0

# a journal bigger than this plainly holds more than a stub, and is
# never opened to find out; the scan only ever spares files
_STUB_MAX_BYTES = 4096

# the events that mean somebody built something: a command they ran, or
# an edit they made by hand outside any command
_WORK = ("cmd", "edit")


def _safe(fn):
    """Losing the recording is a smaller thing than losing the work.

    Everything a journal does runs inside somebody's command or
    somebody's drag, and `flush` is the first thing a command does. A
    throw from here therefore came out of `begin_command` before the
    command had done anything, and the dirty flag survived it, so one
    shape the recorder could not write stopped every command in the
    session from running: delete, hide and move all quietly doing
    nothing, on the whole drawing and not just the shape at fault.

    So a journal that fails stops journalling and says so. It never
    stops the app.
    """
    @functools.wraps(fn)
    def guarded(self, *args, **kwargs):
        if self.broken:
            return None
        try:
            return fn(self, *args, **kwargs)
        except Exception as exc:                           # noqa: BLE001
            self._give_up(exc)
            return None
    return guarded


def _has_work(path: str) -> bool:
    """Did anybody build anything in this session?

    A half-written last line is normal after a crash, and is skipped
    rather than believed; every line before it still counts.
    """
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    if json.loads(line).get("ev") in _WORK:
                        return True
                except ValueError:
                    continue
    except OSError:
        return True                 # unreadable is not the same as empty
    return False


def _b64(shape) -> str:
    return base64.b64encode(geometry.shape_to_bytes(shape)).decode("ascii")


def _cp_dict(cp) -> dict:
    return {"o": [round(float(v), 9) for v in cp.origin],
            "n": [round(float(v), 9) for v in cp.normal],
            "x": [round(float(v), 9) for v in cp.xdir]}


class SessionJournal:
    VERSION = 1

    def __init__(self, path: str):
        self.path = path
        self.broken = False          # gave up recording; the app carries on
        self.failure: Exception | None = None
        self._f = open(path, "a", buffering=1)     # line-buffered: crash-safe
        self.scene = None
        self.history = None
        self.processor = None
        self._shadow: dict = {}
        self._dirty = False
        self._flushing = False
        self._in_command = False
        self._recorded = False       # has anybody built anything yet?
        self._cmd_ids_at_start: set = set()
        self._pending_ckpts: list[str] = []
        self._last_cp = None
        from .. import __version__
        self._write({"ev": "session", "ver": self.VERSION,
                     "app": __version__})

    @classmethod
    def maybe(cls, directory: str):
        """A journal in `directory`, or None if journalling is off.

        Sweeps abandoned stubs on the way in. It used to keep only the
        newest forty and drop the rest, which is how a cache behaves,
        not how a recipe does: a run of short sessions could evict a
        week of real modelling. Nothing with work in it is ever removed
        to make room, at any age or any count.
        """
        if os.environ.get("SERP3D_NO_JOURNAL"):
            return None
        os.makedirs(directory, exist_ok=True)
        cls._sweep_stubs(directory)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return cls(os.path.join(directory, f"{stamp}-{os.getpid()}.jsonl"))

    @staticmethod
    def _sweep_stubs(directory: str):
        cutoff = time.time() - STUB_GRACE
        for name in os.listdir(directory):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(directory, name)
            try:
                st = os.stat(path)
                if st.st_mtime > cutoff or st.st_size > _STUB_MAX_BYTES:
                    continue
                if _has_work(path):
                    continue
                os.unlink(path)
            except OSError:
                pass

    def attach(self, processor, scene, history):
        self.processor = processor
        self.scene = scene
        self.history = history
        processor.journal = self
        scene.add_listener(self._on_scene, ("objects",))
        history.on_checkpoint = self._on_checkpoint
        history.on_discard = self._on_discard
        self._refresh_shadow()

    # -- what the processor reports --

    @_safe
    def begin_command(self, name: str, ctx):
        """A command is starting: flush idle edits, note the ground truth."""
        self.flush()
        # a marker that never found its edit is not coming back: the UI
        # cannot start a command while a drag is still in flight
        self._pending_ckpts.clear()
        self._in_command = True
        self._cmd_ids_at_start = set(self.scene.objects)
        e = {"ev": "cmd", "name": name,
             "sel": [o.id for o in ctx.selection.objects()],
             "sub": [list(s) for s in getattr(ctx.selection,
                                              "subobjects", [])]}
        cp = self._current_cp(ctx)
        if cp is not None:
            e["cp"] = cp
            self._last_cp = cp
        self._write(e)

    @_safe
    def value(self, value, ctx):
        """One resolved answer, with the plane and aim it resolved under."""
        e: dict = {"ev": "val", "v": self._encode(value)}
        if isinstance(value, list):
            # a selection answer carries the sub-objects held alongside it
            # (a control point clicked mid-request never passed through the
            # request, so the ids alone would replay to a different scene)
            sub = [list(s) for s in getattr(ctx.selection, "subobjects", [])]
            if sub:
                e["sub"] = sub
        cp = self._current_cp(ctx)
        if cp is not None and cp != self._last_cp:
            e["cp"] = cp
            self._last_cp = cp
        aim = self._current_aim(ctx)
        if aim is not None:
            e["aim"] = aim
        self._write(e)

    @_safe
    def option(self, name: str, value: str):
        self._write({"ev": "opt", "name": name, "value": value})

    @_safe
    def cancelled(self):
        self._write({"ev": "cancel"})

    @_safe
    def finish(self, success: bool):
        made = [oid for oid in self.scene._order
                if oid not in self._cmd_ids_at_start]
        self._write({"ev": "fin", "ok": bool(success), "made": made})
        self._in_command = False
        self._refresh_shadow()
        self._dirty = False

    # -- what the scene and history report --

    @_safe
    def _on_scene(self):
        if not self._in_command and not self._flushing:
            self._dirty = True

    @_safe
    def _on_checkpoint(self, label: str):
        if self._in_command:
            return                       # the command's own; fin covers it
        self.flush()                     # what came before belongs before
        self._pending_ckpts.append(label)

    @_safe
    def _on_discard(self):
        if self._in_command:
            return
        if self._pending_ckpts:
            self._pending_ckpts.pop()    # a drag that went back to zero

    @_safe
    def note_load(self, path: str):
        """A file was opened outside any command (menu, welcome screen).

        Recorded as one named event instead of a BREP dump of everything
        the file held; replay re-imports the file itself.
        """
        if self._pending_ckpts:
            self._pending_ckpts.pop()    # the open's own checkpoint
        made = [oid for oid in self.scene._order if oid not in self._shadow]
        self._write({"ev": "load", "path": path, "made": made})
        self._refresh_shadow()
        self._dirty = False

    @_safe
    def flush(self):
        """Write the settled idle delta, if there is one.

        Called when a command starts, when a new checkpoint arrives, on a
        UI quiet-period timer, and on close — never per mouse move, so a
        drag lands as one delta, not four hundred.
        """
        if self._flushing or not self._dirty:
            return
        self._flushing = True
        try:
            made, chg, gone = self._delta()
            if not (made or chg or gone):
                # conversions only. The markers stay: a drag that has
                # not moved yet still owns its checkpoint.
                self._refresh_shadow()
                self._dirty = False
                return
            for label in self._pending_ckpts:
                self._write({"ev": "ckpt", "label": label})
            self._pending_ckpts.clear()
            self._write({"ev": "edit", "made": made, "chg": chg,
                         "gone": gone})
            self._refresh_shadow()
            self._dirty = False
        finally:
            self._flushing = False

    @_safe
    def write_fingerprint(self):
        """A checkable summary of the scene, for replay verification."""
        self.flush()
        objs = []
        for o in self.scene.all():
            try:
                size = (geometry.volume(o.shape) if o.kind == "solid"
                        else geometry.curve_length(o.shape)
                        if o.kind == "curve" else 0.0)
            except Exception:                              # noqa: BLE001
                size = 0.0
            try:
                mn, mx = o.bbox()
            except Exception:                              # noqa: BLE001
                mn = mx = (0.0, 0.0, 0.0)
            objs.append({"id": o.id, "kind": o.kind,
                         "size": round(float(size), 6),
                         "bb": [round(float(v), 6) for v in (*mn, *mx)]})
        self._write({"ev": "fp", "objects": objs})

    @_safe
    def close(self):
        """Close the file, and take it away if it recorded nothing.

        Opening the app, looking at it and closing it again should not
        leave anything behind for the next launch to sweep up.
        """
        if self._f.closed:
            return
        self.flush()                 # a settled drag still counts as work
        self._shutdown()

    def _give_up(self, exc: Exception):
        """Stop recording, keep what was recorded, say so once.

        The rest of the session is not journalled: a recording with a
        hole in it would replay into the wrong model, and quietly
        wrong is the one thing this file may never be. The marker goes
        in so `replay --check` can name the moment it stopped.
        """
        self.broken = True
        self.failure = exc
        try:
            if not self._f.closed:
                self._write({"ev": "broken", "why": f"{type(exc).__name__}: "
                                                    f"{exc}"})
            self._shutdown()
        except Exception:                                  # noqa: BLE001
            pass
        print(f"serpentine3d: journalling stopped, {type(exc).__name__}: "
              f"{exc}", file=sys.stderr)

    def _shutdown(self):
        if self._f.closed:
            return
        self._f.close()
        if not self._recorded:
            try:
                os.unlink(self.path)
            except OSError:
                pass

    # -- internals --

    def _delta(self):
        """What changed since the shadow, conversions filtered out.

        The shadow holds the very _shape object each id had, so it knows
        exactly which changes are a DeferredShape realising — geometry
        swapped by bookkeeping, not by anybody's hand — and those are
        never edits. It used to be inferred from the undo checkpoint,
        and a drag held still past the flush timer had already spent
        its checkpoint, so the movement after the pause was swallowed
        and the replay put the object wherever the timer had caught it.
        """
        from .deferred import DeferredShape
        made, chg, gone = [], [], []
        realised = False
        for oid in self.scene._order:
            obj = self.scene.objects[oid]
            if oid not in self._shadow:
                # an object that is itself still a promise was put there
                # by a load, not a hand; note_load covers those
                if not isinstance(obj._shape, DeferredShape):
                    made.append([oid, obj.name, _b64(obj.shape)])
            elif obj._shape is not self._shadow[oid]:
                if isinstance(self._shadow[oid], DeferredShape):
                    realised = True
                else:
                    chg.append([oid, _b64(obj.shape)])
        for oid in self._shadow:
            if oid not in self.scene.objects:
                if isinstance(self._shadow[oid], DeferredShape):
                    realised = True     # converted to nothing, removed
                else:
                    gone.append(oid)
        if realised and not self._pending_ckpts:
            # realise can add siblings (one shape converting to two);
            # with no drag in flight, whatever appeared came from it
            made = []
        return made, chg, gone

    def _refresh_shadow(self):
        self._shadow = {oid: self.scene.objects[oid]._shape
                        for oid in self.scene._order}

    @staticmethod
    def _encode(value):
        if value is None:
            return None
        if isinstance(value, str):
            return {"s": value}
        if isinstance(value, (int, float)):
            return {"n": float(value)}
        if isinstance(value, (list,)):
            return {"ids": [o if isinstance(o, str) else o.id
                            for o in value]}
        return {"p": [float(c) for c in value][:3]}

    @staticmethod
    def _current_cp(ctx):
        try:
            return _cp_dict(ctx.cplane)
        except Exception:                                  # noqa: BLE001
            return None

    @staticmethod
    def _current_aim(ctx):
        """The (base, direction) pair a typed number would run along."""
        try:
            aim = ctx.aim_direction()
        except Exception:                                  # noqa: BLE001
            return None
        if aim is None:
            return None
        base, d = aim
        return [[round(float(v), 9) for v in base],
                [round(float(v), 9) for v in d]]

    def _write(self, event: dict):
        # one choke point, so the flag can never disagree with the file
        if event["ev"] in _WORK:
            self._recorded = True
        event["t"] = round(time.time(), 3)
        self._f.write(json.dumps(event) + "\n")
