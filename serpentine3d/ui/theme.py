"""Serpentine3D dark theme: muted greys with a warm serpentine3d-gold accent."""

# viewport colors (linear-ish RGB floats)
VIEWPORT_BG_TOP = (0.16, 0.165, 0.18)
VIEWPORT_BG_BOTTOM = (0.10, 0.105, 0.12)
GRID_MINOR = (1.0, 1.0, 1.0, 0.055)
GRID_MAJOR = (1.0, 1.0, 1.0, 0.11)
GRID_AXIS_X = (0.75, 0.33, 0.32, 0.85)
GRID_AXIS_Y = (0.38, 0.65, 0.36, 0.85)
SELECTION_COLOR = (1.0, 0.78, 0.25)          # warm gold
ACCENT = "#d9a441"

# Control points, when they are on. Cool, because everything else in the
# viewport is not: curves are white or their layer colour and the selection is
# gold, so a cool blue marker cannot be mistaken for a bit of the drawing.
# White markers were the trouble to begin with — a control point drawn white
# sits on a white curve and disappears into it. EDGE is the dark border drawn
# round each marker, which is what keeps it legible on a pale object as well
# as against the background; NET is the control polygon joining them, kept
# quiet so the points read louder than the lines between them.
CONTROL_POINT = (0.36, 0.80, 1.0)
CONTROL_POINT_EDGE = (0.04, 0.06, 0.09, 0.95)
CONTROL_NET = (0.34, 0.44, 0.56, 0.6)

# Direction arrows, while Dir is running. Green, because the two things it can
# be showing you at once are a curve's direction and a surface's normal, and
# both have to stand out against a drawing that is already white, gold and
# control point blue.
DIRECTION_ARROW = (0.40, 0.95, 0.50, 0.95)

# The arrow on a clipping plane, pointing at the half of the model it takes
# away. Magenta because it is the one colour left: the drawing is white, the
# selection gold, control points blue and direction arrows green, and this
# arrow has to be readable while sitting on top of a plane that is often
# selected and being dragged. PAUSED is the same arrow on a plane that has
# been switched off: half strength reads as a plan rather than a cut, and
# any fainter than this disappears entirely against a pale face, which is
# where a paused plane usually sits.
CLIP_NORMAL = (0.95, 0.40, 0.85, 0.95)
CLIP_NORMAL_PAUSED = (0.95, 0.40, 0.85, 0.55)

ACCENT_DIM = "#8a6a2f"
# Secondary text: a heading, a hint, a row that is switched off.
# The same grey QSS spells out below for headers and placeholders,
# named here because a widget that dims a row has to reach for it in
# code, and Qt's own disabled grey is not what this window paints.
TEXT_MUTED = "#9a9b9e"

# Shaded-mode lighting. SHADED_AMBIENT mirrors a constant hardcoded in
# viewport.MESH_FRAG (`uColor * (0.30 + 0.70 * diff)`); a test pins the two
# together. FILL_FLOOR is what a pure black object is shaded as, and colours
# at or above FILL_KNEE are left exactly as they are. The floor must stay
# below the knee: the two ends define a ramp, and a floor above the knee tips
# it backwards, rendering pure black lighter than dark grey.
SHADED_AMBIENT = 0.30
FILL_FLOOR = 0.42
FILL_KNEE = 0.50


def shaded_fill(color):
    """The colour to shade a surface with, lifted clear of black.

    Shading is multiplicative, so a black object has nothing left to shade: it
    came out flat black against a background that is itself nearly black
    (0.10-0.18) and read as a hole rather than a solid — you had to change the
    layer colour to see the model at all. Rhino keeps black-layer objects
    legible in shaded mode; this does the same, adding grey to colours below
    the knee and more of it the darker they are.

    Gated on the largest channel rather than luminance, so saturated hues that
    are dark in luminance but perfectly visible — pure blue most of all — are
    left alone. Only the fill is lifted: edges keep the object's true colour,
    so a black object still draws black wireframe over a grey surface.
    """
    r, g, b = color[0], color[1], color[2]
    v = max(r, g, b)
    if v >= FILL_KNEE:
        return (r, g, b)
    lift = FILL_FLOOR * (1.0 - v / FILL_KNEE)
    return (min(1.0, r + lift), min(1.0, g + lift), min(1.0, b + lift))

