"""Starting a helper process must not start a second app.

The .3dm importer spawns a reader process, and spawn re-imports the parent's
`__main__` in the child under the name `__mp_main__`. An entry point that
calls main() at import time would therefore open a whole new window for every
import — and `python -m serpentine3d` did exactly that.
"""

import runpy

import pytest


@pytest.fixture
def launched(monkeypatch):
    """Records whether the entry point tried to start the app."""
    calls = []
    monkeypatch.setattr("serpentine3d.launcher.main",
                        lambda: calls.append(True) or 0)
    return calls


def test_the_module_entry_launches_nothing_in_a_spawned_child(launched):
    """`runpy` under `__mp_main__` is precisely what spawn does."""
    runpy.run_module("serpentine3d.__main__", run_name="__mp_main__")
    assert launched == [], "the entry point launched the app in a helper"


def test_the_module_entry_still_runs_the_app_when_run_directly(launched):
    with pytest.raises(SystemExit):
        runpy.run_module("serpentine3d.__main__", run_name="__main__")
    assert launched == [True]
