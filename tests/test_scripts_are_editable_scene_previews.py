"""Run editable Python on a drawing, review it, and keep one undoable change.

These tests use the real workspace, Document/geometry API, file formats and
Agent. Only file dialogs and the assistant's client are faked. Rendering of
the preview/gutter is checked separately in a native OpenGL session.
"""

from __future__ import annotations

import re
import time

import pytest
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QComboBox, QDialog, QFileDialog, QLabel,
    QPlainTextEdit, QTabBar, QTextEdit, QWidget,
)

from serpentine3d.app import MainWindow
from serpentine3d.core import geometry as geo
from serpentine3d.fileio.native import load_scene, save_scene


BOX = 'doc.add(geo.make_box((0, 0, 0), 2, 3, 4), name="Script box")\n'


@pytest.fixture
def windows(tmp_path, monkeypatch):
    monkeypatch.setenv("SERP3D_CONFIG", str(tmp_path / "settings.json"))
    monkeypatch.setenv("SERP3D_NO_RECOVER", "1")
    opened = []

    def create():
        win = MainWindow()
        opened.append(win)
        win.resize(1400, 900)
        win.command_workspace.set_pane_visible("script", True)
        _layout(win)
        return win

    yield create
    for win in opened:
        # A failed assertion during a run must not strand a Python worker.
        stop = _control(_pane(win), "Stop", required=False)
        if stop is not None and stop.isEnabled():
            _trigger(stop)
            QTest.qWait(100)
        win.processor.cancel()
        win.mark_saved()
        win.close()
    QApplication.processEvents()


@pytest.fixture
def win(windows):
    return windows()


def _layout(win):
    shelf = win._cmd_dock.widget()
    shelf.resize(1200, 430)
    for widget in [shelf, *shelf.findChildren(QWidget)]:
        if widget.layout() is not None:
            widget.layout().activate()
    QApplication.processEvents()


def _pane(win):
    return win.command_workspace.script_pane


def _label(value):
    return value.replace("&", "").replace("…", "").strip(" .").lower()


def _control(parent, label, *, required=True):
    target = _label(label)
    matches = [button for button in parent.findChildren(QAbstractButton)
               if button.isVisibleTo(parent)
               and target in {_label(button.text()),
                              _label(button.accessibleName()),
                              _label(button.toolTip())}]
    if not matches:
        matches = [action for action in parent.findChildren(QAction)
                   if _label(action.text()) == target]
    if required:
        assert matches, f"The Script pane needs a {label!r} control"
    return matches[0] if matches else None


def _trigger(control):
    if isinstance(control, QAction):
        control.trigger()
    else:
        control.click()
    QApplication.processEvents()


def _click(win, label):
    control = _control(_pane(win), label)
    assert control.isEnabled(), f"The Script {label!r} control is unavailable"
    _trigger(control)


def _editor(win):
    editors = [widget for widget in _pane(win).findChildren(QWidget)
               if isinstance(widget, (QPlainTextEdit, QTextEdit))
               and not widget.isReadOnly() and widget.isVisibleTo(_pane(win))]
    assert len(editors) == 1, (
        "Script must provide one active editable multiline Python source "
        "document; the existing single-line console is insufficient")
    return editors[0]


def _wait(predicate, message, seconds=6):
    until = time.monotonic() + seconds
    while time.monotonic() < until and not predicate():
        QTest.qWait(10)
    assert predicate(), message


def _history(win):
    return win.command_line.echo_view.toPlainText()


def _state(win):
    return (win.scene.units, tuple(sorted(
        (obj.id, obj.name, obj.kind, obj.layer_id, obj.visible, obj.locked,
         tuple(round(v, 5) for corner in geo.bbox(obj.shape) for v in corner),
         round(geo.volume(obj.shape), 5), str(obj.color))
        for obj in win.scene.all())))


def _preview(win, source=None):
    if source is not None:
        _editor(win).setPlainText(source)
    _click(win, "Run")
    _wait(lambda: _control(_pane(win), "Keep").isEnabled(),
          "A successful script must offer a preview to Keep or Discard.\n"
          + _history(win))


def _save(win, path, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        lambda *args, **kwargs: (str(path), "Python (*.py)"))
    _click(win, "Save")
    assert path.exists(), "Save must write a Python file"


