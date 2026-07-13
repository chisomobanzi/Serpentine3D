import json
import os

import pytest

from serpentine3d.core import geometry as g
from serpentine3d.core.scene import Scene
from serpentine3d.utils.autosave import AutosaveManager


def test_autosave_and_recovery_cycle(tmp_path):
    d = str(tmp_path)
    scene = Scene()
    scene.add(g.make_box((0, 0, 0), 2, 2, 2), name="Crash Box")
    mgr = AutosaveManager(scene, d)
    assert os.path.exists(mgr.lock_path)

    assert mgr.maybe_autosave() is True
    assert os.path.exists(mgr.autosave_path)
    assert mgr.maybe_autosave() is False       # unchanged -> skipped
    scene.add(g.make_sphere((5, 0, 0), 1))
    assert mgr.maybe_autosave() is True

    # simulate a crash: fake a dead session's lockfile
    stale_lock = os.path.join(d, "session-999999.json")
    stale_save = os.path.join(d, "autosave-999999.serp")
    os.rename(mgr.autosave_path, stale_save)
    with open(stale_lock, "w") as f:
        json.dump({"pid": 999999, "autosave": stale_save,
                   "doc_path": "/tmp/mydoc.serp"}, f)

    # a fresh session finds and recovers it
    scene2 = Scene()
    mgr2 = AutosaveManager(scene2, d)
    found = mgr2.find_recoverable()
    assert len(found) == 1
    assert found[0]["doc_path"] == "/tmp/mydoc.serp"
    doc = mgr2.recover(found[0])
    assert doc == "/tmp/mydoc.serp"
    assert len(scene2.all()) == 2
    assert scene2.find_by_name("Crash Box") is not None
    assert not os.path.exists(stale_lock)
    # the recovered state was immediately re-protected
    assert os.path.exists(mgr2.autosave_path)

    # live sessions are never offered
    assert mgr2.find_recoverable() == []


def test_clean_exit_removes_files(tmp_path):
    scene = Scene()
    scene.add(g.make_box((0, 0, 0), 1, 1, 1))
    mgr = AutosaveManager(scene, str(tmp_path))
    mgr.autosave_now()
    mgr.clean_exit()
    assert not os.path.exists(mgr.lock_path)
    assert not os.path.exists(mgr.autosave_path)


def test_stale_lock_without_autosave_is_cleaned(tmp_path):
    d = str(tmp_path)
    with open(os.path.join(d, "session-888888.json"), "w") as f:
        json.dump({"pid": 888888, "autosave": os.path.join(d, "gone.serp")},
                  f)
    mgr = AutosaveManager(Scene(), d)
    assert mgr.find_recoverable() == []
    assert not os.path.exists(os.path.join(d, "session-888888.json"))
