"""A test's windows go when the test does.

A MainWindow is never freed on its own: its menus, panes and tab row are
wired to lambdas that hold the window, and Qt keeps those connections
where Python's garbage collector cannot see them. The app has one window
for its whole life, so it never mattered there. A CI worker builds
hundreds, about 95 MB each, and one reached 6 GB and was killed for it.
conftest deletes the windows a test leaves behind.

The second test checks on the first, so it only means something when
both run in the same process; under xdist they may not, and it skips.
"""

from __future__ import annotations

import gc
import weakref

import pytest

from serpentine3d.app import MainWindow

_left: list[weakref.ref] = []


def test_a_test_builds_windows_and_leaves_them():
    closed = MainWindow()
    closed.show()
    closed.mark_saved()
    closed.close()
    never_shown = MainWindow()
    _left.extend([weakref.ref(closed), weakref.ref(never_shown)])


def test_by_the_next_test_they_are_gone():
    if not _left:
        pytest.skip("the windows were built in another worker")
    gc.collect()
    assert [w() for w in _left] == [None, None]
