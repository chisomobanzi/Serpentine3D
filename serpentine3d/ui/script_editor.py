"""Editable Python drafts and reviewable, undoable document previews."""

from __future__ import annotations

import keyword
from pathlib import Path
import re
import threading
import uuid

from PySide6.QtCore import QCoreApplication, QEvent, QRect, QSize, Qt, Signal, Slot
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QLayout, QMenu, QMessageBox, QPlainTextEdit,
    QPushButton, QSizePolicy, QTabBar, QTabWidget, QTextBrowser, QToolButton, QVBoxLayout, QWidget,
)

from ..script_runtime import execute_script, fingerprint
from .workspace_icons import workspace_icon


BOX_EXAMPLE = '''# A box on a named layer. Edit the dimensions, then Run.
width, depth, height = 40, 30, 20
doc.add(geo.make_box((0, 0, 0), width, depth, height),
        name="Block", layer="Generated")
print("Volume:", doc.volume("Block"))
'''

RIBS_EXAMPLE = '''# Select one guide curve in the viewport before Run.
import numpy as np

if len(selected) != 1 or selected[0].kind != "curve":
    raise ValueError("Select one guide curve before Run.")

count = 12
width, height = 30, 45
frames = geo.sample_curve_frames(selected[0].shape, count)
for i, (origin, tangent, up) in enumerate(frames):
    tangent, up = np.asarray(tangent), np.asarray(up)
    side = np.cross(up, tangent)
    placement = np.eye(4)
    placement[:3, :3] = np.column_stack((tangent, side, up))
    placement[:3, 3] = origin
    rib = geo.make_box((-1, -width / 2, 0), 2, width, height)
    doc.add(geo.apply_matrix(rib, placement),
            name=f"Rib {i + 1:02d}", layer="Ribs")
print(f"Prepared {count} ribs.")
'''

HELP = '''<h2>Python in Serpentine</h2>
<p>Write a script, choose <b>Run</b>, inspect the green geometry in model
viewports, then <b>Keep</b> or <b>Discard</b>. Red geometry will be removed.
Keep is one model undo step. Re-running a draft replaces its own outputs.</p>
<p><code>doc</code> is an isolated working copy of your current document.
<code>geo</code> (also <code>doc.geo</code>) provides geometry functions.
<code>selected</code> contains the scene objects selected at Run.</p>
<pre>guide = doc.get(selected[0].id)
box = doc.add(geo.make_box((0, 0, 0), 40, 30, 20), name="Block")
doc.remove("Block")
doc.run("circle", ["0,0,0", "20"])
print(doc.scene.units)  # document units, e.g. mm
</pre>
<p>Use <code>doc.objects()</code>, <code>doc.get(name_or_id)</code>,
<code>doc.add(shape, name=, layer=)</code>, <code>doc.remove(name_or_id)</code>,
and <code>doc.run(command, inputs)</code>. Inspect shapes with
<code>doc.volume(name)</code>, <code>doc.area(name)</code>, and
<code>doc.bbox(name)</code>. Open/save scripts as normal UTF-8 .py files.</p>
<p><b>Examples</b> includes a box and ribs along a selected guide. Each opens
as a separate editable draft. Assistant scripts also open as new drafts;
they run only when you choose Run.</p>
<p>Stop interrupts Python loops. A native geometry operation may finish
before cancellation takes effect. Finish or cancel an active CAD command
before Keep. If your document changed during preview, Run again.</p>
<p>Scripts are trusted Python with normal file and library access.
Preview protects document edits; it is not a security sandbox and cannot
undo external file writes. The live window and GUI API are not provided.</p>'''


class PythonHighlight(QSyntaxHighlighter):
    def highlightBlock(self, text):
        for pattern, color in (
            (r"\b(?:" + "|".join(keyword.kwlist) + r")\b", "#d7bb82"),
            (r"\b(?:doc|geo|selected|print)\b", "#94c8bb"),
            (r"\b\d+(?:\.\d+)?\b", "#c4acd9"),
            (r'''(?:"[^"\\]*(?:\\.[^"\\]*)*"|'[^'\\]*(?:\\.[^'\\]*)*')''', "#afc791"),
            (r"#.*", "#7d8c8b"),
        ):
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            for match in re.finditer(pattern, text):
                self.setFormat(match.start(), match.end() - match.start(), fmt)


