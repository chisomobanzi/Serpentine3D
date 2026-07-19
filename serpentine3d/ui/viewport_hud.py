"""Subtle in-viewport HUD — click to change the view and display mode.

A small row of translucent menu-chips pinned to the viewport's top-left
corner. Each viewport owns its own, so split/quad layouts each get their own
controls. The container is sized tightly to the chips so it barely covers
any of the scene.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QMenu, QToolButton, QWidget

from . import theme

_VIEWS = [("Top", "top"), ("Front", "front"), ("Right", "right"),
          ("Back", "back"), ("Left", "left"), ("Bottom", "bottom"),
          ("Perspective", "perspective")]

_MODES = [("Shaded", "shaded"), ("Wireframe", "wireframe"),
          ("Ghosted", "ghosted"), ("Rendered", "rendered"),
          ("Technical", "technical"), ("Zebra", "zebra"),
          ("Curvature", "curvature")]

_QSS = f"""
QWidget#hud {{ background: transparent; }}
QToolButton {{
    background: rgba(22,23,26,0.62); color: #bdbec2;
    border: 1px solid rgba(255,255,255,0.08); border-radius: 5px;
    padding: 3px 9px; font-size: 11px; font-family: sans-serif;
}}
QToolButton:hover {{
    background: rgba(38,39,44,0.92); color: #f0f0f2;
    border-color: {theme.ACCENT_DIM};
}}
QToolButton::menu-indicator {{ image: none; width: 0; }}
QMenu {{
    background: #1f2024; color: #d6d7da; border: 1px solid #3a3b41;
    font-size: 12px; padding: 3px;
}}
QMenu::item {{ padding: 4px 18px 4px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: {theme.ACCENT_DIM}; color: #ffffff; }}
"""

_VIEW_LABEL = {k: label for label, k in _VIEWS}
_MODE_LABEL = {k: label for label, k in _MODES}


class ViewportHud(QWidget):
    def __init__(self, viewport):
        super().__init__(viewport)
        self.vp = viewport
        self.setObjectName("hud")
        self.setStyleSheet(_QSS)
        # NB: do NOT set WA_TransparentForMouseEvents here — it makes the whole
        # subtree (chips included) click-through, so the menus never open.

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self._view_btn = self._chip(_VIEWS, self.vp.set_view)
        self._mode_btn = self._chip(_MODES, self.vp.set_display_mode)
        lay.addWidget(self._view_btn)
        lay.addWidget(self._mode_btn)

        self._sync_view(getattr(viewport, "_view_name", "perspective"))
        self._sync_mode()
        viewport.displayModeChanged.connect(self._sync_mode)
        if hasattr(viewport, "viewChanged"):
            viewport.viewChanged.connect(self._sync_view)
        self.adjustSize()
        self.move(8, 8)

    def _chip(self, items, on_pick) -> QToolButton:
        btn = QToolButton(self)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        menu = QMenu(btn)
        for label, key in items:
            act = menu.addAction(label)
            act.triggered.connect(lambda _=False, k=key: on_pick(k))
        btn.setMenu(menu)
        return btn

    def _sync_view(self, name: str):
        self._view_btn.setText(f"{_VIEW_LABEL.get(name, name.title())}  ▾")
        self._reflow()

    def _sync_mode(self):
        mode = self.vp.display_mode
        self._mode_btn.setText(f"{_MODE_LABEL.get(mode, mode.title())}  ▾")
        self._reflow()

    def _reflow(self):
        self.adjustSize()
        self.move(8, 8)
