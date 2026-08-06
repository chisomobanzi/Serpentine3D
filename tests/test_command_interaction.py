"""Every distance in the model must be answerable with the mouse.

Serpentine3D already has the pattern for this — sphere, cylinder, cone and
circle all ask for their radius as a point you can drag, with a ghost of the
result following the cursor and a typed number still accepted:

    rp = yield PointReq("Radius (click, or type a number)",
                        number_from=(centre, direction),
                        rubber_from=centre, preview_fn=_sphere_to)

Commands written without that pattern make the user compute a number in their
head and type it blind. Torus was the one that got reported, but it was never
only torus. This test is the standard: a command that asks for a distance in
model space must accept a drag and must show what it is about to make.

Quantities that are not distances in the model — paper millimetres, screen
pixels, a camera's focal length — are exempt, and each exemption says why.
"""

import ast
import glob
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Prompt words that mean "this is a distance in the model".
SPATIAL_WORDS = (
    "radius", "height", "length", "distance", "width", "depth", "size",
    "diameter", "offset", "thickness", "spacing", "gap", "extrude", "dist",
)

# (command, exact prompt) -> why the mouse cannot answer this one.
KEYBOARD_ONLY = {
    ("camera", "Focal length (mm)"):
        "a property of the lens, not a distance in the scene",
    ("layout", "Paper width (mm)"):
        "the size of the sheet, which is not in the model at all",
    ("layout", "Paper height (mm)"):
        "the size of the sheet, which is not in the model at all",
    ("text", "Text height (mm)"):
        "annotation height on the printed sheet, not model space",
    ("hatch", "Line spacing (mm)"):
        "hatch density on the printed sheet, not model space",
    ("dimstyle", "Text height (mm)"):
        "a style setting with no geometry on screen to drag against",
    ("dimstyle", "Arrow size (mm)"):
        "a style setting with no geometry on screen to drag against",
    ("layer", "Edge width on screen (pixels)"):
        "a width in screen pixels, which has no length in the model",
    ("detailsection",
     "Cut plane distance from the detail target (toward the viewer)"):
        "you are inside a layout detail, so the cursor is on the paper "
        "sheet and cannot reach into the model to measure a cut depth",
}

# (command, exact prompt) -> why this later point has nothing to preview yet.
_FIRST_OF_ITS_FLOW = (
    "the first pick of an alternate way in (Center, 2Point, ...) — it comes "
    "after the keyword answer, so it is not the function's first PointReq, "
    "but nothing exists yet to drag from"
)

NOTHING_TO_SHOW = {
    ("point", "Next point (Enter to finish)"):
        "each point object stands alone — nothing joins it to the last one, "
        "so a rubber band back to it would draw a line that is not there",
    ("line", "Middle of line"): _FIRST_OF_ITS_FLOW,
    ("circle", "Start of diameter"): _FIRST_OF_ITS_FLOW,
    ("circle", "First point on circle"): _FIRST_OF_ITS_FLOW,
    ("arc", "Center of arc"): _FIRST_OF_ITS_FLOW,
    ("arc", "Start of arc"): _FIRST_OF_ITS_FLOW,
    ("ellipse", "Start of first axis"): _FIRST_OF_ITS_FLOW,
    ("sphere", "Start of diameter"): _FIRST_OF_ITS_FLOW,
}


def _commands():
    """(file, command name, [(req type, prompt, kwargs, line)]) per command."""
    out = []
    for path in sorted(glob.glob(os.path.join(
            ROOT, "serpentine3d", "commands", "*.py"))):
        tree = ast.parse(open(path).read())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = None
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call)
                        and getattr(dec.func, "id", "") == "command"
                        and dec.args
                        and isinstance(dec.args[0], ast.Constant)):
                    name = dec.args[0].value
            if name is None:
                continue
            reqs = []
            for sub in ast.walk(node):
                if not isinstance(sub, ast.Yield) or sub.value is None:
                    continue
                call = sub.value
                if not isinstance(call, ast.Call):
                    continue
                rtype = getattr(call.func, "id", None)
                if not rtype or not rtype.endswith("Req"):
                    continue
                prompt = ""
                if call.args and isinstance(call.args[0], ast.Constant):
                    prompt = str(call.args[0].value)
                kwargs = {k.arg for k in call.keywords if k.arg}
                reqs.append((rtype, prompt, kwargs, sub.lineno))
            reqs.sort(key=lambda r: r[3])
            if reqs:
                out.append((os.path.basename(path), name, reqs))
    return out


def _is_spatial(prompt: str) -> bool:
    low = prompt.lower()
    return any(w in low for w in SPATIAL_WORDS)


def test_the_audit_can_actually_see_the_commands():
    """A parser that quietly matches nothing would make every test below
    pass while checking not one thing."""
    cmds = _commands()
    assert len(cmds) > 100, f"only found {len(cmds)} commands — parser broken"
    names = {c for _, c, _ in cmds}
    for expected in ("torus", "sphere", "cylinder", "line", "polyline"):
        assert expected in names, f"{expected} missing — parser broken"


def test_a_distance_in_the_model_can_be_answered_with_the_mouse():
    offenders = []
    for fname, cmd, reqs in _commands():
        for rtype, prompt, _kwargs, line in reqs:
            if rtype not in ("LengthReq", "NumberReq"):
                continue
            if not _is_spatial(prompt):
                continue
            if (cmd, prompt) in KEYBOARD_ONLY:
                continue
            offenders.append(f"  {fname}:{line}  {cmd}: {prompt!r}")
    assert not offenders, (
        "these ask for a distance in the model but only accept typing:\n"
        + "\n".join(offenders)
        + "\n\nUse a PointReq with number_from= and preview_fn= so it can be "
          "dragged (see cmd_sphere), or add it to KEYBOARD_ONLY with a "
          "reason if the mouse genuinely cannot answer it.")