def _open(win, path, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        lambda *args, **kwargs: (str(path), "Python (*.py)"))
    _click(win, "Open")


def _find_draft(win, source):
    """Allow either separate editor pages or one editor with a draft selector."""
    if _editor(win).toPlainText() == source:
        return _editor(win)
    selectors = (_pane(win).findChildren(QTabBar)
                 + _pane(win).findChildren(QComboBox))
    for selector in selectors:
        for index in range(selector.count()):
            selector.setCurrentIndex(index)
            QApplication.processEvents()
            if _editor(win).toPlainText() == source:
                return _editor(win)
    pytest.fail("Earlier Python source must remain accessible as a separate draft")


def _guide(win):
    guide = win.scene.add(geo.make_interp_curve(
        [(0, 0, 0), (20, 8, 0), (45, -5, 0), (75, 10, 0)]), name="Guide")
    win.selection.set([guide.id])
    return guide


def _ribs(count):
    return (f"count = {count}\n"
            "assert len(selected) == 1\n"
            "guide = doc.get(selected[0].id)\n"
            "assert guide.name == 'Guide'\n"
            "for i, point in enumerate(geo.sample_curve(guide.shape, count)):\n"
            "    doc.add(geo.make_box(point, 1, 3, 8), name=f'Rib {i}')\n")


def test_script_has_a_real_editor_controls_syntax_and_line_number_affordance(win):
    editor = _editor(win)
    for label in ("New", "Open", "Save", "Run", "Stop", "Keep", "Discard",
                  "Help", "Examples"):
        _control(_pane(win), label)
    editor.setPlainText("# editable Python\nfor i in range(3):\n    print(i)\n")
    QTest.qWait(30)
    blocks = [editor.document().findBlockByNumber(n) for n in range(3)]
    assert any(block.layout().formats() for block in blocks), \
        "Python source must distinguish syntax visually"
    assert any("line" in (widget.accessibleName() + widget.toolTip()).lower()
               and "number" in (widget.accessibleName() + widget.toolTip()).lower()
               for widget in _pane(win).findChildren(QWidget)), \
        "The line-number gutter must be identifiable to users and assistive tools"
    win._toggle_console()
    win._toggle_console()
    assert _editor(win).toPlainText() == "# editable Python\nfor i in range(3):\n    print(i)\n"


def test_new_open_and_save_preserve_exact_source_and_separate_drafts(win, tmp_path, monkeypatch):
    original = "# My unfinished façade\nwidth = 2\n\n" + BOX
    _editor(win).setPlainText(original)
    _click(win, "New")
    assert _editor(win).toPlainText() != original
    _editor(win).setPlainText("# A second draft\n" + BOX)
    _find_draft(win, original)
    first = tmp_path / "my façade.py"
    _save(win, first, monkeypatch)
    assert first.read_text(encoding="utf-8") == original
    external = tmp_path / "external.py"
    external.write_text("# external\nanswer = 'α'\n\n", encoding="utf-8")
    _open(win, external, monkeypatch)
    assert _editor(win).toPlainText() == external.read_text(encoding="utf-8")
    changed = "# external\nanswer = 'β'\n\n"
    _editor(win).setPlainText(changed)
    _click(win, "Save")
    assert external.read_text(encoding="utf-8") == changed
    assert first.read_text(encoding="utf-8") == original
    assert _find_draft(win, original).toPlainText() == original


def test_run_uses_current_document_units_selection_and_stages_one_undoable_change(win):
    source = win.scene.add(geo.make_box((10, 0, 0), 5, 5, 5), name="Input")
    win.scene.units = "cm"
    win.selection.set([source.id])
    before = _state(win)
    code = ("assert doc.scene.units == 'cm'\n"
            "assert len(selected) == 1 and selected[0].name == 'Input'\n"
            "assert doc.get(selected[0].id).name == 'Input'\n"
            "doc.remove('Input')\n" + BOX +
            "doc.run('circle', ['0,0,20', '5'])\n"
            "print('two staged objects')\n")
    _preview(win, code)
    assert _state(win) == before, "Run must leave live geometry intact until Keep"
    assert not win.history.can_undo, "Preview must not add model undo entries"
    _click(win, "Keep")
    assert len(win.scene.all()) == 2
    assert win.scene.get(source.id) is None
    assert geo.volume(win.scene.find_by_name("Script box").shape) == pytest.approx(24)
    assert any(obj.kind == "curve" for obj in win.scene.all())
    assert "script" in _history(win).lower() and "two staged objects" in _history(win)
    assert win.history.undo() is not None
    assert _state(win) == before
    assert not win.history.can_undo, "All script changes must be one undo operation"
    assert win.history.redo() is not None
    assert len(win.scene.all()) == 2


