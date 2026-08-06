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
import json
import os
import time

from . import geometry

JOURNAL_DIR = os.path.join(
    os.environ.get("XDG_DATA_HOME",
                   os.path.expanduser("~/.local/share")),
    "serpentine3d", "journals")

# sessions to keep; older recipes age out the way autosaves do
KEEP_JOURNALS = 40


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
        self._f = open(path, "a", buffering=1)     # line-buffered: crash-safe
        self.scene = None
        self.history = None
        self.processor = None
        self._shadow: dict = {}
        self._dirty = False
        self._flushing = False
        self._in_command = False
        self._cmd_ids_at_start: set = set()
        self._pending_ckpts: list[str] = []
        self._last_cp = None
        from .. import __version__
        self._write({"ev": "session", "ver": self.VERSION,
                     "app": __version__})

    @classmethod
    def maybe(cls, directory: str):
        """A journal in `directory`, or None if journalling is off."""
        if os.environ.get("SERP3D_NO_JOURNAL"):
            return None
        os.makedirs(directory, exist_ok=True)
        old = sorted(f for f in os.listdir(directory)
                     if f.endswith(".jsonl"))
        for name in old[:-KEEP_JOURNALS]:
            try:
                os.unlink(os.path.join(directory, name))
            except OSError:
                pass
        stamp = time.strftime("%Y%m%d-%H%M%S")
        return cls(os.path.join(directory, f"{stamp}-{os.getpid()}.jsonl"))

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

    def begin_command(self, name: str, ctx):
        """A command is starting: flush idle edits, note the ground truth."""
        self.flush()
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

    def value(self, value, ctx):
        """One resolved answer, with the plane and aim it resolved under."""
        e: dict = {"ev": "val", "v": self._encode(value)}
        cp = self._current_cp(ctx)
        if cp is not None and cp != self._last_cp:
            e["cp"] = cp
            self._last_cp = cp
        aim = self._current_aim(ctx)
        if aim is not None:
            e["aim"] = aim
        self._write(e)

    def option(self, name: str, value: str):
        self._write({"ev": "opt", "name": name, "value": value})

    def cancelled(self):
        self._write({"ev": "cancel"})

    def finish(self, success: bool):
        made = [oid for oid in self.scene._order
                if oid not in self._cmd_ids_at_start]
        self._write({"ev": "fin", "ok": bool(success), "made": made})
        self._in_command = False
        self._refresh_shadow()
        self._dirty = False

    # -- what the scene and history report --

    def _on_scene(self):
        if not self._in_command and not self._flushing:
            self._dirty = True

    def _on_checkpoint(self, label: str):
        if self._in_command:
            return                       # the command's own; fin covers it
        self.flush()                     # what came before belongs before
        self._pending_ckpts.append(label)

    def _on_discard(self):
        if self._in_command:
            return
        if self._pending_ckpts:
            self._pending_ckpts.pop()    # a drag that went back to zero

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

    def flush(self):
        """Write the settled idle delta, if there is one.

        Called when a command starts, when a new checkpoint arrives, on a
        UI quiet-period timer, and on close — never per mouse move, so a
        drag lands as one delta, not four hundred.
        """
        if self._flushing or not (self._dirty or self._pending_ckpts):
            return
        self._flushing = True
        try:
            if not self._pending_ckpts:
                # geometry changed but nobody checkpointed: a deferred
                # shape converting on first read, not an edit
                self._refresh_shadow()
                self._dirty = False
                return
            made, chg, gone = self._delta()
            if not (made or chg or gone):
                self._pending_ckpts.clear()
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

    def close(self):
        if self._f.closed:
            return
        self.flush()
        self._f.close()

    # -- internals --

    def _delta(self):
        made, chg, gone = [], [], []
        for oid in self.scene._order:
            obj = self.scene.objects[oid]
            if oid not in self._shadow:
                made.append([oid, obj.name, _b64(obj.shape)])
            elif obj._shape is not self._shadow[oid]:
                chg.append([oid, _b64(obj.shape)])
        for oid in self._shadow:
            if oid not in self.scene.objects:
                gone.append(oid)
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
        event["t"] = round(time.time(), 3)
        self._f.write(json.dumps(event) + "\n")