class LineNumbers(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor
        self.setAccessibleName("Python line numbers")
        self.setToolTip("Line numbers")

    def sizeHint(self):
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):
        editor = self.editor
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor("#24272a"))
        painter.setPen(QColor("#788180"))
        block = editor.firstVisibleBlock()
        top = round(editor.blockBoundingGeometry(block).translated(editor.contentOffset()).top())
        while block.isValid() and top <= event.rect().bottom():
            height = round(editor.blockBoundingRect(block).height())
            if block.isVisible() and top + height >= event.rect().top():
                painter.drawText(0, top, self.width() - 8, height,
                                 Qt.AlignmentFlag.AlignRight, str(block.blockNumber() + 1))
            top += height
            block = block.next()


class PythonEditor(QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setAccessibleName("Python script source")
        self.setPlaceholderText("# Write Python with doc, geo, and selected…")
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setTabStopDistance(self.fontMetrics().horizontalAdvance(" ") * 4)
        self.setStyleSheet("QPlainTextEdit { background: #202326; color: #d4dbd7;"
                           " border: 1px solid #39413e; selection-background-color: #426257; }")
        self.numbers = LineNumbers(self)
        self.highlight = PythonHighlight(self.document())
        self.blockCountChanged.connect(self.update_gutter)
        self.updateRequest.connect(self._scroll_gutter)
        self.update_gutter()

    def gutter_width(self):
        return 16 + self.fontMetrics().horizontalAdvance("9") * len(str(self.blockCount()))

    def update_gutter(self, *_):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _scroll_gutter(self, rect, dy):
        if dy:
            self.numbers.scroll(0, dy)
        else:
            self.numbers.update(0, rect.y(), self.numbers.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.contentsRect()
        self.numbers.setGeometry(QRect(rect.left(), rect.top(), self.gutter_width(), rect.height()))

    def event(self, event):
        if event.type() == QEvent.Type.ShortcutOverride:
            # Model-wide shortcuts must not consume Python editing, including
            # Enter/Space, Ctrl+Z, Delete, selection, and copy/paste.
            event.accept()
            return True
        return super().event(event)


class ScriptEditor(QWidget):
    completed = Signal(object)

    def __init__(self, window):
        super().__init__(window)
        self.setAccessibleName("Script editor")
        self.window = window
        self._stop = threading.Event()
        self._thread = None
        self._preview = None
        self._closed = False
        self._running_editor = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setMovable(True)
        self.tabs.setTabsClosable(True)
        self.tabs.setIconSize(QSize(16, 16))
        self.tabs.setElideMode(Qt.TextElideMode.ElideRight)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.setStyleSheet("""
            QTabWidget::pane { border: none; }
            QTabBar::tab { background: transparent; color: #929a9e;
                border: none; padding: 4px 7px; }
            QTabBar::tab:selected { color: #dbdcd6; background: #27292d;
                border-bottom: 1px solid #aa8b49; }
            QToolButton#scriptTabClose { background: transparent; border: none;
                border-radius: 3px; padding: 0; }
            QToolButton#scriptTabClose:hover { background: #3b4046; }
            QToolButton#scriptTabClose:pressed { background: #484e55; }
            QToolButton#scriptTabClose:focus { border: 1px solid #657d98; }
        """)
        layout.addWidget(self.tabs, 1)
        actions = self.tab_actions = QWidget()
        actions.setStyleSheet("QPushButton, QToolButton { padding: 3px 6px; }")
        files = QHBoxLayout(actions)
        files.setSizeConstraint(QLayout.SizeConstraint.SetFixedSize)
        files.setContentsMargins(4, 0, 1, 0)
        files.setSpacing(1)
        self.tabs.setCornerWidget(actions, Qt.Corner.TopRightCorner)
        self.examples = QToolButton()
        self.examples.setText("Examples")
        self.examples.setToolTip("Python examples")
        self.examples.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.examples)
        menu.addAction("Box on a layer", lambda: self.new_draft(BOX_EXAMPLE, "Box.py"))
        menu.addAction("Ribs along selected guide", lambda: self.new_draft(RIBS_EXAMPLE, "Ribs.py"))
        self.examples.setMenu(menu)
        files.addWidget(self.examples)
        self.run_button = self._button("Run", self.run)
        self.stop_button = self._button("Stop", self.stop)
        self.keep_button = self._button("Keep", self.keep)
        self.discard_button = self._button("Discard", self.discard)
        for button, name in ((self.run_button, "run"), (self.stop_button, "stop")):
            button.setIcon(workspace_icon(name, color="#b6d5c7" if name == "run" else "#9ca6ad"))
            button.setIconSize(QSize(14, 14))
        for button in (self.run_button, self.stop_button, self.keep_button, self.discard_button):
            files.addWidget(button)
        self.run_button.setStyleSheet("background: #2b4038; color: #b6d5c7;")
        self.run_button.setToolTip("Run Python to preview document changes")
        more = QToolButton()
        more.setIcon(workspace_icon("more"))
        more.setToolTip("Script actions · New, Open, Save and Help")
        more.setAccessibleName("Script actions")
        more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(more)
        menu.addAction("New", lambda: self.new_draft())
        menu.addAction("Open", self.open_file)
        menu.addAction("Save", self.save_file)
        menu.addSeparator()
        self._run_actions = [menu.addAction(button.accessibleName(), callback)
                             for button, callback in ((self.stop_button, self.stop),
                                                      (self.keep_button, self.keep),
                                                      (self.discard_button, self.discard))]
        menu.addSeparator()
        menu.addAction("Help", self.show_help)
        more.setMenu(menu)
        files.addWidget(more)
        self.status = QLabel()
        self.status.setMinimumWidth(0)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.status.setStyleSheet("color: #9eaaa4; font-size: 11px;")
        self.status.hide()
        layout.addWidget(self.status)
        self.completed.connect(self._completed)
        self._restore_drafts()
        if not self.tabs.count():
            self.new_draft()
        self._controls()

    @staticmethod
    def _button(label, callback):
        button = QPushButton(label)
        button.setAccessibleName(label)
        button.clicked.connect(callback)
        return button

    @property
    def editor(self):
        return self.tabs.currentWidget()

    def new_draft(self, source="", title="Untitled.py", path=None):
        editor = PythonEditor()
        editor.script_path = path
        editor.script_id = str(uuid.uuid4())
        editor.script_title = title
        editor.setPlainText(source)
        index = self.tabs.addTab(editor, workspace_icon("script", color="#9baec7"), title)
        # Replace the platform's close artwork while retaining Qt's close
        # signal and the existing save/discard flow. Resolve the index on click
        # so moving tabs never changes which document the button closes.
        close = QToolButton(self.tabs.tabBar())
        close.setObjectName("scriptTabClose")
        close.setIcon(workspace_icon("close", color="#8d979f"))
        close.setIconSize(QSize(16, 16))
        close.setFixedSize(20, 20)
        close.setAccessibleName("Close script")
        close.setToolTip("Close script")
        close.clicked.connect(
            lambda: self.tabs.tabCloseRequested.emit(self.tabs.indexOf(editor)))
        self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.LeftSide, None)
        self.tabs.tabBar().setTabButton(index, QTabBar.ButtonPosition.RightSide, close)
        self.tabs.setCurrentWidget(editor)
        editor.document().modificationChanged.connect(
            lambda changed: self.tabs.setTabText(self.tabs.indexOf(editor),
                                                 editor.script_title + (" •" if changed else "")))
        editor.setFocus()
        return editor

    def open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open Python script", "", "Python (*.py)")
        if not path:
            return
        path = str(Path(path).resolve())
        for index in range(self.tabs.count()):
            if self.tabs.widget(index).script_path == path:
                self.tabs.setCurrentIndex(index)
                return
        try:
            self.new_draft(Path(path).read_text(encoding="utf-8"), Path(path).name, path)
        except (OSError, UnicodeError) as exc:
            self._echo(f"Open failed: {exc}")

    def save_file(self):
        return self._save_editor(self.editor)

    def _save_editor(self, editor):
        path = editor.script_path
        if path is None:
            path, _ = QFileDialog.getSaveFileName(self, "Save Python script", editor.script_title,
                                                 "Python (*.py)")
        if not path:
            return False
        path = str(Path(path).resolve())
        if not path.lower().endswith(".py"):
            path += ".py"
        try:
            Path(path).write_text(editor.toPlainText(), encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            self._echo(f"Save failed: {exc}")
            return False
        old_owner = self._owner(editor)
        before = fingerprint(self.window.scene.snapshot())
        editor.script_path = path
        editor.script_title = Path(path).name
        self.tabs.setTabText(self.tabs.indexOf(editor), editor.script_title)
        editor.document().setModified(False)
        # Saving a previously kept untitled draft gives its outputs a stable
        # file identity that survives a .serp and .py reopening together.
        owner = self._owner(editor)
        changed = self._rename_owner(self.window.scene.history_records, old_owner, owner)
        # This changes a script's file identity, not a model operation. The
        # identity must follow earlier geometry states through undo and redo.
        history = self.window.history
        for _, snapshot in (*history._undo, *history._redo):
            self._rename_owner(snapshot.get("history_records", []), old_owner, owner)
        if self._preview is not None and self._running_editor is editor:
            self._rename_owner(self._preview["snapshot"]["history_records"], old_owner, owner)
        if changed:
            self.window.scene.notify()
            if self._running_editor is editor and self._baseline == before:
                self._baseline = fingerprint(self.window.scene.snapshot())
        self._echo(f"Saved {path}")
        return True

    def close_tab(self, index):
        editor = self.tabs.widget(index)
        if editor is None:
            return
        if self._running_editor is editor:
            if self._thread is not None:
                self._echo("Stop the running script before closing its tab.")
                return
            if self._preview is not None:
                self._echo("Keep or Discard the preview before closing its script tab.")
                return
        unsaved = (bool(editor.toPlainText()) if editor.script_path is None
                   else editor.document().isModified())
        if unsaved:
            choice = QMessageBox.question(
                self, "Close Python script",
                f'Save changes to "{editor.script_title}" before closing?',
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if choice == QMessageBox.StandardButton.Cancel:
                return
            if choice == QMessageBox.StandardButton.Save and not self._save_editor(editor):
                return
        self.tabs.removeTab(self.tabs.indexOf(editor))
        if self._running_editor is editor:
            self._running_editor = None
        editor.deleteLater()
        if not self.tabs.count():
            self.new_draft()

    @staticmethod
    def _rename_owner(records, old_owner, owner):
        changed = False
        if old_owner != owner:
            for record in records:
                if record.get("op") == "script_output" and record.get("owner") == old_owner:
                    record["owner"] = owner
                    changed = True
        return changed

    @staticmethod
    def _owner(editor):
        return "file:" + editor.script_path if editor.script_path else "draft:" + editor.script_id

    def show_help(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Python scripting help")
        dialog.resize(660, 530)
        layout = QVBoxLayout(dialog)
        browser = QTextBrowser()
        browser.setHtml(HELP)
        layout.addWidget(browser)
        close = self._button("Close", dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    def _echo(self, text):
        for line in str(text).splitlines():
            self.window.command_line.echo(f"[Script] {line}")

    def _controls(self):
        busy = self._thread is not None
        self.run_button.setEnabled(not busy and not self._closed)
        self.stop_button.setEnabled(busy)
        self.keep_button.setEnabled(self._preview is not None and not busy)
        self.discard_button.setEnabled(self._preview is not None and not busy)
        for button, action in zip((self.stop_button, self.keep_button, self.discard_button),
                                  self._run_actions):
            action.setEnabled(button.isEnabled())
            button.setVisible(button.isEnabled())
        # QTabWidget caches corner placement. Reflow after preview actions
        # change width so their right edge stays inside a narrow pane.
        self.tab_actions.layout().invalidate()
        self.tab_actions.layout().activate()
        self.tab_actions.adjustSize()
        self.tabs.setCornerWidget(self.tab_actions, Qt.Corner.TopRightCorner)
        self.tab_actions.show()
        QCoreApplication.sendEvent(self.tabs, QEvent(QEvent.Type.LayoutRequest))
        self.status.setVisible(bool(self.status.text()))

    def run(self):
        if self._thread is not None or self._closed:
            return
        self.discard(announce=False)
        editor = self.editor
        snapshot = self.window.scene.snapshot()
        self._baseline = fingerprint(snapshot)
        self._selected_ids = list(self.window.selection.ids)
        self._running_editor = editor
        self._stop = threading.Event()
        source = editor.toPlainText()
        filename = editor.script_path or editor.script_title
        owner = self._owner(editor)
        self._run_owner = owner
        self.status.setText(f"Running {editor.script_title}…")
        self._echo(f"Run {filename}")

        def worker():
            result = execute_script(source, filename, snapshot, self._selected_ids, owner, self._stop)
            try:
                self.completed.emit(result)
            except RuntimeError:
                pass  # the owning window was destroyed during a native call

        self._thread = threading.Thread(target=worker, name="Serpentine Python", daemon=True)
        self._thread.start()
        self._controls()

    def stop(self):
        self._stop.set()
        self.status.setText("Stopping… native geometry calls may need to finish")
        self._controls()

    @Slot(object)
    def _completed(self, result):
        self._thread = None
        if self._closed:
            return
        if result.get("output"):
            self._echo(result["output"])
        if self._stop.is_set() or result.get("stopped"):
            self.status.setText("Stopped · document unchanged")
            self._echo("Stopped; document unchanged")
        elif result.get("error"):
            self.status.setText("Python error · see command history")
            self._echo(result["error"])
        else:
            # A Save can give the originating draft its first path while the
            # worker is running. Its outputs belong to that same draft.
            self._rename_owner(result["snapshot"]["history_records"], self._run_owner,
                               self._owner(self._running_editor))
            self._preview = result
            for message in result.get("messages", []):
                self._echo(message)
            self.window.scene.script_preview = result["overlay"]
            self._redraw()
            self.status.setText(f"Preview: {self._running_editor.script_title} · "
                                f"+{result['changed']} / −{result['removed']}")
            self.status.setToolTip(f"{self._running_editor.script_title}: "
                                   f"{result['changed']} new/changed in green, "
                                   f"{result['removed']} removed in red. Keep or Discard.")
            self._echo(f"Preview ready: {result['changed']} new/changed, {result['removed']} removed")
        self._controls()

    def _redraw(self):
        for viewport in self.window.all_viewports():
            viewport.update()

    def keep(self):
        if self._preview is None:
            return
        if self.window.processor.busy:
            self._echo("Finish or cancel the active CAD command before Keep. Preview is still available.")
            return
        if fingerprint(self.window.scene.snapshot()) != self._baseline:
            self._echo("The document changed since Run. Run again to make a fresh preview.")
            self.discard(announce=False)
            self.status.setText("Document changed · Run again")
            return
        result = self._preview
        self.window.history.checkpoint("Script: " + self._running_editor.script_title)
        self.window.scene.restore(result["snapshot"])
        for obj in self.window.scene.all():
            obj._scene = self.window.scene
        self.window.selection.set([oid for oid in self._selected_ids if self.window.scene.get(oid)])
        self._echo(f"Kept {self._running_editor.script_title} · one undo step")
        self.discard(announce=False)
        self.status.setText("Kept · Run again to replace outputs")

    def discard(self, announce=True):
        had_preview = self._preview is not None
        self._preview = None
        self.window.scene.script_preview = None
        self._redraw()
        self._controls()
        if announce and had_preview:
            self.status.setText("Discarded · document unchanged")
            self._echo("Discarded preview; document unchanged")

    def shutdown(self):
        if self._closed:
            return
        self.window.cfg.set("script_drafts", {
            "current": self.tabs.currentIndex(),
            "drafts": [{"source": editor.toPlainText(), "title": editor.script_title,
                        "path": editor.script_path, "id": editor.script_id,
                        "modified": editor.document().isModified()}
                       for editor in (self.tabs.widget(index)
                                      for index in range(self.tabs.count()))],
        })
        self._closed = True
        self._stop.set()
        self.discard(announce=False)

    def _restore_drafts(self):
        saved = self.window.cfg.get("script_drafts", default={})
        if not isinstance(saved, dict) or not isinstance(saved.get("drafts", []), list):
            return
        for draft in saved.get("drafts", []):
            if not isinstance(draft, dict) or not isinstance(draft.get("source"), str):
                continue
            title = draft.get("title")
            path = draft.get("path")
            editor = self.new_draft(draft["source"],
                                    title if isinstance(title, str) else "Untitled.py",
                                    path if isinstance(path, str) else None)
            if isinstance(draft.get("id"), str):
                editor.script_id = draft["id"]
            editor.document().setModified(bool(draft.get("modified", True)))
        current = saved.get("current", 0)
        if isinstance(current, int) and 0 <= current < self.tabs.count():
            self.tabs.setCurrentIndex(current)
