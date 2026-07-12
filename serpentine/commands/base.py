"""Interactive command framework.

A command is a generator function: it yields input requests (points, numbers,
object selections, options) and receives the resolved values back. The
CommandProcessor drives the generator from typed command-line input, viewport
clicks, or the MCP bridge — the command code never knows the difference.

    @command("line", aliases=("l",))
    def cmd_line(ctx):
        p1 = yield PointReq("Start of line")
        p2 = yield PointReq("End of line", rubber_from=p1)
        obj = ctx.scene.add(geometry.make_line(p1, p2))
        ctx.echo(f"Created {obj.name}.")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..core import geometry

Point = tuple[float, float, float]


# --------------------------------------------------------------- input requests

class Req:
    prompt: str = ""


@dataclass
class PointReq(Req):
    prompt: str
    default: Point | None = None
    rubber_from: Point | None = None      # draw rubber-band line while picking
    rubber_pts: list | None = None        # accumulated points (polyline preview)
    allow_empty: bool = False             # Enter with no input -> None (done)
    extra_options: tuple = ()             # typed keywords returned verbatim


@dataclass
class NumberReq(Req):
    prompt: str
    default: float | None = None
    minimum: float | None = None


@dataclass
class IntReq(Req):
    prompt: str
    default: int | None = None
    minimum: int | None = None


@dataclass
class TextReq(Req):
    prompt: str
    default: str | None = None


@dataclass
class OptionReq(Req):
    prompt: str
    options: list[str] = field(default_factory=list)
    default: str | None = None


@dataclass
class SelectReq(Req):
    prompt: str
    min_count: int = 1
    max_count: int | None = None          # None = unlimited, finish with Enter
    kinds: tuple = ()                     # () = any; else e.g. ("curve",)
    allow_preselected: bool = True


class CancelCommand(Exception):
    """Raised inside a generator when the user hits Escape."""


# --------------------------------------------------------------- registry

@dataclass
class CommandDef:
    name: str
    fn: Callable
    aliases: tuple = ()
    label: str = ""
    mutates: bool = True


_REGISTRY: dict[str, CommandDef] = {}
_ALIASES: dict[str, str] = {}


def command(name: str, aliases: tuple = (), label: str = "",
            mutates: bool = True):
    def wrap(fn):
        cd = CommandDef(name=name.lower(), fn=fn, aliases=aliases,
                        label=label or name.capitalize(), mutates=mutates)
        _REGISTRY[cd.name] = cd
        for a in aliases:
            _ALIASES[a.lower()] = cd.name
        return fn
    return wrap


def add_alias(alias: str, target: str):
    """Register a user alias at runtime (overrides built-ins)."""
    _ALIASES[alias.lower().strip()] = target.lower().strip()


def remove_alias(alias: str):
    _ALIASES.pop(alias.lower().strip(), None)


def resolve(name: str) -> CommandDef | None:
    key = name.lower().strip()
    if key in _REGISTRY:
        return _REGISTRY[key]
    if key in _ALIASES:
        return _REGISTRY[_ALIASES[key]]
    return None


def all_commands() -> list[CommandDef]:
    return sorted(_REGISTRY.values(), key=lambda c: c.name)


def completions(prefix: str) -> list[str]:
    prefix = prefix.lower()
    names = [c.name for c in _REGISTRY.values()]
    return sorted(n for n in names if n.startswith(prefix))


# --------------------------------------------------------------- context

class CommandContext:
    def __init__(self, scene, selection, history, viewport=None, window=None):
        self.scene = scene
        self.selection = selection
        self.history = history
        self.viewport = viewport
        self.window = window
        self.last_point: Point | None = None
        self._echo_fns: list = []

    @property
    def cplane(self):
        if self.viewport is not None:
            return self.viewport.cplane
        from ..core.cplane import CPlane
        return CPlane()

    def add_echo_listener(self, fn):
        self._echo_fns.append(fn)

    def echo(self, msg: str):
        for fn in self._echo_fns:
            fn(msg)


# --------------------------------------------------------------- input parsing

def parse_point(text: str, last_point: Point | None = None) -> Point | None:
    """Parse 'x,y[,z]' absolute or '@dx,dy[,dz]' relative coordinates."""
    text = text.strip()
    relative = text.startswith("@")
    if relative:
        text = text[1:]
    parts = [p.strip() for p in text.replace(";", ",").split(",")]
    if len(parts) not in (2, 3):
        return None
    try:
        vals = [float(p) for p in parts]
    except ValueError:
        return None
    if len(vals) == 2:
        vals.append(0.0)
    if relative:
        base = last_point or (0.0, 0.0, 0.0)
        vals = [b + v for b, v in zip(base, vals)]
    return tuple(vals)


def parse_value(req: Req, text: str, ctx: CommandContext):
    """Parse typed text against a request. Returns (ok, value_or_error)."""
    text = text.strip()
    if isinstance(req, PointReq):
        if not text and req.allow_empty:
            return True, None
        if not text and req.default is not None:
            return True, req.default
        for opt in req.extra_options:
            if text and opt.lower().startswith(text.lower()):
                return True, opt
        pt = parse_point(text, ctx.last_point)
        if pt is None:
            return False, "Expected coordinates like 3,4,0 (or @1,0 relative)"
        return True, pt
    if isinstance(req, NumberReq):
        if not text and req.default is not None:
            return True, req.default
        try:
            v = float(text)
        except ValueError:
            # allow a point-pair style distance? keep simple
            return False, "Expected a number"
        if req.minimum is not None and v < req.minimum:
            return False, f"Value must be >= {req.minimum}"
        return True, v
    if isinstance(req, IntReq):
        if not text and req.default is not None:
            return True, req.default
        try:
            v = int(text)
        except ValueError:
            return False, "Expected an integer"
        if req.minimum is not None and v < req.minimum:
            return False, f"Value must be >= {req.minimum}"
        return True, v
    if isinstance(req, TextReq):
        if not text and req.default is not None:
            return True, req.default
        if not text:
            return False, "Expected text"
        return True, text
    if isinstance(req, OptionReq):
        if not text and req.default is not None:
            return True, req.default
        for opt in req.options:
            if opt.lower().startswith(text.lower()) and text:
                return True, opt
        return False, f"Options: {', '.join(req.options)}"
    return False, "Unsupported input"


def format_prompt(req: Req) -> str:
    p = req.prompt
    if isinstance(req, OptionReq) and req.options:
        p += f" ({'/'.join(req.options)})"
    default = getattr(req, "default", None)
    if default is not None:
        if isinstance(default, tuple):
            p += f" <{','.join(str(round(c, 4)) for c in default)}>"
        else:
            p += f" <{default}>"
    return p


# --------------------------------------------------------------- processor

class CommandProcessor:
    """Drives command generators; UI- and transport-agnostic."""

    def __init__(self, ctx: CommandContext):
        self.ctx = ctx
        self.gen = None
        self.active: CommandDef | None = None
        self.request: Req | None = None
        self.last_command: str | None = None
        self._start_revision = 0
        self._select_buffer: list[str] = []
        self._listeners: list = []       # notified on state change

    # -- observers --
    def add_listener(self, fn):
        self._listeners.append(fn)

    def _notify(self):
        for fn in self._listeners:
            fn()

    @property
    def busy(self) -> bool:
        return self.gen is not None

    # -- lifecycle --
    def run(self, name: str) -> bool:
        if self.busy:
            self.cancel()
        cd = resolve(name)
        if cd is None:
            self.ctx.echo(f"Unknown command: {name}")
            self._notify()
            return False
        self.active = cd
        self.last_command = cd.name
        self.ctx.echo(f"> {cd.name}")
        if cd.mutates:
            self._start_revision = self.ctx.scene.revision
            self.ctx.history.checkpoint(cd.name)
        self.gen = cd.fn(self.ctx)
        self._select_buffer = []
        self._advance(None)
        return True

    def _advance(self, value):
        try:
            self.request = self.gen.send(value)
        except StopIteration:
            self._finish(success=True)
            return
        except CancelCommand:
            self._finish(success=False)
            return
        except geometry.GeometryError as exc:
            self.ctx.echo(f"Error: {exc}")
            self._finish(success=False)
            return
        except Exception as exc:                          # noqa: BLE001
            self.ctx.echo(f"Command failed: {type(exc).__name__}: {exc}")
            self._finish(success=False)
            return
        self._prepare_request()
        self._notify()

    def _prepare_request(self):
        req = self.request
        if isinstance(req, SelectReq):
            self._select_buffer = []
            if (req.allow_preselected and self.ctx.selection.ids):
                pre = [o.id for o in self.ctx.selection.objects()
                       if not req.kinds or o.kind in req.kinds]
                if pre:
                    if req.max_count:
                        pre = pre[:req.max_count]
                    if len(pre) >= req.min_count:
                        # consume pre-selection immediately
                        self.ctx.selection.clear()
                        self._advance(
                            [self.ctx.scene.objects[i] for i in pre])
                        return

    def _finish(self, success: bool):
        was = self.active
        self.gen = None
        self.request = None
        self.active = None
        if was and was.mutates and not success:
            # nothing changed -> no undo entry; partial work stays undoable
            if self.ctx.scene.revision == self._start_revision:
                self.ctx.history.discard_checkpoint()
        if not success and was:
            self.ctx.echo(f"{was.label} cancelled.")
        self._notify()

    def cancel(self):
        if self.gen is not None:
            gen = self.gen
            self.gen = None
            try:
                gen.close()
            except Exception:                              # noqa: BLE001
                pass
            self.gen = None
            self._finish(success=False)

    # -- input feeding --
    def provide(self, value):
        """Feed a resolved value (from click or programmatic caller)."""
        if not self.busy or self.request is None:
            return
        if isinstance(self.request, PointReq):
            self.ctx.last_point = value
        self._advance(value)

    def provide_text(self, text: str):
        """Feed typed text for the current request."""
        if not self.busy or self.request is None:
            return
        req = self.request
        if isinstance(req, SelectReq):
            self._select_text(text)
            return
        ok, result = parse_value(req, text, self.ctx)
        if not ok:
            self.ctx.echo(result)
            self._notify()
            return
        self.provide(result)

    # -- selection request handling --
    def _matching(self, obj, req: SelectReq) -> bool:
        return not req.kinds or obj.kind in req.kinds

    def click_object(self, obj_id: str):
        req = self.request
        if not isinstance(req, SelectReq):
            return
        obj = self.ctx.scene.get(obj_id)
        if obj is None or not self._matching(obj, req):
            self.ctx.echo("Object type not accepted here.")
            return
        if obj_id in self._select_buffer:
            self._select_buffer.remove(obj_id)
        else:
            self._select_buffer.append(obj_id)
        self.ctx.selection.set(self._select_buffer)
        if req.max_count and len(self._select_buffer) >= req.max_count:
            self.finish_selection()
        else:
            self._notify()

    def _select_text(self, text: str):
        req = self.request
        text = text.strip()
        if not text:
            self.finish_selection()
            return
        if text.lower() == "all":
            self._select_buffer = [
                o.id for o in self.ctx.scene.visible_objects()
                if self._matching(o, req)]
            self.ctx.selection.set(self._select_buffer)
            self.finish_selection()
            return
        obj = self.ctx.scene.find_by_name(text)
        if obj and self._matching(obj, req):
            if obj.id not in self._select_buffer:
                self._select_buffer.append(obj.id)
            self.ctx.selection.set(self._select_buffer)
            if req.max_count and len(self._select_buffer) >= req.max_count:
                self.finish_selection()
            else:
                self._notify()
        else:
            self.ctx.echo(f"No selectable object named '{text}'.")

    def box_objects(self, obj_ids: list[str]):
        """Add box-selected objects to an active selection request."""
        req = self.request
        if not isinstance(req, SelectReq):
            return
        for obj_id in obj_ids:
            obj = self.ctx.scene.get(obj_id)
            if obj is None or not self._matching(obj, req):
                continue
            if obj_id not in self._select_buffer:
                self._select_buffer.append(obj_id)
                if req.max_count and len(self._select_buffer) >= req.max_count:
                    break
        self.ctx.selection.set(self._select_buffer)
        if req.max_count and len(self._select_buffer) >= req.max_count:
            self.finish_selection()
        else:
            self._notify()

    def finish_selection(self):
        req = self.request
        if not isinstance(req, SelectReq):
            return
        if len(self._select_buffer) < req.min_count:
            self.ctx.echo(
                f"Select at least {req.min_count} object(s) — "
                f"{len(self._select_buffer)} selected.")
            self._notify()
            return
        objs = [self.ctx.scene.objects[i] for i in self._select_buffer]
        self.ctx.selection.clear()
        self._advance(objs)

    # -- prompt for UI --
    def prompt_text(self) -> str:
        if self.request is None:
            return "Command"
        base = format_prompt(self.request)
        if isinstance(self.request, SelectReq):
            n = len(self._select_buffer)
            if n:
                base += f"  [{n} selected — Enter to accept]"
        return base
