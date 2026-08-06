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
    rubber_sides: object = None           # point -> the sides of the frame it
                                          # spans: no band, and two numbers
    allow_empty: bool = False             # Enter with no input -> None (done)
    extra_options: tuple = ()             # typed keywords returned verbatim
    choices: dict | None = None
    preview_fn: object = None             # value/point -> ghost shape
    axis_lock: tuple | None = None        # (base, dir): pick along this axis
    number_from: object = None            # (base, dir) or point-fn: '10' ->
                                          # base+10*dir / number_from(10.0)
    allow_number: bool = False            # bare number returns the float


def frame_sides(corner, cplane):
    """A `rubber_sides` for a rectangle dragged out from `corner`.

    Measured on the plane it is being drawn on, which is the only place the
    two numbers mean anything: a rectangle on a tilted plane has sides of its
    own, and the world's idea of them is a pair of shadows.
    """
    def sides(p):
        u1, v1, _ = cplane.from_world(corner)
        u2, v2, _ = cplane.from_world(p)
        return (abs(u2 - u1), abs(v2 - v1))
    return sides


def quadrant(ctx, cplane=None):
    """Which way the sides run when only their lengths were given.

    A typed length says how big, never which way, and the cursor has been
    saying which way all along. Measured on the plane the shape is drawn on
    when it has one, the world axes when it does not. Positive where there
    is no cursor to ask — a batch, or the bridge — because something has to
    be drawn.
    """
    aim = ctx.aim_direction()
    if aim is None:
        return 1.0, 1.0
    _base, d = aim
    if cplane is None:
        u, v = d[0], d[1]
    else:
        u = sum(a * b for a, b in zip(d, cplane.xdir))
        v = sum(a * b for a, b in zip(d, cplane.ydir))
    return (-1.0 if u < 0 else 1.0), (-1.0 if v < 0 else 1.0)


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
    choices: dict | None = None
    preview_fn: object = None


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
    # Whether an empty Enter, or a right-click on an idle prompt, may repeat
    # this command. Rhino keeps a list it will never repeat and delete is on
    # it: right-clicking is a reflex, and a reflex should not be able to
    # throw away the geometry that is still picked.
    repeatable: bool = True
    # Which space this command's picked points are in: "model" coordinates,
    # "paper" millimetres on a sheet, or "any" for the few that read the
    # viewport and cope with either. Only a sheet can tell them apart, and
    # the default is the safe one — a command that never said is not let
    # loose on paper it cannot mean anything about.
    space: str = "model"


_REGISTRY: dict[str, CommandDef] = {}
_ALIASES: dict[str, str] = {}


