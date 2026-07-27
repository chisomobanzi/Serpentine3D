"""Import must say it is working, and stop when asked.

A set-design .3dm can take minutes. Without a signal the app looks hung, and
there is no way out but killing it — which is what happened with a 921 MB
fence file. So importers take a `progress` callback and abandon the work when
it says to.
"""

import pytest
import rhino3dm as r3

from serpentine3d import fileio
from serpentine3d.core.scene import Scene


def _boxes_3dm(path: str, n: int) -> str:
    """A .3dm with `n` brep boxes — several objects, so progress can move."""
    model = r3.File3dm()
    for i in range(n):
        box = r3.Box(r3.BoundingBox(r3.Point3d(i * 10, 0, 0),
                                    r3.Point3d(i * 10 + 5, 5, 5)))
        model.Objects.AddBrep(r3.Brep.CreateFromBox(box))
    assert model.Write(path, 8)
    return path


def test_progress_is_reported_while_importing(tmp_path):
    path = _boxes_3dm(str(tmp_path / "boxes.3dm"), 5)
    seen = []

    def progress(fraction, message):
        seen.append((fraction, message))
        return True

    fileio.import_file(Scene(), path, progress=progress)

    assert len(seen) >= 5, f"only {len(seen)} updates for 5 objects"
    fractions = [f for f, _ in seen]
    assert fractions == sorted(fractions), "progress went backwards"
    assert all(0.0 <= f <= 1.0 for f in fractions), fractions
    assert all(m for _, m in seen), "an update carried no message"


def test_returning_false_cancels_the_import(tmp_path):
    path = _boxes_3dm(str(tmp_path / "boxes.3dm"), 5)
    calls = {"n": 0}

    def progress(fraction, message):
        calls["n"] += 1
        return calls["n"] < 2               # cancel on the second update

    scene = Scene()
    with pytest.raises(fileio.Cancelled):
        fileio.import_file(scene, path, progress=progress)

    assert calls["n"] == 2, "kept working after cancel"
    assert scene.all() == [], "a cancelled import left objects behind"


def test_cancelling_leaves_the_scene_exactly_as_it_was(tmp_path):
    """Cancel means "as you were", so callers can simply drop their undo
    checkpoint. That only holds if no importer half-fills the scene."""
    from serpentine3d.core import geometry

    scene = Scene()
    scene.add(geometry.make_box((0, 0, 0), 1, 1, 1), name="already here")
    before = [o.name for o in scene.all()]

    path = _boxes_3dm(str(tmp_path / "boxes.3dm"), 5)
    with pytest.raises(fileio.Cancelled):
        fileio.import_file(scene, path, progress=lambda f, m: False)

    assert [o.name for o in scene.all()] == before


def test_cancelling_at_the_very_end_does_not_discard_the_work(tmp_path):
    """Clicking Cancel as the last object lands would otherwise throw away a
    finished import — worse than ignoring the click."""
    path = _boxes_3dm(str(tmp_path / "boxes.3dm"), 3)
    scene = Scene()
    # let everything through, then refuse only the completion report
    assert fileio.import_file(scene, path,
                              progress=lambda f, m: f < 1.0) == 3
    assert len(scene.all()) == 3


def _one_brep_3dm(path: str) -> str:
    """A .3dm holding a single six-faced brep and nothing else."""
    model = r3.File3dm()
    box = r3.Box(r3.BoundingBox(r3.Point3d(0, 0, 0), r3.Point3d(5, 5, 5)))
    model.Objects.AddBrep(r3.Brep.CreateFromBox(box))
    assert model.Write(path, 8)
    return path


def test_progress_moves_inside_a_single_object(tmp_path):
    """One polysurface can be most of the file — the fence is 7921 faces in
    one object. Reporting only between objects would freeze the bar, and
    leave Cancel dead, for the whole import."""
    path = _one_brep_3dm(str(tmp_path / "one.3dm"))
    seen = []
    fileio.import_file(Scene(), path,
                       progress=lambda f, m: seen.append(f) or True)

    assert [f for f in seen if 0.0 < f < 1.0], \
        f"progress never moved inside the object: {seen}"


def test_cancel_inside_an_object_stops_that_object(tmp_path):
    path = _one_brep_3dm(str(tmp_path / "one.3dm"))
    calls = {"n": 0}

    def progress(fraction, message):
        calls["n"] += 1
        return fraction == 0.0              # cancel once real work starts

    scene = Scene()
    with pytest.raises(fileio.Cancelled):
        fileio.import_file(scene, path, progress=progress)
    assert scene.all() == []


def _one_mesh_3dm(path: str, faces: int) -> str:
    """A .3dm holding a single mesh of `faces` triangles."""
    model = r3.File3dm()
    mesh = r3.Mesh()
    for i in range(faces + 2):
        mesh.Vertices.Add(float(i), float(i % 7), 0.0)
    for i in range(faces):
        mesh.Faces.AddFace(i, i + 1, i + 2)
    model.Objects.AddMesh(mesh, None)
    assert model.Write(path, 8)
    return path


def test_progress_moves_inside_a_large_mesh(tmp_path):
    """Meshes are converted a face at a time in Python — the fence's biggest
    is 1.6 million faces, 21 seconds in one opaque call. A frozen bar for 21
    seconds is the complaint this whole change exists to answer."""
    path = _one_mesh_3dm(str(tmp_path / "mesh.3dm"), 5000)
    seen = []
    fileio.import_file(Scene(), path,
                       progress=lambda f, m: seen.append(f) or True)

    assert [f for f in seen if 0.0 < f < 1.0], \
        f"progress never moved inside the mesh: {seen}"


