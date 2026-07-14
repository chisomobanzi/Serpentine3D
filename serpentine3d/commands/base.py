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

import math
from dataclasses import dataclass, field
from typing import Callable

from ..core import geometry

Point = tuple[float, float, float]


# --------------------------------------------------------------- input requests

class Req:
    prompt: str = ""
    choices: dict | None = None      # {"Cap": ["Yes","No"]} option chips
    preview_fn = None                # callable(value) -> shape for ghosts


@dataclass
class PointReq(Req):
    prompt: str
    default: Point | None = None
    rubber_from: Point | None = None      # draw rubber-band line while picking
    rubber_pts: list | None = None        # accumulated points (polyline preview)
    allow_empty: bool = False             # Enter with no input -> None (done)
    extra_options: tuple = ()             # typed keywords returned verbatim
    choices: dict | None = None
    preview_fn: object = None             # value/point -> ghost shape
    axis_lock: tuple | None = None        # (base, dir): pick along this axis
    number_from: tuple | None = None      # (base, dir): '10' -> base+10*dir


@dataclass
class NumberReq(Req):
    prompt: str
    default: float | None = None
    minimum: float | None = None
    choices: dict | None = None
    preview_fn: object = None


@dataclass
class LengthReq(NumberReq):
    """A length in document units — accepts 3'6", 30cm, 1.5in, etc."""


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
    choices: dict | None = None
    preview_fn: object = None


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
        return _REGISTRY.get(_ALIASES[key].split()[0])
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

    def opt(self, name: str, default: str) -> str:
        return getattr(self, "options", {}).get(name, default)

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

def parse_point(text: str, last_point: Point | None = None,
                units: str = "mm", cplane=None) -> Point | None:
    """Parse coordinates: 'x,y[,z]' absolute, '@dx,dy[,dz]' relative, or
    'dist<angle' polar (relative to the last point, on the CPlane).

    Each coordinate accepts unit expressions (3'6", 30cm, 1.5in)."""
    from ..utils.units import parse_length
    text = text.strip()

    # polar: distance<angle_degrees (CPlane XY, from last point)
    if "<" in text:
        dist_s, _, ang_s = text.partition("<")
        dist = parse_length(dist_s, units)
        try:
            ang = math.radians(float(ang_s.strip()))
        except ValueError:
            return None
        if dist is None:
            return None
        base = last_point or (0.0, 0.0, 0.0)
        if cplane is not None:
            u, v, w = cplane.from_world(base)
            return cplane.to_world(u + dist * math.cos(ang),
                                   v + dist * math.sin(ang), w)
        return (base[0] + dist * math.cos(ang),
                base[1] + dist * math.sin(ang), base[2])

    relative = text.startswith("@")
    if relative:
        text = text[1:]
    parts = [p.strip() for p in text.replace(";", ",").split(",")]
    if len(parts) not in (2, 3):
        return None
    vals = []
    for p in parts:
        v = parse_length(p, units)
        if v is None:
            return None
        vals.append(v)
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
        pt = parse_point(text, ctx.last_point, ctx.scene.units, ctx.cplane)
        if pt is None and req.number_from is not None:
            from ..utils.units import parse_length
            v = parse_length(text, ctx.scene.units)
            if v is not None:
                base, direction = req.number_from
                pt = tuple(b + v * d for b, d in zip(base, direction))
        if pt is None:
            return False, ("Expected coordinates like 3,4,0 "
                           "(@1,0 relative, 10<45 polar, units like 3'6\")")
        return True, pt
    if isinstance(req, LengthReq):
        if not text and req.default is not None:
            return True, req.default
        from ..utils.units import parse_length
        v = parse_length(text, ctx.scene.units)
        if v is None:
            return False, "Expected a length (e.g. 250, 3'6\", 30cm)"
        if req.minimum is not None and v < req.minimum:
            return False, f"Value must be >= {req.minimum}"
        return True, v
    if isinstance(req, NumberReq):
        if not text and req.default is not None:
            return True, req.default
        try:
            v = float(text)
        except ValueError:
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
        for opt in req.options:                    # exact match first
            if text and opt.lower() == text.lower():
                return True, opt
        for opt in req.options:
            if text and opt.lower().startswith(text.lower()):
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
        self.command_options: dict = {}
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
        # macro form: 'osnap mid toggle' — first token is the command,
        # the rest answer its prompts; aliases may expand to macros too
        tokens = name.split()
        name = tokens[0] if tokens else name
        args = tokens[1:]
        alias_target = _ALIASES.get(name.lower().strip())
        if alias_target and " " in alias_target:
            expanded = alias_target.split()
            name = expanded[0]
            args = expanded[1:] + args
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
        self.command_options = {}
        self.ctx.options = self.command_options
        self._advance(None)
        for arg in args:
            if not self.busy:
                break
            self.provide_text(arg)
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
        if was and was.mutates and success:
            # command is over: release the selection (Rhino-style);
            # 'sellast' / 'selprev' habits bring it back
            self.ctx.selection.clear()
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

    def set_option(self, name: str, value: str | None = None):
        """Set (or cycle) a persistent option of the running command."""
        req = self.request
        if req is None or not getattr(req, "choices", None):
            return False
        for opt_name, values in req.choices.items():
            if opt_name.lower() == name.lower():
                if value is None:            # cycle
                    cur = self.command_options.get(opt_name, values[0])
                    idx = (values.index(cur) + 1) % len(values) \
                        if cur in values else 0
                    value = values[idx]
                else:
                    matches = [v for v in values
                               if v.lower().startswith(value.lower())]
                    if not matches:
                        return False
                    value = matches[0]
                self.command_options[opt_name] = value
                self.ctx.echo(f"{opt_name}={value}")
                self._notify()
                return True
        return False

    def _try_option_text(self, text: str) -> bool:
        req = self.request
        if req is None or not getattr(req, "choices", None):
            return False
        text = text.strip()
        if "=" in text:
            name, _, value = text.partition("=")
            return self.set_option(name.strip(), value.strip())
        for opt_name in req.choices:
            if opt_name.lower() == text.lower():
                return self.set_option(opt_name)
        return False

    def option(self, name: str, default: str) -> str:
        return self.command_options.get(name, default)

    def preview_shape(self, text: str):
        """Ghost shape for text being typed at the current request, or None."""
        req = self.request
        if req is None or getattr(req, "preview_fn", None) is None:
            return None
        ok, value = parse_value(req, text, self.ctx)
        return self.preview_for(value) if ok else None

    def preview_for(self, value):
        """Ghost shape for a candidate value (e.g. the mouse point)."""
        req = self.request
        fn = getattr(req, "preview_fn", None) if req else None
        if fn is None or value is None:
            return None
        try:
            return fn(value)
        except Exception:                                  # noqa: BLE001
            return None

    def provide_text(self, text: str):
        """Feed typed text for the current request."""
        if not self.busy or self.request is None:
            return
        if text.strip() and self._try_option_text(text):
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
        if not self.ctx.scene.is_selectable(obj.id):
            return False
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
        if not self._select_buffer and req.min_count > 0:
            self.cancel()                    # Enter on nothing: never mind
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
    def option_chips(self) -> list:
        """[(name, current_value)] for the active request's options."""
        req = self.request
        if req is None or not getattr(req, "choices", None):
            return []
        return [(n, self.command_options.get(n, v[0]))
                for n, v in req.choices.items()]

    def prompt_text(self) -> str:
        if self.request is None:
            return "Command"
        base = format_prompt(self.request)
        if isinstance(self.request, SelectReq):
            n = len(self._select_buffer)
            if n:
                base += f"  [{n} selected — Enter to accept]"
        return base
