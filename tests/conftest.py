import pytest

import serpentine3d.commands  # registers all commands  # noqa: F401


@pytest.fixture(scope="session", autouse=True)
def _qapp():
    """A full QApplication before anything creates a QGuiApplication
    (core/text.py would otherwise block widget construction later)."""
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])
from serpentine3d.commands.base import CommandContext, CommandProcessor
from serpentine3d.core.history import History
from serpentine3d.core.scene import Scene
from serpentine3d.core.selection import SelectionManager


@pytest.fixture
def env():
    scene = Scene()
    selection = SelectionManager(scene)
    history = History(scene)
    ctx = CommandContext(scene, selection, history)
    proc = CommandProcessor(ctx)
    return scene, selection, history, ctx, proc


class StubLayoutView:
    """Just enough of ui.layout_view for headless drafting commands."""

    def __init__(self):
        self.entered_detail = None

    def _entered(self):
        return None


class StubViewport:
    def __init__(self, space: str):
        from serpentine3d.core.cplane import CPlane
        self.space = space          # a layout id puts commands on that sheet
        self.layout_view = StubLayoutView()
        self.cplane = CPlane()