QSS = """
* { outline: none; }

QMainWindow, QWidget {
    background-color: #26272b;
    color: #cfd0d2;
    font-size: 13px;
}

QMainWindow::separator {
    background: #1b1c1f;
    /* 3px was nearly ungrabbable — the panels read as fixed-width (#5) */
    width: 6px; height: 6px;
}

QMainWindow::separator:hover {
    background: #8a6a2f;
}

QDockWidget {
    color: #9a9b9e;
    titlebar-close-icon: none;
    font-size: 12px;
}
QDockWidget::title {
    background: #2e2f34;
    padding: 5px 8px;
    border-bottom: 1px solid #1b1c1f;
}

QToolBar {
    background: #2b2c30;
    border: none;
    spacing: 2px;
    padding: 3px;
}
QToolBar::separator {
    background: #3d3e44;
    width: 1px; margin: 4px 3px;
}

QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px;
    color: #cfd0d2;
}
QToolButton:hover {
    background: #3a3b41;
    border-color: #4a4b52;
}
QToolButton:pressed, QToolButton:checked {
    background: #4a3f28;
    border-color: #d9a441;
    color: #f0d9a8;
}

QLineEdit {
    background: #1e1f22;
    border: 1px solid #3a3b41;
    border-radius: 4px;
    padding: 5px 8px;
    color: #e8e9ea;
    selection-background-color: #8a6a2f;
}
QLineEdit:focus { border-color: #d9a441; }

QListWidget, QTreeWidget, QTableWidget, QTreeView {
    background: #232427;
    border: 1px solid #1b1c1f;
    alternate-background-color: #26272b;
}
QListWidget::item, QTreeWidget::item {
    padding: 3px;
}
QListWidget::item:selected, QTreeWidget::item:selected {
    background: #4a3f28;
    color: #f0d9a8;
}
QHeaderView::section {
    background: #2e2f34;
    border: none;
    border-right: 1px solid #1b1c1f;
    border-bottom: 1px solid #1b1c1f;
    padding: 4px 6px;
    color: #9a9b9e;
}

QPushButton {
    background: #35363c;
    border: 1px solid #45464d;
    border-radius: 4px;
    padding: 5px 14px;
}
QPushButton:hover { background: #3f4047; border-color: #55565e; }
QPushButton:pressed { background: #2b2c30; }
QPushButton:default { border-color: #d9a441; }

QMenuBar { background: #2b2c30; }
QMenuBar::item { padding: 5px 10px; background: transparent; }
QMenuBar::item:selected { background: #3a3b41; }
QMenu {
    background: #2e2f34;
    border: 1px solid #1b1c1f;
    padding: 4px;
}
QMenu::item { padding: 5px 24px 5px 12px; border-radius: 3px; }
QMenu::item:selected { background: #4a3f28; color: #f0d9a8; }
QMenu::separator { height: 1px; background: #3d3e44; margin: 4px 6px; }

QStatusBar {
    background: #2b2c30;
    border-top: 1px solid #1b1c1f;
    color: #9a9b9e;
}

QScrollBar:vertical {
    background: #232427; width: 10px; margin: 0;
}
QScrollBar::handle:vertical {
    background: #45464d; border-radius: 5px; min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #55565e; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QScrollBar:horizontal {
    background: #232427; height: 10px; margin: 0;
}
QScrollBar::handle:horizontal {
    background: #45464d; border-radius: 5px; min-width: 24px;
}

QComboBox {
    background: #1e1f22;
    border: 1px solid #3a3b41;
    border-radius: 4px;
    padding: 4px 8px;
}
QComboBox QAbstractItemView {
    background: #2e2f34;
    selection-background-color: #4a3f28;
}

QLabel#commandPrompt {
    color: #d9a441;
    font-weight: bold;
}
QLabel#commandEcho {
    color: #85868a;
    font-family: monospace;
}

QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #55565e;
    border-radius: 3px;
    background: #1e1f22;
}
QCheckBox::indicator:checked {
    background: #d9a441;
    border-color: #d9a441;
}
"""
