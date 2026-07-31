"""The About box.

An About box gets opened for one of two reasons: somebody wants to know
what this program is, or somebody is filing a bug and needs to say which
build they are on and what it is standing on. The first is a sentence and
it never changes; the second is a table, and the version, the kernel and
the Qt build in it are exactly the facts a reporter cannot be expected to
dig out by hand — so they are on the box, and one button puts the lot on
the clipboard in the shape an issue wants them.
"""

from __future__ import annotations

import platform
import sys

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel,
    QPushButton, QVBoxLayout, QWidget)

from . import theme
from .dialogs import untether
from .splash import mark_pixmap
from .welcome import _DOCS, _GITHUB

# The panel the website's own Support button opens, rather than the bare
# profile page GitHub's sponsor button lands on.
_KOFI = ("https://ko-fi.com/chisomobanzi/"
         "?hidefeed=true&widget=true&embed=true&preview=true")

_BLURB = ("An open-source NURBS surface modeller — freeform surfaces, solids "
          "and drafting sheets, on Linux, Windows and macOS.")
_NAME_STORY = ("Named after the serpentine stone of Zimbabwean Shona "
               "sculpture.")

_QSS = f"""
QDialog#about {{ background: #1b1c20; }}
QLabel#word {{ color: #ececee; }}
QLabel#ver, QLabel#section, QLabel#key {{ color: #85868a; }}
QLabel#section {{ font-family: monospace; letter-spacing: 1.5px; }}
QLabel#blurb {{ color: #cfcfd2; font-size: 13px; }}
QLabel#val {{ color: #e6e6e8; font-family: monospace; font-size: 12px; }}
QFrame#card {{ background: #232428; border: 1px solid #34353a;
              border-radius: 8px; }}
QLabel#link {{ color: {theme.ACCENT}; }}
QPushButton {{
    padding: 7px 14px; border-radius: 6px; background: #2c2d32;
    border: 1px solid #3a3b41; color: #e6e6e8; font-size: 12px;
}}
QPushButton:hover {{ background: #34353b; border-color: {theme.ACCENT}; }}
"""


def _kernel_version() -> str:
    """OCCT arrives as a wheel, so its own headers are not around to ask —
    the wheel's version is the honest answer and the one a bug report can
    be matched against."""
    try:
        from importlib.metadata import version
        return version("cadquery-ocp")
    except Exception:                                      # noqa: BLE001
        return "unknown"


def build_rows() -> list[tuple[str, str]]:
    """What this build is, and what it is standing on."""
    from PySide6 import __version__ as pyside_version
    from PySide6.QtCore import qVersion

    from .. import __version__
    host = (f"{platform.system()} {platform.release()} "
            f"({platform.machine()})")
    return [
        ("Serpentine3D", __version__),
        ("Python", platform.python_version()),
        ("Qt", f"{qVersion()} (PySide6 {pyside_version})"),
        ("OpenCASCADE", _kernel_version()),
        ("Platform", host),
    ]


class AboutDialog(QDialog):
    def __init__(self, window: QWidget | None = None):
        super().__init__(window)
        from .. import __version__
        self._version = __version__
        self._rows = build_rows()
        self.setObjectName("about")
        self.setWindowTitle("About Serpentine3D")
        self.setStyleSheet(_QSS)
        self.setFixedWidth(460)
        self._build()
        untether(self, over=window)

    # ---------------------------------------------------------------- text
    def summary_text(self) -> str:
        """What the box says in prose, as one string."""
        return "\n".join([f"Serpentine3D v{self._version} · MIT licence",
                          _BLURB, _NAME_STORY])

    def details_text(self) -> str:
        """The table, in the shape an issue wants it pasted."""
        width = max(len(k) for k, _ in self._rows)
        return "\n".join(f"{k.ljust(width)}  {v}" for k, v in self._rows)

    def link_urls(self) -> list[str]:
        return [_DOCS, _GITHUB, _KOFI]

    def copy_details(self):
        QApplication.clipboard().setText(self.details_text())
        # Say it took, then go back to being a button: a control stuck
        # reading "Copied" no longer looks like something you can press.
        self._copy_btn.setText("Copied")
        QTimer.singleShot(1500, self._reset_copy_label)

    def _reset_copy_label(self):
        self._copy_btn.setText("Copy details")

    # --------------------------------------------------------------- build
    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 18)
        outer.setSpacing(16)

        outer.addLayout(self._header())

        blurb = QLabel(f"{_BLURB}\n\n{_NAME_STORY}")
        blurb.setObjectName("blurb")
        blurb.setWordWrap(True)
        outer.addWidget(blurb)

        outer.addWidget(self._build_card())
        outer.addLayout(self._footer())

    def _header(self) -> QHBoxLayout:
        head = QHBoxLayout()
        head.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(mark_pixmap(46))
        head.addWidget(logo)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        word = QLabel("Serpentine3D")
        word.setObjectName("word")
        wf = QFont()
        wf.setPointSizeF(21)
        wf.setWeight(QFont.Weight.DemiBold)
        word.setFont(wf)
        titles.addWidget(word)
        ver = QLabel(f"v{self._version}  ·  MIT licence")
        ver.setObjectName("ver")
        titles.addWidget(ver)
        head.addLayout(titles)
        head.addStretch(1)
        return head

    def _build_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(10)
        section = QLabel("BUILD")
        section.setObjectName("section")
        sf = QFont("monospace")
        sf.setPointSizeF(8.5)
        section.setFont(sf)
        lay.addWidget(section)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)
        for row, (key, value) in enumerate(self._rows):
            k = QLabel(key)
            k.setObjectName("key")
            v = QLabel(value)
            v.setObjectName("val")
            # The values are the half of this anybody retypes, so let them
            # be selected out of the box as well as copied wholesale.
            v.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(k, row, 0)
            grid.addWidget(v, row, 1)
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        return card

    def _footer(self) -> QHBoxLayout:
        foot = QHBoxLayout()
        foot.setSpacing(8)
        foot.addWidget(self._link("Docs", _DOCS))
        foot.addWidget(self._dot())
        foot.addWidget(self._link("GitHub", _GITHUB))
        foot.addWidget(self._dot())
        foot.addWidget(self._link("Support", _KOFI))
        foot.addStretch(1)
        self._copy_btn = QPushButton("Copy details")
        self._copy_btn.clicked.connect(self.copy_details)
        foot.addWidget(self._copy_btn)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        close.setDefault(True)
        foot.addWidget(close)
        return foot

    def _dot(self) -> QLabel:
        dot = QLabel("·")
        dot.setObjectName("ver")
        return dot

    def _link(self, text: str, url: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("link")
        lab.setCursor(Qt.CursorShape.PointingHandCursor)
        lab.mousePressEvent = (
            lambda _ev, u=url: QDesktopServices.openUrl(QUrl(u)))
        return lab


if __name__ == "__main__":                                 # pragma: no cover
    app = QApplication(sys.argv)
    AboutDialog().exec()
