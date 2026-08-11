"""Re-execute a session journal and land on the same geometry.

The journal recorded resolved values, so nothing here parses or snaps:
points are fed back as points, keywords as keywords, and the plane and
aim each value was resolved under are installed as context overrides
before the command sees it. Object ids differ run to run — uuid4 does
not take requests — so an id map carries every recorded reference across
to the object that stands in its place.

Commands that write files (save, export) are skipped whole: their scene
effect is nil and a replay has no business writing over anyone's disk.
"""

from __future__ import annotations

import base64
import json

from . import geometry
from .cplane import CPlane
from .history import History
from .scene import Scene
from .selection import SelectionManager

# their effect is on disk, not in the scene
SKIP_COMMANDS = {"save", "saveas", "export", "screenshot",
                 "viewcapturetoclipboard", "turntable"}

_TOL = 1e-4


class ReplayError(RuntimeError):
    """The replay stopped matching the recording."""


def load_events(path: str) -> list[dict]:
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


class Replayer:
    def __init__(self, events, echo=None):
        import serpentine3d.commands  # noqa: F401 — registers commands
        from ..commands.base import CommandContext, CommandProcessor
        self.events = list(events)
        self.scene = Scene()
        self.selection = SelectionManager(self.scene)
        self.history = History(self.scene)
        self.ctx = CommandContext(self.scene, self.selection, self.history)
        if echo is not None:
            self.ctx.add_echo_listener(echo)
        self.proc = CommandProcessor(self.ctx)
        self.idmap: dict[str, str] = {}
        self._before_cmd: set = set()
        self._mismatches: list[str] = []
        self.fingerprints_checked = 0
        self.on_event = None            # hook for the renderer: fn(event)

    # -- driving --

    def run(self):
        i = 0
        while i < len(self.events):
            i = self.step(i)

    def step(self, i: int) -> int:
        """Apply event i; return the index of the next event to apply."""
        e = self.events[i]
        handler = getattr(self, f"_ev_{e['ev']}", None)
        nxt = None
        if handler is not None:
            nxt = handler(e, i)
        if self.on_event is not None:
            self.on_event(e)
        return nxt if nxt is not None else i + 1

    def verify(self) -> list[str]:
        """Mismatches against every fingerprint met during the run."""
        return list(self._mismatches)

    # -- events --

    def _ev_session(self, e, i):
        if e.get("ver", 1) > 1:
            raise ReplayError(f"journal version {e['ver']} is newer "
                              "than this replayer")

    def _ev_broken(self, e, i):
        """The recorder gave up here, so the file stops before the work did.

        Everything up to this point still replays. What follows it was
        never written down, and saying so is the whole point of the
        marker: a short recipe is fine, a silently short one is not.
        """
        self._mismatches.append(
            f"the recording stopped early: {e.get('why', 'unknown')}")

    def _ev_cmd(self, e, i):
        from ..commands.base import resolve
        name = e["name"]
        if name in SKIP_COMMANDS or resolve(name) is None:
            j = i + 1                    # consume the whole command silently
            while j < len(self.events) and self.events[j]["ev"] != "fin":
                j += 1
            return j + 1
        self._apply_ctx(e)
        sel = [x for x in self._mapped(e.get("sel", []))
               if x in self.scene.objects]
        if sel:
            self.selection.set(sel)
        else:
            self.selection.clear()
        sub = [(self.idmap.get(s[0], s[0]), s[1], s[2])
               for s in e.get("sub", [])]
        sub = [s for s in sub if s[0] in self.scene.objects]
        if sub:
            self.selection.set_subobjects(sub)
        self._before_cmd = set(self.scene.objects)
        self.proc.run(name)

    def _ev_val(self, e, i):
        self._apply_ctx(e)
        v = e["v"]
        if v is not None and "ids" in v:
            from ..commands.base import SelectReq
            if isinstance(self.proc.request, SelectReq):
                objs = [self.scene.objects[x]
                        for x in self._mapped(v["ids"])
                        if x in self.scene.objects]
                self.selection.clear()
                sub = [(self.idmap.get(s[0], s[0]), s[1], s[2])
                       for s in e.get("sub", [])]
                sub = [s for s in sub if s[0] in self.scene.objects]
                if sub:
                    # sub-objects held when the live answer was given —
                    # the command reads these right after the yield
                    self.selection.set_subobjects(sub)
                self.proc._advance(objs)
            # else: the preselection consumed it inside run(), identically
        elif v is None:
            self.proc.provide(None)
        elif "p" in v:
            self.proc.provide(tuple(v["p"]))
        elif "n" in v:
            self.proc.provide(float(v["n"]))
        elif "s" in v:
            self.proc.provide(v["s"])

    def _ev_opt(self, e, i):
        self.proc.set_option(e["name"], e.get("value"))

    def _ev_cancel(self, e, i):
        self.proc.cancel()

    def _ev_fin(self, e, i):
        if self.proc.busy:
            raise ReplayError(f"desync at event {i}: the recording finished "
                              f"a command the replay is still inside")
        new = [oid for oid in self.scene._order
               if oid not in self._before_cmd]
        rec = e.get("made", [])
        if len(new) != len(rec):
            raise ReplayError(
                f"desync at event {i}: recorded {len(rec)} new object(s), "
                f"replay made {len(new)}")
        for a, b in zip(rec, new):
            self.idmap[a] = b

    def _ev_ckpt(self, e, i):
        self.history.checkpoint(e.get("label", ""))

    def _ev_edit(self, e, i):
        for oid, name, b64 in e.get("made", []):
            shape = geometry.shape_from_bytes(base64.b64decode(b64))
            self.idmap[oid] = self.scene.add(shape, name=name).id
        for oid, b64 in e.get("chg", []):
            x = self.idmap.get(oid, oid)
            if x in self.scene.objects:
                self.scene.replace_shape(
                    x, geometry.shape_from_bytes(base64.b64decode(b64)))
        for oid in e.get("gone", []):
            x = self.idmap.get(oid, oid)
            if x in self.scene.objects:
                self.scene.remove(x)

    def _ev_load(self, e, i):
        from .. import fileio
        before = set(self.scene.objects)
        self.history.checkpoint("open")
        fileio.import_file(self.scene, e["path"])
        new = [oid for oid in self.scene._order if oid not in before]
        for a, b in zip(e.get("made", []), new):
            self.idmap[a] = b

    def _ev_fp(self, e, i):
        self.fingerprints_checked += 1
        rec = e.get("objects", [])
        if len(rec) != len(self.scene.all()):
            self._mismatches.append(
                f"object count: recorded {len(rec)}, "
                f"replayed {len(self.scene.all())}")
        for r in rec:
            x = self.idmap.get(r["id"], r["id"])
            obj = self.scene.objects.get(x)
            if obj is None:
                self._mismatches.append(f"{r['id']}: missing after replay")
                continue
            if obj.kind != r["kind"]:
                self._mismatches.append(
                    f"{r['id']}: kind {r['kind']} became {obj.kind}")
                continue
            try:
                size = (geometry.volume(obj.shape) if obj.kind == "solid"
                        else geometry.curve_length(obj.shape)
                        if obj.kind == "curve" else 0.0)
            except Exception:                              # noqa: BLE001
                size = 0.0
            if abs(size - r["size"]) > _TOL * max(1.0, abs(r["size"])):
                self._mismatches.append(
                    f"{r['id']}: size {r['size']} became {round(size, 6)}")
                continue
            mn, mx = obj.bbox()
            for got, want in zip((*mn, *mx), r["bb"]):
                if abs(got - want) > _TOL * max(1.0, abs(want)):
                    self._mismatches.append(
                        f"{r['id']}: bbox drifted "
                        f"({round(got, 6)} vs {want})")
                    break

    # -- helpers --

    def _mapped(self, ids):
        return [self.idmap.get(i, i) for i in ids]

    def _apply_ctx(self, e):
        if "cp" in e:
            cp = e["cp"]
            self.ctx.replay_cplane = CPlane(origin=cp["o"], normal=cp["n"],
                                            xdir=cp["x"])
        if e["ev"] == "val":
            aim = e.get("aim")
            self.ctx.replay_aim = (
                (tuple(aim[0]), tuple(aim[1])) if aim else None)