def command(name: str, aliases: tuple = (), label: str = "",
            mutates: bool = True, space: str = "model",
            repeatable: bool = True):
    def wrap(fn):
        cd = CommandDef(name=name.lower(), fn=fn, aliases=aliases,
                        label=label or name.capitalize(), mutates=mutates,
                        space=space, repeatable=repeatable)
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
        self.result_ids: list[str] = []
        self.result_subobjects: list = []

    def held_control_points(self) -> dict:
        """{obj_id: [index, ...]} — the control points the selection holds.

        Empty in the ordinary case, which is what tells a command it is
        working on whole objects as it always has. Must be read before the
        command asks anything, since a select prompt clears the selection to
        take its answer and the held points would go with it.
        """
        held: dict = {}
        for entry in getattr(self.selection, "subobjects", []):
            obj_id, kind, index = entry
            if kind != "cv" or self.scene.get(obj_id) is None:
                continue
            held.setdefault(obj_id, []).append(int(index))
        return held

    def control_point_ghost(self, held, fn):
        """Preview of those objects with their held points put through `fn`."""
        shapes = [s for _id, s in self._moved_control_points(held, fn)]
        return geometry.make_compound(shapes) if shapes else None

    def apply_to_control_points(self, held, fn) -> int:
        """Put every held control point through `fn`; how many moved.

        The points stay held afterwards. A command that ends by letting go of
        them would be a command you have to pick your way back into before
        you can nudge the same corner again, and nudging the same corner
        again is most of what control point editing is.
        """
        moved = 0
        for obj_id, shape in self._moved_control_points(held, fn):
            self.scene.replace_shape(obj_id, shape)
            moved += len(held[obj_id])
        self.result_subobjects = [(oid, "cv", i)
                                  for oid, idxs in held.items() for i in idxs]
        return moved

    def _moved_control_points(self, held, fn):
        """(obj_id, shape) for each object, its held points through `fn`.

        Every point is measured from the shape as it stands and put back one
        at a time, the same way the gumball edits them, so a command and a
        drag of the gumball cannot disagree about what a moved corner does to
        the curve. An object whose points cannot be read is skipped rather
        than half-transformed.
        """
        for obj_id, idxs in held.items():
            obj = self.scene.get(obj_id)
            if obj is None:
                continue
            surface = obj.kind == "surface"
            try:
                was = (geometry.surface_control_points(obj.shape)[0]
                       if surface else geometry.get_control_points(obj.shape))
                to = geometry.transform_points([was[i] for i in idxs], fn)
                shape = obj.shape
                for i, p in zip(idxs, to):
                    shape = (geometry.move_surface_control_point(shape, i, p)
                             if surface
                             else geometry.move_control_point(shape, i, p))
            except (geometry.GeometryError, IndexError):
                continue
            yield obj_id, shape

    def select_result(self, objs):
        """Say what this command made, to be left selected when it ends.

        Most commands let go of the selection on the way out, because you
        picked those objects to say which ones and the pick has been spent.
        A boolean is the other sort: it eats what you picked and puts
        something else there, so letting go leaves you holding nothing and
        the gumball, which was on the solid you were working on, with
        nowhere to be.
        """
        self.result_ids = [o if isinstance(o, str) else o.id for o in objs]

    def opt(self, name: str, default: str) -> str:
        return getattr(self, "options", {}).get(name, default)

    @property
    def cplane(self):
        """The plane the running command draws on.

        The viewport is asked rather than told: inside a detail the plane is
        the one that detail looks at, and a command has no business knowing
        whether it is being run through a window onto the model.
        """
        if self.viewport is not None:
            return self.viewport.active_cplane()
        from ..core.cplane import CPlane
        return CPlane()

    def locked_direction(self):
        """The Tab direction lock, if one is being held for this point.

        Typing a length is how you use a lock, so the parser has to know
        about it, and only the viewport can say whether the lock still
        belongs to the point being picked rather than an earlier one.
        """
        vp = self.viewport
        fn = getattr(vp, "locked_direction", None) if vp is not None else None
        return fn() if fn is not None else None

    def aim_direction(self):
        """The direction the cursor is pointing from the point before it.

        What makes a bare number a point at a prompt no command named an
        axis for: the rubber band on screen says which way, the number says
        how far. Only the viewport knows where the cursor is, and only it
        knows that ortho or a snap has already moved the answer.
        """
        for vp in self._aiming_panes():
            fn = getattr(vp, "aim_direction", None)
            aim = fn() if fn is not None else None
            if aim is not None:
                return aim
        return None

    def _aiming_panes(self):
        """The panes to ask which way, the cursor's own first.

        Four panes share one command line. The number is typed at the
        keyboard but it is aimed with the mouse, and the mouse is not
        always in the pane the last click made active — draw in Top with
        Perspective still active and the pane commands act on has never
        had the cursor over it, so it has nothing to say.
        """
        panes = []
        listing = getattr(self.window, "all_viewports", None)
        if listing is not None:
            panes = [v for v in listing()
                     if getattr(v, "underMouse", None) is not None
                     and v.underMouse()]
        if self.viewport is not None and self.viewport not in panes:
            panes.append(self.viewport)
        return panes

    def on_bare_paper(self) -> bool:
        """True when a pick can only name paper, and not the model.

        Inside a detail it can name both — the detail is a window onto the
        model, so the viewport unprojects through it.
        """
        vp = self.viewport
        if vp is None or getattr(vp, "space", "model") == "model":
            return False
        lv = getattr(vp, "layout_view", None)
        return getattr(lv, "entered_detail", None) is None

    def sheet_view(self):
        """The layout view, when a command asking for objects means the sheet.

        A sheet has two things on it a command could mean: the sheet's own
        geometry, frames and annotations, and the model seen through a detail.
        The same thing that decides where a point lands decides this — a detail
        is a window onto the model, so inside one a command is working on the
        model and can ask for model objects the ordinary way, by clicking them
        through the frame. On bare paper there is no model to ask about and no
        click that could name one, so the sheet is the answer, and a command
        that went looking for model objects there would wait for ever.

        None for the headless stub viewport, which has no sheet to pick on.
        """
        if not self.on_bare_paper():
            return None
        lv = getattr(self.viewport, "layout_view", None)
        return lv if hasattr(lv, "delete_selected") else None

    def add(self, shape, name: str | None = None):
        """Put a new shape where the command is drawing it.

        The model, normally. On bare paper there is no model point the command
        could have been given, so what it drew is paper geometry and belongs to
        the sheet — the millimetres it was handed are the millimetres it keeps.
        Inside a detail the picks were model points already, so it goes in the
        model like anything else.

        Commands that can only mean the model — a box, an extrusion — never
        reach here on paper: the processor refuses their first point instead.
        """
        lay = self.viewport.layout_view.layout if self.on_bare_paper() else None
        if lay is None:
            return self.scene.add(shape, name=name)
        obj = lay.add(shape, name=name)
        # so the checkpoint taken at the start of the command is kept: it is
        # discarded if the scene says nothing changed, and a sheet is the scene
        self.scene.notify("layouts")
        return obj

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
        # A command that runs along an axis of its own says so; failing
        # that, Tab lets you aim one by hand, and failing that the cursor is
        # aiming one anyway. A number means the same thing in all three: how
        # far along it. Tab beats the cursor because a frozen direction is a
        # decision already made, and moving the mouse afterwards must not
        # quietly undo it.
        along = req.number_from
        if along is None and not req.allow_number:
            along = ctx.locked_direction() or ctx.aim_direction()
        if pt is None and (along is not None or req.allow_number):
            from ..utils.units import parse_length
            v = parse_length(text, ctx.scene.units)
            if v is not None:
                if callable(along):
                    pt = tuple(along(v))
                elif along is not None:
                    base, direction = along
                    pt = tuple(b + v * d for b, d in zip(base, direction))
                else:
                    return True, float(v)     # allow_number: the raw value
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
    extras = getattr(req, "extra_options", ())
    if extras:
        p += f" ({'/'.join(extras)})"
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
        # every point the running command has taken, so the UI can offer
        # them as snaps: what you are drawing is not in the scene yet
        self.picked_points: list = []

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
        self.picked_points = []
        if cd.repeatable:
            # A command that is never repeated does not disturb the repeat
            # target either: after delete, Enter still repeats whatever you
            # were doing before it.
            self.last_command = cd.name
        self.ctx.echo(f"> {cd.name}")
        if cd.mutates:
            self._start_revision = self.ctx.scene.revision
            self.ctx.history.checkpoint(cd.name)
        self.gen = cd.fn(self.ctx)
        self.ctx.result_ids = []
        self.ctx.result_subobjects = []
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
        if (isinstance(req, PointReq) and self.active is not None
                and self.active.space == "model"
                and self.ctx.on_bare_paper()):
            # Bare paper is not somewhere a model coordinate exists, and
            # answering with millimetres put the geometry in the model at the
            # paper's numbers. Cancel first, so that the reason is the last
            # thing said rather than buried under "cancelled".
            # Two lines, because only the newest line or two is on screen and
            # each half has to stand on its own: what went wrong, then what to
            # do about it.
            label = self.active.label
            self.cancel()
            self.ctx.echo(f"{label} needs a point in the model, "
                          "and bare paper is not the model.")
            self.ctx.echo("Double-click a detail to work inside it, or "
                          "annotate the sheet with text, dim, leader or hatch.")
            return
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
        self.picked_points = []
        was = self.active
        self.gen = None
        self.request = None
        self.active = None
        made = [i for i in self.ctx.result_ids if i in self.ctx.scene.objects]
        held = [e for e in self.ctx.result_subobjects
                if e[0] in self.ctx.scene.objects]
        self.ctx.result_ids = []
        self.ctx.result_subobjects = []
        if was and was.mutates and success:
            # command is over: release the selection (Rhino-style);
            # 'sellast' / 'selprev' habits bring it back. Unless it said what
            # it made, in which case that is what you are holding — see
            # CommandContext.select_result.
            if made:
                self.ctx.selection.set(made)
            else:
                self.ctx.selection.clear()
            # Control points are the exception again, and the other way about:
            # a command that worked on them hands them back, because the next
            # thing you do to a corner is nearly always move it again.
            if held:
                self.ctx.selection.set_subobjects(held)
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
            # Enter answers with None and an option answers with its name;
            # neither is somewhere you can snap to
            if value is not None and not isinstance(value, str):
                try:
                    self.picked_points.append(
                        tuple(float(c) for c in value)[:3])
                except (TypeError, ValueError):
                    pass
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
    def keyword_chips(self) -> list[str]:
        """One-shot words the current prompt accepts, for clickable chips.

        Where option chips carry a value and cycle, these answer the prompt
        outright: Close on a polyline, Center on an arc. Clicking one is
        the same as typing it.
        """
        req = self.request
        return list(getattr(req, "extra_options", ()) or ())

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
