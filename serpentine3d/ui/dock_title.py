"""A side panel's title bar: its icon, its name, and float and close.

Qt's own dock title is text and nothing else. Properties and Layers sit
stacked in one column, and Properties can show a layer, so each panel says
which it is with a mark as well as a word, the way the layer tab in
Properties carries the Layers panel's mark.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDockWidget, QHBoxLayout, QLabel, QToolButton, QWidget

from . import theme

_QSS = (
    "#dockTitle { background: #2e2f34; border-bottom: 1px solid #1b1c1f; }"
    # transparent, or the app theme's panel grey shows as a box behind each
    "#dockTitle QLabel { color: #9a9b9e; font-size: 12px;"
    " background: transparent; }"
    "#dockTitle QToolButton { color: #77787e; border: none; padding: 0 3px;"
    " background: transparent; }"
    "#dockTitle QToolButton:hover { color: #e8e9ea; }"
    "#dockTitle QTabBar { background: transparent; font-size: 12px; }"
    "#dockTitle QTabBar::tab { background: transparent; color: #9a9b9e;"
    " padding: 3px 8px; margin: 0; border: none;"
    " border-bottom: 2px solid transparent; max-width: 150px; }"
    "#dockTitle QTabBar::tab:selected { color: #e8e9ea;"
    f" border-bottom-color: {theme.ACCENT}; }}"
    "#dockTitle QTabBar::tab:hover:!selected { color: #cfd0d2; }"
)


class DockTitleBar(QWidget):
    """Icon, name, then whatever a subclass puts in `row`, then the dock's
    own float and close buttons for the features it has."""

    def __init__(self, icon, title: str, dock: QDockWidget | None = None):
        super().__init__()
        self._dock = dock
        self.setObjectName("dockTitle")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(_QSS)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(8, 0, 4, 0)
        self.row.setSpacing(6)
        self.icon = QLabel()
        self.icon.setPixmap(icon)
        self.title = QLabel(title)
        self.row.addWidget(self.icon)
        self.row.addWidget(self.title)
        # Room for a subclass's widgets, then the stretch. The stretch is the
        # drag handle: a bare widget ignores a press, so it reaches the dock
        # underneath and the panel still tears off.
        self._slot = self.row.count()
        self.row.addStretch(1)
        self.float_btn = QToolButton(self)
        self.float_btn.setText("❐")
        self.float_btn.setToolTip("Float or dock this panel")
        self.close_btn = QToolButton(self)
        self.close_btn.setText("✕")
        self.close_btn.setToolTip("Close this panel")
        self.row.addWidget(self.float_btn)
        self.row.addWidget(self.close_btn)
        if dock is not None:
            self.float_btn.clicked.connect(
                lambda: dock.setFloating(not dock.isFloating()))
            self.close_btn.clicked.connect(dock.close)
            dock.featuresChanged.connect(self._show_buttons)
        self._show_buttons()
        self.setMinimumHeight(26)

    def add_widget(self, widget, *args):
        """Put a widget after the name, before the stretch."""
        self.row.insertWidget(self._slot, widget, *args)
        self._slot += 1

    def _show_buttons(self, *_args):
        feats = (self._dock.features() if self._dock is not None
                 else QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        self.float_btn.setVisible(
            bool(feats & QDockWidget.DockWidgetFeature.DockWidgetFloatable))
        self.close_btn.setVisible(
            bool(feats & QDockWidget.DockWidgetFeature.DockWidgetClosable))

    def mouseDoubleClickEvent(self, ev):
        """A double-click on a dock's title floats it, as Qt's own does."""
        if self._dock is not None and (
                self._dock.features()
                & QDockWidget.DockWidgetFeature.DockWidgetFloatable):
            self._dock.setFloating(not self._dock.isFloating())
        ev.accept()
