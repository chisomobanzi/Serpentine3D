"""Welcome / start screen — shown on launch (Rhino/Blender style).

Start a new model (mm or inches), open a file, pick a recent document, or
jump to the docs. Skippable and remembers the "show at startup" choice.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from . import theme
from .splash import mark_pixmap

_GITHUB = "https://github.com/chisomobanzi/Serpentine3D"
_DOCS = "https://chisomobanzi.github.io/Serpentine3D/"

_QSS = f"""
QDialog#welcome {{ background: #1b1c20; }}
QLabel#word {{ color: #ececee; }}
QLabel#ver, QLabel#section {{ color: #85868a; }}
QLabel#section {{ font-family: monospace; letter-spacing: 1.5px; }}
QFrame#card {{ background: #232428; border: 1px solid #34353a;
              border-radius: 8px; }}
QPushButton#start {{
    text-align: left; padding: 11px 14px; border-radius: 6px;
    background: #2c2d32; border: 1px solid #3a3b41; color: #e6e6e8;
    font-size: 13px;
}}
QPushButton#start:hover {{ background: #34353b; border-color: {theme.ACCENT}; }}
QPushButton#start[primary="true"] {{ border-color: {theme.ACCENT_DIM}; }}
QListWidget {{ background: transparent; border: none; color: #cfcfd2;
              font-size: 13px; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 5px; }}
QListWidget::item:hover {{ background: #2c2d32; }}
QListWidget::item:selected {{ background: #34353b; color: #fff; }}
QLabel#link {{ color: {theme.ACCENT}; }}
QCheckBox {{ color: #85868a; }}
"""


class WelcomeScreen(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self.setObjectName("welcome")
        self.setWindowTitle("Welcome to Serpentine3D")
        # A NORMAL window type (not DIALOG) with no transient-for hint, so
        # GNOME's attach-modal-dialogs can't glue it to the main window
        # (drags it, can't resize). Still application-modal via exec().
        self.setWindowFlags(Qt.WindowType.Window)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setFixedSize(660, 460)
        self.setStyleSheet(_QSS)
        self._build()
        if window is not None:                 # centre over the main window
            c = window.frameGeometry().center()
            self.move(c.x() - self.width() // 2, c.y() - self.height() // 2)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 20)
        outer.setSpacing(18)

        # header: mark + wordmark + version
        header = QHBoxLayout()
        header.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(mark_pixmap(46))
        header.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        word = QLabel("Serpentine3D")
        word.setObjectName("word")
        wf = QFont()
        wf.setPointSizeF(21)
        wf.setWeight(QFont.Weight.DemiBold)
        word.setFont(wf)
        titles.addWidget(word)
        from .. import __version__
        ver = QLabel(f"v{__version__}  ·  precision NURBS modelling")
        ver.setObjectName("ver")
        titles.addWidget(ver)
        header.addLayout(titles)
        header.addStretch(1)
        outer.addLayout(header)

        # body: two columns (Start | Recent)
        body = QHBoxLayout()
        body.setSpacing(18)
        body.addWidget(self._start_column(), 1)
        body.addWidget(self._recent_column(), 1)
        outer.addLayout(body, 1)

        # footer: startup toggle + links
        footer = QHBoxLayout()
        show = QCheckBox("Show this screen at startup")
        show.setChecked(self.win.cfg.get("show_welcome", default=True))
        show.toggled.connect(
            lambda on: self.win.cfg.set("show_welcome", on))
        footer.addWidget(show)
        footer.addStretch(1)
        footer.addWidget(self._link("Documentation", _DOCS))
        dot = QLabel("·")
        dot.setObjectName("ver")
        footer.addWidget(dot)
        footer.addWidget(self._link("GitHub", _GITHUB))
        outer.addLayout(footer)

    def _section(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("section")
        f = QFont("monospace")
        f.setPointSizeF(8.5)
        lab.setFont(f)
        return lab

    def _start_column(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        lay.addWidget(self._section("START"))
        b_mm = self._start_btn("New model", "millimetres",
                               lambda: self._new("mm"), primary=True)
        b_in = self._start_btn("New model", "inches",
                               lambda: self._new("in"))
        b_open = self._start_btn("Open a file…", "STEP · DXF · 3dm · OBJ · serp",
                                 self._open)
        lay.addWidget(b_mm)
        lay.addWidget(b_in)
        lay.addWidget(b_open)
        lay.addStretch(1)
        return card

    def _start_btn(self, title, subtitle, slot, primary=False) -> QPushButton:
        btn = QPushButton()
        btn.setObjectName("start")
        if primary:
            btn.setProperty("primary", "true")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(btn)
        lay.setContentsMargins(14, 9, 14, 9)
        lay.setSpacing(1)
        t = QLabel(title)
        t.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        t.setStyleSheet("color:#ececee; font-size:13px; "
                        "background:transparent; border:none;")
        s = QLabel(subtitle)
        s.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        s.setStyleSheet("color:#85868a; font-size:11px; "
                        "background:transparent; border:none;")
        lay.addWidget(t)
        lay.addWidget(s)
        btn.clicked.connect(slot)
        return btn

    def _recent_column(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(8)
        lay.addWidget(self._section("RECENT"))
        files = self.win.recent_files()
        if not files:
            empty = QLabel("No recent files yet —\nstart a new model to begin.")
            empty.setStyleSheet("color:#85868a; font-size:12px;")
            lay.addWidget(empty)
            lay.addStretch(1)
            return card
        listing = QListWidget()
        for p in files[:8]:
            item = QListWidgetItem(os.path.basename(p))
            item.setToolTip(p)
            item.setData(Qt.ItemDataRole.UserRole, p)
            listing.addItem(item)
        listing.itemActivated.connect(self._open_recent)
        listing.itemClicked.connect(self._open_recent)
        lay.addWidget(listing, 1)
        return card

    def _link(self, text: str, url: str) -> QLabel:
        lab = QLabel(f'<a style="color:{theme.ACCENT};text-decoration:none" '
                     f'href="{url}">{text}</a>')
        lab.setObjectName("link")
        lab.setOpenExternalLinks(False)
        lab.linkActivated.connect(lambda u: QDesktopServices.openUrl(QUrl(u)))
        return lab

    # -- actions --
    def _new(self, units: str):
        self.win.start_new(units)
        self.accept()

    def _open(self):
        self.accept()
        self.win._file_open()

    def _open_recent(self, item: QListWidgetItem):
        path = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        self.win._open_path(path)


def should_show(window) -> bool:
    """Show the welcome screen on launch? Skips headless/automation, when
    turned off, and when a document is already loaded (CLI file / recovery)."""
    from PySide6.QtWidgets import QApplication
    if os.environ.get("SERP3D_NO_WELCOME") == "1":
        return False
    if QApplication.platformName() in ("offscreen", "minimal", "vnc"):
        return False
    if not window.cfg.get("show_welcome", default=True):
        return False
    if getattr(window.ctx, "current_path", None) is not None:
        return False          # a file was opened / recovered
    return True
