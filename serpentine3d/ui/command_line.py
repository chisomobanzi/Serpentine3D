"""Rhino-style command line: history echo, prompt, input with completion."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)

from ..commands.base import completions, resolve

MAX_SUGGESTIONS = 8


def rank_completions(prefix: str, recent: list[str]) -> list[str]:
    """Command names starting with `prefix`, best guess first.

    Alphabetical order is no guess at all: it offers `tolerance` to someone
    typing `to`, and files `detailborder` in ahead of `detailmode`. What you
    ran lately comes first, then the shortest name — which puts the plain
    command in front of the variants built on top of it.
    """
    order = {n: i for i, n in enumerate(recent)}
    return sorted(completions(prefix),
                  key=lambda n: (order.get(n, len(order)), len(n), n))


class CommandInput(QLineEdit):
    # Set on every keypress: a guess must not be filled back in over a
    # deletion, or the box fights the person trying to correct it.
    deleting = False

    tabPressed = Signal()
    upPressed = Signal()
    downPressed = Signal()
    escPressed = Signal()
    focusLost = Signal()

    def focusOutEvent(self, ev):
        # Whatever is being suggested floats over the viewport, so it must not
        # outlive the typing that asked for it.
        self.focusLost.emit()
        super().focusOutEvent(ev)

    def event(self, ev):
        if ev.type() == ev.Type.KeyPress and ev.key() == Qt.Key.Key_Tab:
            self.tabPressed.emit()
            return True
        # with an empty input, cede Ctrl+C/V/A to the app-level shortcuts
        if (ev.type() == ev.Type.ShortcutOverride and not self.text()
                and ev.modifiers() & Qt.KeyboardModifier.ControlModifier
                and ev.key() in (Qt.Key.Key_C, Qt.Key.Key_V, Qt.Key.Key_A)):
            ev.ignore()
            return False
        return super().event(ev)

    def keyPressEvent(self, ev):
        key = ev.key()
        self.deleting = key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete)
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            # QLineEdit fires returnPressed but leaves the event ignored;
            # consume it here or it bubbles to the main window, whose
            # Enter-repeats-last-command fallback instantly re-runs the
            # command the returnPressed handling just completed
            super().keyPressEvent(ev)
            ev.accept()
        elif key == Qt.Key.Key_Up:
            self.upPressed.emit()
        elif key == Qt.Key.Key_Down:
            self.downPressed.emit()
        elif key == Qt.Key.Key_Escape:
            self.escPressed.emit()
        elif (not self.text()
                and ev.modifiers() & Qt.KeyboardModifier.ControlModifier
                and key in (Qt.Key.Key_C, Qt.Key.Key_V, Qt.Key.Key_A,
                            Qt.Key.Key_Z, Qt.Key.Key_Y)):
            ev.ignore()          # bubble to the main window
        else:
            super().keyPressEvent(ev)


class _EchoView(QPlainTextEdit):
    """The history. Asks for four lines, takes any more room it is given.

    A plain text edit asks for a great deal of height, and the command area
    is not where the window should be spending it, so this asks for the four
    lines the history has always shown. It used to be held there by a
    maximum height, which meant a taller command area put the extra space
    below the input rather than into the part worth reading back.
    """

    LINES = 4

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setHeight(self.LINES * self.fontMetrics().lineSpacing() + 8)
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setHeight(self.fontMetrics().lineSpacing() + 8)   # one line
        return hint


class CommandLine(QWidget):
    """Bottom dock: scrolling echo area + prompt + input line."""

    submitted = Signal(str)         # raw text the user entered
    cancelled = Signal()
    optionClicked = Signal(str)     # option chip clicked -> cycle its value
    keywordClicked = Signal(str)    # keyword chip clicked -> answers prompt
    tabPressed = Signal()           # Tab while a point is wanted

    def __init__(self, parent=None):
        super().__init__(parent)
        # Tab means completion at the "Command" prompt and direction lock
        # while a command is asking for a point. The two never overlap:
        # there is no command name to complete once one is running.
        self.point_pending = False
        # Whether the prompt is "Command". A command asking for a value picks
        # its own words: "to" at an option prompt is the start of one of them,
        # not an invitation to run Top.
        self.awaiting_command = True
        self._history: list[str] = []
        self._hist_pos = 0

        mono = QFont("monospace")
        mono.setStyleHint(QFont.StyleHint.TypeWriter)

        self.echo_view = _EchoView()
        self.echo_view.setReadOnly(True)
        self.echo_view.setFont(mono)
        self.echo_view.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.echo_view.setStyleSheet(
            "QPlainTextEdit { background: #1b1c1f; border: none;"
            " color: #85868a; padding: 2px 6px; }")

        self.prompt_label = QLabel("Command")
        self.prompt_label.setObjectName("commandPrompt")

        self.input = CommandInput()
        self.input.setFont(mono)
        self.input.setPlaceholderText(
            "type a command (line, circle, extrude, loft, ...)")

        # The other matches, listed above the input because the command line
        # lives at the bottom of the window. It takes no focus: every keystroke
        # still belongs to the box, which is where you are looking.
        self.suggestions = QListWidget(self)
        self.suggestions.setFont(mono)
        self.suggestions.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.suggestions.setCursor(Qt.CursorShape.PointingHandCursor)
        self.suggestions.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.suggestions.setStyleSheet(
            "QListWidget { background: #26272b; color: #c9cacd;"
            " border: 1px solid #3a3b40; outline: none; }"
            "QListWidget::item { padding: 1px 6px; }"
            "QListWidget::item:selected { background: #33343a;"
            " color: #d8b44a; }")
        self.suggestions.hide()
        self.suggestions.itemClicked.connect(self._on_suggestion_clicked)

        self.input.returnPressed.connect(self.submit_input)
        self.input.tabPressed.connect(self._on_tab)
        self.input.textEdited.connect(self._on_typed)
        self.input.upPressed.connect(self._on_up)
        self.input.downPressed.connect(self._on_down)
        self.input.escPressed.connect(self.input.clear)
        self.input.escPressed.connect(self.suggestions.hide)
        self.input.focusLost.connect(self.suggestions.hide)
        self.input.escPressed.connect(self.cancelled.emit)

        self._chip_row = QHBoxLayout()
        self._chip_row.setContentsMargins(0, 0, 0, 0)
        self._chip_row.setSpacing(6)
        self._chips: list[QPushButton] = []
        self._keyword_chips: list[QPushButton] = []

        row = QHBoxLayout()
        row.setContentsMargins(8, 4, 8, 6)
        row.setSpacing(8)
        row.addWidget(self.prompt_label)
        row.addWidget(self.input, 1)
        row.addLayout(self._chip_row)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # All the stretch goes to the history: drag the command area taller
        # and it is the echoed output that gets the room, not a gap under
        # the input.
        layout.addWidget(self.echo_view, 1)
        layout.addLayout(row)

    # -- public API --

    def echo(self, msg: str):
        self.echo_view.appendPlainText(msg)
        self.echo_view.moveCursor(QTextCursor.MoveOperation.End)

    def clear_history_selection(self):
        """Drop any text picked out of the history.

        Ctrl+C copies that text in preference to the drawing, so a
        selection nobody meant any more has to stop being one.
        """
        self.echo_view.moveCursor(QTextCursor.MoveOperation.End)

    def set_prompt(self, text: str):
        self.prompt_label.setText(text)

    def set_options(self, chips: list):
        """Show clickable [Name=Value] chips; click cycles the value."""
        want = [f"{n}={v}" for n, v in chips]
        if want == [c.text() for c in self._chips]:
            return
        for c in self._chips:
            self._chip_row.removeWidget(c)
            c.deleteLater()
        self._chips = []
        for (name, _), label in zip(chips, want):
            chip = QPushButton(label)
            chip.setFlat(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            chip.setToolTip(f"Click to change {name} (or type {name}=value)")
            chip.setStyleSheet(
                "QPushButton { color: #d8b44a; background: #26272b;"
                " border: 1px solid #3a3b40; border-radius: 9px;"
                " padding: 1px 10px; }"
                "QPushButton:hover { border-color: #d8b44a; }")
            chip.clicked.connect(
                lambda _=False, n=name: self.optionClicked.emit(n))
            self._chip_row.addWidget(chip)
            self._chips.append(chip)

    def set_keywords(self, words: list):
        """Show one-shot keyword chips; clicking one answers the prompt.

        Where an option chip is Name=Value and cycles, a keyword is a word
        the prompt takes whole — Close, Center, BothSides — the clickable
        twin of typing it.
        """
        if words == [c.text() for c in self._keyword_chips]:
            return
        for c in self._keyword_chips:
            self._chip_row.removeWidget(c)
            c.deleteLater()
        self._keyword_chips = []
        for word in words:
            chip = QPushButton(word)
            chip.setFlat(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            chip.setToolTip(f"Click (or type) {word}")
            chip.setStyleSheet(
                "QPushButton { color: #7fb3d8; background: #26272b;"
                " border: 1px solid #3a3b40; border-radius: 9px;"
                " padding: 1px 10px; }"
                "QPushButton:hover { border-color: #7fb3d8; }")
            chip.clicked.connect(
                lambda _=False, w=word: self.keywordClicked.emit(w))
            self._chip_row.addWidget(chip)
            self._keyword_chips.append(chip)

    def focus(self):
        self.input.setFocus()

    def run_command(self, text: str):
        """Run as if typed at the prompt (records history)."""
        self.suggestions.hide()
        text = text.strip()
        if text:
            self._history.append(text)
            self._hist_pos = len(self._history)
            self.submitted.emit(text)

    def recent_commands(self, limit: int = 12) -> list[str]:
        """Distinct command names, most recent first."""
        out: list[str] = []
        for t in reversed(self._history):
            name = t.strip().split()[0].lower() if t.strip() else ""
            if name and name not in out:
                out.append(name)
            if len(out) >= limit:
                break
        return out

    def submit_input(self):
        """Submit the current input text exactly as pressing Enter does:
        record history, clear the box, and emit `submitted`. Public so a
        right-click in the viewport can act as Enter (Rhino-style)."""
        self.suggestions.hide()
        text = self.input.text()
        self.input.clear()
        if text.strip():
            self._history.append(text.strip())
        self._hist_pos = len(self._history)
        self.submitted.emit(text)

    # -- internals --

    def _on_typed(self, text: str):
        """Guess at what is being typed, unless a command is asking for a value.

        The guess is filled in only when letters are being added to the end:
        putting it back over a backspace makes the box fight whoever is trying
        to correct it, and there is nothing to guess in the middle of a word.
        """
        if not self.awaiting_command:
            self.suggestions.hide()
            return
        appending = (not self.input.deleting
                     and self.input.cursorPosition() == len(text))
        self._offer(text.strip(), fill=appending)

    def _offer(self, prefix: str, fill: bool):
        """List what `prefix` could be, and maybe make it the best of them.

        Filling in leaves the letters that were not typed selected, so the next
        keystroke replaces them — and so Enter, or a right-click in the
        viewport, submits the whole name rather than the prefix.

        A prefix that already names a command or an alias is never extended:
        `line` must not become `linetype` under someone's fingers, and `l`
        must not become `layer` when it is the alias for line.
        """
        self.suggestions.clear()
        matches = rank_completions(prefix, self.recent_commands()) if prefix \
            else []
        if not matches:
            self.suggestions.hide()
            return
        self.suggestions.addItems(matches[:MAX_SUGGESTIONS])
        self.suggestions.setCurrentRow(0)
        self._place_suggestions()
        if fill and resolve(prefix) is None:
            self.input.setText(matches[0])
            self.input.setSelection(len(prefix), len(matches[0]) - len(prefix))

    def _place_suggestions(self):
        """Stand the list on the command line, growing upwards.

        Reparented onto the window rather than onto the command line: the dock
        is only tall enough for the echo area and the prompt, so the list has to
        be free to cover the viewport instead. It clears the whole dock rather
        than just the input, which keeps the echoed history — and the
        Model/Layout tabs — readable while it is up. Only as wide as the names
        in it: this is a hint, not a panel.
        """
        win = self.window()
        if self.suggestions.parentWidget() is not win:
            self.suggestions.setParent(win)
        row_h = self.suggestions.sizeHintForRow(0)
        if row_h <= 0:
            row_h = self.input.fontMetrics().height() + 2
        height = self.suggestions.count() * row_h + 4
        width = min(max(200, self.suggestions.sizeHintForColumn(0) + 24),
                    max(200, self.input.width()))
        self.suggestions.setGeometry(
            self.input.mapTo(win, QPoint(0, 0)).x(),
            max(0, self.mapTo(win, QPoint(0, 0)).y() - height), width, height)
        self.suggestions.raise_()
        self.suggestions.show()

    def _use_row(self, row: int):
        """Put a whole name in the box — no selected tail, it was chosen."""
        self.suggestions.setCurrentRow(row)
        item = self.suggestions.item(row)
        if item is not None:
            self.input.setText(item.text())

    def _on_suggestion_clicked(self, item):
        self.input.setText(item.text())
        self.submit_input()

    def _on_tab(self):
        if self.point_pending:
            self.tabPressed.emit()
        else:
            self._complete()

    def _complete(self):
        """Tab: take the highlighted match, and on the next Tab the one after.

        Unlike typing, Tab is an outright request, so it will extend a name
        that is already a command — cycling `line` on to `linetype`.
        """
        if self.suggestions.isHidden() or not self.suggestions.count():
            self._offer(self.input.text().strip(), fill=False)
            if self.suggestions.count():
                self._use_row(0)
            return
        self._use_row((self.suggestions.currentRow() + 1)
                      % self.suggestions.count())

    def _on_up(self):
        if self.suggestions.isHidden() or not self.suggestions.count():
            self.history_prev()
        else:
            self._use_row(max(0, self.suggestions.currentRow() - 1))

    def _on_down(self):
        if self.suggestions.isHidden() or not self.suggestions.count():
            self.history_next()
        else:
            self._use_row(min(self.suggestions.currentRow() + 1,
                              self.suggestions.count() - 1))

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(ev)

    def eventFilter(self, obj, ev):
        return super().eventFilter(obj, ev)

    def history_prev(self):
        if self._history and self._hist_pos > 0:
            self._hist_pos -= 1
            self.input.setText(self._history[self._hist_pos])

    def history_next(self):
        if self._hist_pos < len(self._history) - 1:
            self._hist_pos += 1
            self.input.setText(self._history[self._hist_pos])
        else:
            self._hist_pos = len(self._history)
            self.input.clear()
