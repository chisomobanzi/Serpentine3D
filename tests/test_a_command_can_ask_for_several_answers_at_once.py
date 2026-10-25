"""A command can ask for several answers as one thing (#45).

Hatch wants a popup with pattern, spacing and angle visible together
rather than three prompts in a row. Commands never touch Qt, so what a
command yields is a FormReq: the fields it wants, each an ordinary
request. A window shows them as one popup and answers the lot with
`provide_form`; anything without a window, which is every script, macro,
journal replay and MCP call, is asked them one after another exactly as
before.

That is the point of doing it this way: nothing that already answers
these prompts has to learn anything new.
"""

from __future__ import annotations

import pytest

from serpentine3d.commands.base import (FormField, FormReq, NumberReq,
                                        OptionReq, command, resolve)


@pytest.fixture
def asked(env):
    """A throwaway command that asks for two things at once."""
    scene, _sel, _hist, ctx, proc = env
    seen = {}

    @command("formprobe")
    def _cmd(ctx):
        seen["answers"] = yield FormReq(
            "Probe", title="Probe",
            fields=(FormField("pattern",
                              OptionReq("Pattern",
                                        options=["Lines", "Solid"],
                                        default="Lines")),
                    FormField("spacing",
                              NumberReq("Line spacing", default=1.0,
                                        minimum=0.1),
                              when=lambda a: a["pattern"] != "Solid")))
        ctx.echo("probed")

    yield proc, seen
    from serpentine3d.commands.base import _REGISTRY
    _REGISTRY.pop("formprobe", None)


def test_without_a_window_the_fields_are_asked_one_after_another(asked):
    proc, seen = asked

    proc.run("formprobe")
    assert proc.request.prompt == "Pattern"
    proc.provide_text("Lines")
    assert proc.request.prompt == "Line spacing"
    proc.provide_text("2.5")

    assert seen["answers"] == {"pattern": "Lines", "spacing": 2.5}
    assert not proc.busy


def test_a_field_that_does_not_apply_is_not_asked_for(asked):
    """A solid pattern has no line spacing, so the prompt that would ask
    for one is skipped and its default stands."""
    proc, seen = asked

    proc.run("formprobe")
    proc.provide_text("Solid")

    assert not proc.busy, "it asked for a spacing a solid hatch has no use for"
    assert seen["answers"] == {"pattern": "Solid", "spacing": 1.0}


def test_a_window_answers_the_whole_form_at_once(asked):
    proc, seen = asked

    proc.run("formprobe")
    assert isinstance(proc.form, FormReq)
    assert [f.name for f in proc.form.fields] == ["pattern", "spacing"]
    proc.provide_form({"pattern": "Solid", "spacing": 0.25})

    assert seen["answers"] == {"pattern": "Solid", "spacing": 0.25}
    assert not proc.busy
    assert proc.form is None


def test_a_form_the_popup_half_fills_keeps_the_defaults(asked):
    proc, seen = asked

    proc.run("formprobe")
    proc.provide_form({"spacing": 3.0})

    assert seen["answers"] == {"pattern": "Lines", "spacing": 3.0}


def test_the_fields_already_answered_stand_if_a_popup_finishes_the_rest(asked):
    proc, seen = asked

    proc.run("formprobe")
    proc.provide_text("Lines")          # answered as a prompt
    proc.provide_form({})               # then the window took over

    assert seen["answers"]["pattern"] == "Lines"
    assert seen["answers"]["spacing"] == 1.0


def test_cancelling_mid_form_leaves_nothing_behind(asked):
    proc, _seen = asked

    proc.run("formprobe")
    proc.cancel()

    assert proc.form is None and not proc.busy


def test_the_command_is_the_one_that_decides_to_ask_this_way(asked):
    """A command that never yields a form has no form, and the processor
    is unchanged for it."""
    proc, _seen = asked
    assert proc.form is None
    assert resolve("formprobe") is not None