def test_a_dragged_distance_shows_what_it_is_about_to_make():
    """number_from without preview_fn is a drag in the dark."""
    offenders = []
    for fname, cmd, reqs in _commands():
        for rtype, prompt, kwargs, line in reqs:
            if rtype != "PointReq" or "number_from" not in kwargs:
                continue
            if kwargs & {"preview_fn", "rubber_from", "rubber_pts"}:
                continue
            offenders.append(f"  {fname}:{line}  {cmd}: {prompt!r}")
    assert not offenders, (
        "these can be dragged but show nothing while you drag:\n"
        + "\n".join(offenders))


def test_a_draggable_prompt_says_so():
    """The user cannot see that a prompt takes a drag unless it says so."""
    offenders = []
    for fname, cmd, reqs in _commands():
        for rtype, prompt, kwargs, line in reqs:
            if rtype != "PointReq" or "number_from" not in kwargs:
                continue
            if "click" in prompt.lower() or "drag" in prompt.lower():
                continue
            offenders.append(f"  {fname}:{line}  {cmd}: {prompt!r}")
    assert not offenders, (
        "these accept a drag but the prompt does not mention it; say "
        "'(click, or type a number)':\n" + "\n".join(offenders))


def test_every_exemption_still_points_at_something_real():
    """An exemption for a prompt that has been reworded stops protecting
    anything and starts hiding the next offender."""
    live = {(cmd, prompt)
            for _f, cmd, reqs in _commands()
            for _rt, prompt, _kw, _ln in reqs}
    stale = sorted(k for k in KEYBOARD_ONLY if k not in live)
    assert not stale, (
        f"KEYBOARD_ONLY entries that match no prompt any more: {stale}")


@pytest.mark.parametrize("entry,reason", sorted(KEYBOARD_ONLY.items()))
def test_every_exemption_gives_a_reason(entry, reason):
    assert reason and len(reason) > 15, f"{entry} needs a real reason"


def test_a_point_after_the_first_shows_something():
    """The first pick of a command has nothing to show yet. Every pick after
    it does: by then the command knows something about the shape, and the
    user should be able to see it follow the cursor rather than guess.

    This is the general form of the complaint that started all of it — you
    could not see, or snap to, the thing you were in the middle of drawing.
    """
    shows = {"rubber_from", "rubber_pts", "preview_fn", "axis_lock",
             "number_from"}
    offenders = []
    for fname, cmd, reqs in _commands():
        points = [r for r in reqs if r[0] == "PointReq"]
        for rtype, prompt, kwargs, line in points[1:]:
            if kwargs & shows or (cmd, prompt) in NOTHING_TO_SHOW:
                continue
            offenders.append(f"  {fname}:{line}  {cmd}: {prompt!r}")
    assert not offenders, (
        "these ask for another point but show nothing while you move:\n"
        + "\n".join(offenders)
        + "\n\nPass rubber_from= (or rubber_pts=/preview_fn=) so the shape "
          "follows the cursor, or add it to NOTHING_TO_SHOW with a reason.")


@pytest.mark.parametrize("entry,reason", sorted(NOTHING_TO_SHOW.items()))
def test_every_silent_point_gives_a_reason(entry, reason):
    assert reason and len(reason) > 15, f"{entry} needs a real reason"


def _commands_using(helper):
    """(file, command, [(prompt, kwargs, line)]) for commands calling helper."""
    out = []
    for path in sorted(glob.glob(os.path.join(
            ROOT, "serpentine3d", "commands", "*.py"))):
        tree = ast.parse(open(path).read())
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            name = None
            for dec in node.decorator_list:
                if (isinstance(dec, ast.Call)
                        and getattr(dec.func, "id", "") == "command"
                        and dec.args
                        and isinstance(dec.args[0], ast.Constant)):
                    name = dec.args[0].value
            if name is None:
                continue
            calls = {getattr(c.func, "attr", getattr(c.func, "id", ""))
                     for c in ast.walk(node) if isinstance(c, ast.Call)}
            if helper not in calls:
                continue
            reqs = []
            for sub in ast.walk(node):
                call = sub.value if isinstance(sub, ast.Yield) else None
                if not isinstance(call, ast.Call):
                    continue
                if getattr(call.func, "id", None) != "PointReq":
                    continue
                prompt = (str(call.args[0].value)
                          if call.args and isinstance(call.args[0],
                                                      ast.Constant) else "")
                reqs.append((prompt,
                             {k.arg for k in call.keywords if k.arg},
                             sub.lineno))
            if reqs:
                out.append((os.path.basename(path), name, reqs))
    return out


def test_a_signed_drag_pins_the_cursor_to_the_line_it_measures():
    """`signed_along` throws away everything sideways to its direction, so a
    cursor that wanders off that line still reports a number — one that has
    nothing to do with where the user is pointing, and does not match the
    rubber band drawn for them.

    Signed distances therefore have to be axis-locked: then the point the
    command gets is the point on the line the user can see.
    """
    offenders = []
    for fname, cmd, reqs in _commands_using("signed_along"):
        for prompt, kwargs, line in reqs:
            if "number_from" in kwargs and "axis_lock" not in kwargs:
                offenders.append(f"  {fname}:{line}  {cmd}: {prompt!r}")
    assert not offenders, (
        "these measure along a direction but let the cursor leave it:\n"
        + "\n".join(offenders)
        + "\n\nPass the same (base, direction) as axis_lock=, or read the "
          "distance with dragging.distance_from() instead, which does not "
          "care which way the cursor went.")
