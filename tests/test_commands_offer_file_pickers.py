"""Path-taking commands use one predictable window-owned file chooser.

The command generators still own when a path is needed and what kind of file
it is.  A live MainWindow turns that request into a chooser; typed commands,
headless runs and API automation can keep answering the same request as text.
"""

from __future__ import annotations

import os

import pytest
from PySide6.QtGui import QColor, QImage

from serpentine3d import fileio
from serpentine3d.api import SerpApi
from serpentine3d.commands.base import PointReq, TextReq
from serpentine3d.core import geometry as g
from serpentine3d.core.layout import Layout


# command, setup, answers before the path, save?, title word, filter globs,
# expected default-name kind
CASES = [
    ("open", "plain", (), False, "open", ("*.serp", "*.3dm"), "none"),
    ("import", "plain", (), False, "import", ("*.step", "*.obj"), "none"),
    ("save", "plain", (), True, "save", ("*.serp", "*.3dm"), "native"),
    ("export", "plain", ("",), True, "export", ("*.serp", "*.step"),
     "export"),
    ("pictureframe", "picture", ("",), False, "picture",
     ("*.png", "*.jpg", "*.jpeg"), "none"),
    ("exportpdf", "multi_sheet", ("",), True, "pdf", ("*.pdf",),
     "sheets.pdf"),
    ("exportdxf", "sheet", (), True, "dxf", ("*.dxf",),
     "Picker Sheet.dxf"),
    ("exportsvg", "sheet", (), True, "svg", ("*.svg",),
     "Picker Sheet.svg"),
    ("viewcapturetofile", "plain", (), True, "capture",
     ("*.png", "*.jpg", "*.jpeg"), "viewport.png"),
    ("turntable", "model", ("", ""), True, "turntable", ("*.mp4",),
     "turntable"),
    ("turntableui", "plain", ("",), True, "turntable", ("*.mp4",),
     "turntable"),
]


@pytest.fixture
def window():
    from serpentine3d.app import MainWindow

    win = MainWindow()
    try:
        yield win
    finally:
        if win.processor.busy:
            win.processor.cancel()
        win.mark_saved()
        win.close()


def _prepare(win, kind):
    if kind == "model":
        win.scene.add(g.make_box((0, 0, 0), 10, 10, 10))
    elif kind in ("sheet", "multi_sheet"):
        layout = win._new_sheet("A3")
        layout.name = "Picker Sheet"
        if kind == "multi_sheet":
            win.scene.layouts.append(Layout(name="Other Sheet"))
            win.scene.notify()
    elif kind == "picture":
        # Force the Add/RemoveAll prompt so the picker timing is covered too.
        win.scene.image_planes.append({"path": "already-there.png"})


def _assert_default(kind, name):
    basename = os.path.basename(os.path.expanduser(name)) if name else ""
    if kind == "none":
        assert not name
    elif kind == "native":
        assert basename.endswith(".serp")
    elif kind == "export":
        assert basename and os.path.splitext(basename)[1].lower() \
            in fileio.EXPORT_EXTS
    elif kind == "turntable":
        assert basename.startswith("serpentine-turntable-")
        assert basename.endswith(".mp4")
    else:
        assert basename == kind


@pytest.mark.parametrize(
    "command,setup,answers,save,title_word,globs,default_kind", CASES)
def test_live_path_commands_offer_one_picker_at_the_path_step(
        window, monkeypatch, command, setup, answers, save, title_word, globs,
        default_kind):
    _prepare(window, setup)
    revision = window.scene.revision
    picture_count = len(window.scene.image_planes)
    calls = []
    messages = []
    window.ctx.add_echo_listener(messages.append)

    def cancel_picker(*, save, title, name="", filters=""):
        calls.append({"save": save, "title": title, "name": name,
                      "filters": filters})
        return ""

    monkeypatch.setattr(window, "_pick_file", cancel_picker)

    window.run_command(command)
    for answer in answers:
        assert not calls, "picker opened before the command reached its path"
        window.processor.provide_text(answer)

    assert len(calls) == 1
    call = calls[0]
    assert call["save"] is save
    assert title_word in call["title"].lower()
    assert all(glob in call["filters"] for glob in globs)
    _assert_default(default_kind, call["name"])
    assert not window.processor.busy
    assert window.scene.revision == revision
    assert len(window.scene.image_planes) == picture_count
    assert not any(message.lower().startswith(("error", "command failed"))
                   for message in messages)


def test_a_chosen_picture_path_reaches_the_corner_step(
        window, monkeypatch, tmp_path):
    path = tmp_path / "reference.png"
    image = QImage(8, 4, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    assert image.save(str(path))
    calls = []

    def choose_picture(**kwargs):
        calls.append(kwargs)
        return str(path)

    monkeypatch.setattr(window, "_pick_file", choose_picture)

    window.run_command("pictureframe")

    assert len(calls) == 1
    assert isinstance(window.processor.request, PointReq)
    assert window.processor.request.prompt == "First corner"
    assert window.scene.image_planes == []


@pytest.mark.parametrize(
    "command,setup,answers,_save,_title_word,_globs,_default_kind", CASES)
def test_headless_path_commands_leave_a_typed_request(
        window, monkeypatch, tmp_path, command, setup, answers, _save,
        _title_word, _globs, _default_kind):
    monkeypatch.chdir(tmp_path)
    _prepare(window, setup)
    calls = []

    def forbidden_picker(**kwargs):
        calls.append(kwargs)
        raise AssertionError("headless command opened a file chooser")

    monkeypatch.setattr(window, "_pick_file", forbidden_picker)

    window.run_command(f"{command} --headless")
    for answer in answers:
        window.processor.provide_text(answer)

    assert not calls
    assert window.processor.busy
    assert isinstance(window.processor.request, TextReq)
    prompt = window.processor.request.prompt.lower()
    assert "path" in prompt or "file" in prompt


def test_api_command_never_opens_a_picker(window, monkeypatch, tmp_path):
    target = tmp_path / "automated.step"
    exported = []

    def forbidden_picker(**_kwargs):
        raise AssertionError("SerpApi automation opened a file chooser")

    def record_export(_scene, path, **kwargs):
        exported.append((path, kwargs))

    monkeypatch.setattr(window, "_pick_file", forbidden_picker)
    monkeypatch.setattr(fileio, "export_file", record_export)

    SerpApi(window).command("export", inputs=["All", str(target)])

    assert exported and exported[0][0] == str(target)
    assert not window.processor.busy