def test_cancel_inside_a_mesh_stops_it(tmp_path):
    path = _one_mesh_3dm(str(tmp_path / "mesh.3dm"), 5000)
    calls = {"n": 0}

    def progress(fraction, message):
        calls["n"] += 1
        return fraction == 0.0              # cancel once real work starts

    scene = Scene()
    with pytest.raises(fileio.Cancelled):
        fileio.import_file(scene, path, progress=progress)
    assert scene.all() == []


def test_a_mesh_does_not_report_once_per_face(tmp_path):
    """Reporting per face would cost more than the conversion: the fence has
    9.6 million mesh faces. Updates are per chunk, so their number stays
    bounded however big the mesh gets."""
    path = _one_mesh_3dm(str(tmp_path / "mesh.3dm"), 5000)
    seen = []
    fileio.import_file(Scene(), path,
                       progress=lambda f, m: seen.append(f) or True)

    assert len(seen) < 200, f"{len(seen)} updates for a 5000-face mesh"


def test_import_without_a_callback_is_unchanged(tmp_path):
    path = _boxes_3dm(str(tmp_path / "boxes.3dm"), 3)
    scene = Scene()
    assert fileio.import_file(scene, path) == 3


def test_throttling_spares_the_ui_without_hiding_the_end():
    """Repainting once per face would cost more than importing the fence.
    The first update must still land (so the dialog appears at once) and so
    must completion (so the bar doesn't stop at 98%)."""
    now = [0.0]
    seen = []
    tick = fileio.throttled(lambda f, m: seen.append(f) or True,
                            interval=0.1, clock=lambda: now[0])

    tick(0.0, "start")
    for i in range(1, 100):                 # a burst inside one interval
        now[0] += 0.001
        tick(i / 100, "working")
    now[0] += 1.0
    tick(1.0, "done")

    assert seen[0] == 0.0, "the first update was swallowed"
    assert seen[-1] == 1.0, "completion was swallowed"
    assert len(seen) < 10, f"{len(seen)} repaints for 100 updates"


def test_throttling_never_swallows_a_cancel():
    """A skipped update must not be reported as 'user cancelled'."""
    tick = fileio.throttled(lambda f, m: False, interval=1e9,
                            clock=lambda: 0.0)
    assert tick(0.0, "start") is False      # first call reaches the callback
    assert tick(0.5, "working") is not False   # skipped: no verdict to give


def test_the_window_shows_a_dialog_and_honours_its_cancel(tmp_path):
    """The whole point, wired end to end: Open puts up a cancellable dialog,
    and pressing Cancel stops the import and leaves the scene alone."""
    from PySide6.QtWidgets import QApplication, QProgressDialog

    from serpentine3d import app as app_mod

    path = _boxes_3dm(str(tmp_path / "boxes.3dm"), 60)
    win = app_mod.MainWindow()
    try:
        seen = {}

        def find_dialog():
            for w in QApplication.instance().topLevelWidgets():
                if isinstance(w, QProgressDialog) and w.isVisible():
                    return w
            return None

        # The dialog deliberately waits before appearing, so poll for it from
        # inside the import rather than guessing when it shows up.
        from PySide6.QtCore import QTimer

        poll = QTimer()
        poll.setInterval(50)

        def try_cancel():
            dlg = find_dialog()
            if dlg is not None:
                seen["label"] = dlg.labelText()
                dlg.cancel()
                poll.stop()

        poll.timeout.connect(try_cancel)
        poll.start()
        try:
            win._open_path(path)
        finally:
            poll.stop()

        assert seen.get("label"), "no progress dialog was ever shown"
        assert win.scene.all() == [], "cancelled open still loaded objects"
        assert find_dialog() is None, "the dialog outlived the import"
    finally:
        win.mark_saved()
        win.close()


def test_the_progress_dialog_is_not_tethered_to_the_main_window(tmp_path):
    """Under GNOME's attach-modal-dialogs a DIALOG-type window is glued to its
    parent: dragging it drags the main window with it. Every other dialog here
    dodges that by asking for a NORMAL window type, and so must this one."""
    import sys

    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import QApplication, QProgressDialog

    from serpentine3d import app as app_mod

    if not sys.platform.startswith("linux"):
        pytest.skip("attach-modal-dialogs is a GNOME/Linux behaviour")

    path = _boxes_3dm(str(tmp_path / "boxes.3dm"), 60)
    win = app_mod.MainWindow()
    try:
        seen = {}

        def look():
            for w in QApplication.instance().topLevelWidgets():
                if isinstance(w, QProgressDialog) and w.isVisible():
                    seen["type"] = w.windowType()
                    w.cancel()
                    poll.stop()

        poll = QTimer()
        poll.setInterval(50)
        poll.timeout.connect(look)
        poll.start()
        try:
            win._open_path(path)
        finally:
            poll.stop()

        assert seen, "no progress dialog was ever shown"
        assert seen["type"] == Qt.WindowType.Window, \
            f"tethered: window type is {seen['type']}"
    finally:
        win.mark_saved()
        win.close()


def test_every_format_reports_something(tmp_path):
    """Whatever the format, the caller gets a start and a finish — a dialog
    that only appears for .3dm is worse than one that always appears."""
    from serpentine3d.core import geometry

    scene = Scene()
    scene.add(geometry.make_box((0, 0, 0), 1, 1, 1), name="box")
    for ext in (".serp", ".step", ".obj", ".stl"):
        path = str(tmp_path / f"x{ext}")
        fileio.export_file(scene, path)
        seen = []
        fileio.import_file(Scene(), path,
                           progress=lambda f, m: seen.append((f, m)) or True)
        assert seen, f"{ext} reported no progress at all"
        assert seen[-1][0] == 1.0, f"{ext} never reported completion"