def test_discard_preserves_scene_and_history_and_the_script_can_run_again(win):
    _guide(win)
    before = _state(win)
    _preview(win, "doc.get('Guide').name = 'Changed only in preview'\n" + BOX)
    assert _state(win) == before
    _click(win, "Discard")
    assert _state(win) == before and not win.history.can_undo
    _preview(win, BOX)
    _click(win, "Keep")
    assert win.scene.find_by_name("Guide") is not None
    assert win.scene.find_by_name("Script box") is not None


def test_python_exception_is_atomic_and_identifies_the_saved_file_and_line(win, tmp_path, monkeypatch):
    _guide(win)
    before = _state(win)
    code = "doc.remove('Guide')\n" + BOX + "raise ValueError('broken rib')\n"
    _editor(win).setPlainText(code)
    path = tmp_path / "failed_ribs.py"
    _save(win, path, monkeypatch)
    _click(win, "Run")
    _wait(lambda: "broken rib" in _history(win), "Python errors must reach command history")
    history = _history(win)
    assert "failed_ribs.py" in history and re.search(r"(?:line\s+3|:3\b)", history)
    assert "script" in history.lower() and "ValueError" in history
    assert _state(win) == before and not win.history.can_undo
    assert not _control(_pane(win), "Keep").isEnabled()


def test_rerun_replaces_its_outputs_and_keeps_the_guide_selected(win):
    guide = _guide(win)
    other = win.scene.add(geo.make_box((200, 0, 0), 2, 2, 2), name="Unrelated")
    for count in (3, 7, 2):
        _preview(win, _ribs(count))
        _click(win, "Keep")
        made = [obj for obj in win.scene.all() if obj.id not in (guide.id, other.id)]
        assert len(made) == count, "Rerunning one script must replace its previous output"
        assert all(geo.is_valid(obj.shape) and geo.volume(obj.shape) > 0 for obj in made)
        assert win.scene.get(guide.id) is not None and win.scene.get(other.id) is not None
        assert win.selection.ids == [guide.id], "Keep must retain the script's selected inputs"
    win.history.undo()
    assert len(win.scene.all()) == 9, "Undoing a rerun must restore its prior outputs"


def test_ownership_survives_drawing_and_corresponding_python_file_reopen(windows, tmp_path, monkeypatch):
    win = windows()
    _guide(win)
    _editor(win).setPlainText(_ribs(3))
    path = tmp_path / "ribs.py"
    _save(win, path, monkeypatch)
    _preview(win)
    _click(win, "Keep")
    drawing = tmp_path / "ribs.serp"
    save_scene(win.scene, str(drawing))
    reopened = windows()
    load_scene(reopened.scene, str(drawing))
    reopened.selection.set([reopened.scene.find_by_name("Guide").id])
    _open(reopened, path, monkeypatch)
    _preview(reopened, _ribs(5))
    _click(reopened, "Keep")
    assert len(reopened.scene.all()) == 6, "Reopening a saved script must retain its output ownership"
    assert reopened.scene.find_by_name("Guide") is not None
    assert reopened.selection.ids == [reopened.scene.find_by_name("Guide").id]


def test_keep_waits_for_a_pending_cad_prompt_without_losing_the_preview(win):
    _editor(win).setPlainText(BOX)
    win.processor.run("line")
    win.processor.provide_text("1,2,3")
    request = win.processor.request
    points = list(win.processor.picked_points)
    win.command_line.input.setText("5,2,3")
    _preview(win)
    before_keep = _state(win)
    _click(win, "Keep")
    assert win.processor.busy and win.processor.request is request
    assert win.processor.picked_points == points
    assert win.command_line.input.text() == "5,2,3"
    assert _state(win) == before_keep, \
        "Keep must wait until the active CAD command releases its undo checkpoint"
    assert re.search(r"finish|cancel|pending|active command", _history(win), re.IGNORECASE)
    assert _control(_pane(win), "Keep").isEnabled(), "The waiting preview must remain available"
    win.processor.cancel()
    assert not win.processor.busy
    _click(win, "Keep")
    assert win.scene.find_by_name("Script box") is not None
    win.history.undo()
    assert win.scene.all() == [] and not win.history.can_undo


