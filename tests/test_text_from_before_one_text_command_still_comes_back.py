"""`textobject` and `textcurves` were the model's text commands until
0.13.0 made `text` the one command (#142). They still run it, so scripts
written for them work, and a session journal recorded by 0.12.5 still
recovers its text: a journal step whose command is unknown is skipped, so
without them a crash before an upgrade lost every text it had placed.

tests/data/journal_0125_textobject.jsonl was recorded by 0.12.5 itself:
editable text placed with the editor and then edited, a line, and text
turned into its letter outlines.
"""

from pathlib import Path

import pytest

from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core.history import History
from serpentine3d.core.replay import Replayer, load_events
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager
from serpentine3d.core.text import TextShape

DATA = Path(__file__).parent / "data"


def test_a_0_12_5_journal_that_placed_text_recovers_it():
    replay = Replayer(load_events(str(DATA / "journal_0125_textobject.jsonl")))
    replay.run()
    assert not replay.proc.busy
    objects = replay.scene.all()
    texts = [o for o in objects if isinstance(o.shape, TextShape)]
    assert [t.shape.text for t in texts] == ["BOR"]
    assert sorted(o.kind for o in objects if o not in texts) == \
        ["curve"] * 6, "the line, and AB as five letter outlines"


def _scripted(name):
    """What a script typing BOR at 10,20,0, 7 high, makes with `name`."""
    scene = Scene()
    proc = CommandProcessor(CommandContext(scene, SelectionManager(scene),
                                           History(scene)))
    proc.run(name)
    for answer in ("BOR", "10,20,0", "7"):
        proc.provide_text(answer)
    assert not proc.busy
    return sorted((o.kind, tuple(round(v, 6) for p in o.bbox() for v in p))
                  for o in scene.all())


@pytest.mark.parametrize("name", ["textobject", "textcurves"])
def test_the_old_names_make_what_text_makes(name):
    made = _scripted(name)
    # how many outlines B, O and R make is the font's business (seven
    # here, six on macOS); that the old name makes the same is the test's
    assert made and made == _scripted("text")