def test_keep_rejects_a_stale_preview_without_overwriting_new_user_work(win):
    _preview(win, BOX)
    win.scene.add(geo.make_box((90, 0, 0), 1, 1, 1), name="New user work")
    before_keep = _state(win)
    _click(win, "Keep")
    assert _state(win) == before_keep, "A stale preview must preserve newer user/AI work"
    assert not win.history.can_undo, "Rejecting a preview must not create an undo entry"
    assert re.search(r"changed|stale|run again|rerun", _history(win), re.IGNORECASE)


def test_stop_interrupts_a_python_loop_without_blocking_qt_and_allows_another_run(win):
    _guide(win)
    before = _state(win)
    # Bounded as a harness backstop: a broken Stop must fail, not hang pytest.
    code = ("import time\ndoc.remove('Guide')\n"
            "deadline = time.monotonic() + 3\n"
            "while time.monotonic() < deadline:\n    pass\n" + BOX)
    _editor(win).setPlainText(code)
    heartbeats = []
    timer = QTimer()
    timer.timeout.connect(lambda: heartbeats.append(time.monotonic()))
    timer.start(15)
    start = time.monotonic()
    try:
        _click(win, "Run")
        assert time.monotonic() - start < 0.5, "Run must return immediately to Qt"
        QTest.qWait(100)
        assert len(heartbeats) >= 2, "The event loop must continue while Python runs"
        assert _state(win) == before
        _click(win, "Stop")
        _wait(lambda: not _control(_pane(win), "Stop").isEnabled(),
              "Stop must interrupt the loop promptly", seconds=1)
    finally:
        timer.stop()
    assert _state(win) == before and not win.history.can_undo
    assert not _control(_pane(win), "Keep").isEnabled()
    _preview(win, BOX)
    _click(win, "Keep")
    assert win.scene.find_by_name("Script box") is not None


def test_closing_during_a_run_stops_and_discards_without_late_model_writes(win):
    _guide(win)
    before = _state(win)
    _editor(win).setPlainText(
        "import time\ndoc.remove('Guide')\n"
        "deadline = time.monotonic() + 1\n"
        "while time.monotonic() < deadline:\n    pass\n" + BOX)
    start = time.monotonic()
    _click(win, "Run")
    assert time.monotonic() - start < 0.5
    win.mark_saved()
    win.close()
    QTest.qWait(1200)
    assert _state(win) == before and not win.history.can_undo


def test_typing_enter_space_and_undo_belong_to_the_editor(win):
    win.history.checkpoint("Existing model operation")
    obj = win.scene.add(geo.make_box((0, 0, 0), 2, 2, 2), name="Existing")
    editor = _editor(win)
    editor.setPlainText("")
    editor.setFocus()
    QTest.keyClicks(editor, "width = 10")
    QTest.keyClick(editor, Qt.Key.Key_Return)
    QTest.keyClicks(editor, "# line box undo")
    assert "width = 10\n" in editor.toPlainText()
    assert not win.processor.busy
    assert win.scene.get(obj.id) is not None
    QTest.keyClick(editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert win.scene.get(obj.id) is not None and win.history.can_undo
    assert editor.toPlainText() != "width = 10\n# line box undo"


def _example(win, name):
    examples = _control(_pane(win), "Examples")
    menu = examples.menu() if hasattr(examples, "menu") else None
    candidates = list(menu.actions()) if menu is not None else _pane(win).findChildren(QAction)
    matches = [action for action in candidates if name in action.text().lower()]
    if not matches:
        matches = [button for button in _pane(win).findChildren(QAbstractButton)
                   if name in button.text().lower()]
    assert matches, f"Examples must offer a runnable {name} script"
    _trigger(matches[0])
    source = _editor(win).toPlainText()
    compile(source, f"{name}_example.py", "exec")
    return source


def test_offline_box_and_selected_guide_ribs_examples_are_editable_and_runnable(win):
    source = _example(win, "box")
    assert "doc." in source and "geo." in source
    _preview(win)
    _click(win, "Keep")
    box_outputs = {obj.id for obj in win.scene.all()}
    assert box_outputs and all(geo.is_valid(obj.shape) and geo.volume(obj.shape) > 0
                               for obj in win.scene.all())
    guide = _guide(win)
    source = _example(win, "rib")
    assert "selected" in source
    _preview(win)
    _click(win, "Keep")
    ribs = [obj for obj in win.scene.all() if obj.id not in box_outputs | {guide.id}]
    assert len(ribs) >= 2 and all(geo.is_valid(obj.shape) for obj in ribs)
    assert win.selection.ids == [guide.id]
    assert len({tuple(round(v, 2) for v in geo.centroid(obj.shape)) for obj in ribs}) > 1
    # Editing a normal numeric parameter, then rerunning, uses the same input.
    match = re.search(r"(?m)^(\w*count\w*\s*=\s*)(\d+)", source, re.IGNORECASE)
    assert match, "The ribs example needs an editable count parameter"
    changed = source[:match.start(2)] + "4" + source[match.end(2):]
    _preview(win, changed)
    _click(win, "Keep")
    assert len([obj for obj in win.scene.all()
                if obj.id not in box_outputs | {guide.id}]) == 4
    assert win.selection.ids == [guide.id]


def test_help_is_available_offline_and_describes_the_actual_script_globals(win, monkeypatch):
    _editor(win)
    captured = []
    urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl", lambda url: urls.append(url) or True)

    def collect():
        for top in QApplication.topLevelWidgets():
            if top is not win and not top.isVisible():
                continue
            for widget in [top, *top.findChildren(QWidget)]:
                if not widget.isVisibleTo(top):
                    continue
                if isinstance(widget, (QTextEdit, QPlainTextEdit)) and widget.isReadOnly():
                    captured.append(widget.toPlainText())
                elif isinstance(widget, QLabel):
                    captured.append(widget.text())
            if isinstance(top, QDialog) and top.isVisible():
                top.accept()

    timer = QTimer()
    timer.timeout.connect(collect)
    timer.start(20)
    try:
        _click(win, "Help")
        QTest.qWait(50)
        collect()
    finally:
        timer.stop()
    for url in urls:
        assert url.isLocalFile(), "Script Help must work without an internet connection"
        from pathlib import Path
        captured.append(Path(url.toLocalFile()).read_text(encoding="utf-8"))
    help_text = "\n".join(captured)
    for term in ("doc", "geo", "selected", "doc.get", "doc.add", "doc.remove", "doc.run", "units"):
        assert term in help_text, f"Offline Help must explain {term}"


def test_agent_can_prepare_a_new_python_draft_without_running_or_overwriting_code(win):
    from serpentine3d.ai.agent import Agent
    from serpentine3d.api import SerpApi

    original = "# My unfinished script\nwidth = 123\n"
    _editor(win).setPlainText(original)
    win.command_workspace.set_mode("ai")
    mode = win.command_workspace.mode

    class ScriptClient:
        def __init__(self):
            self.requests = 0
            self.advertised = []
            self.results = []

        def stream_message(self, system, messages, tools, **kwargs):
            self.requests += 1
            self.advertised = tools
            if self.requests == 1:
                return {"content": [{"type": "tool_use", "id": "python-draft",
                                     "name": "prepare_script",
                                     "input": {"source": BOX, "title": "Box from assistant"}}],
                        "stop_reason": "tool_use", "usage": {}}
            self.results = messages[-1]["content"]
            return {"content": [{"type": "text", "text": "The script is ready to review."}],
                    "stop_reason": "end_turn", "usage": {}}

    client = ScriptClient()
    agent = Agent(SerpApi(win), client, parent=win)
    agent.send("Prepare a box script for me to edit and run")
    _wait(lambda: not agent.busy, "The Agent script handoff did not finish")
    schema = next((tool for tool in client.advertised if tool["name"] == "prepare_script"), None)
    assert schema is not None, "The Agent must advertise a structured prepare_script tool"
    assert "source" in schema["input_schema"]["properties"]
    assert client.results and client.results[0]["tool_use_id"] == "python-draft"
    assert not client.results[0].get("is_error", False), client.results[0]
    assert _editor(win).toPlainText() == BOX
    assert _find_draft(win, original).toPlainText() == original
    assert win.scene.all() == [] and not win.history.can_undo
    assert win.command_workspace.mode == mode
