"""Hydra's look: sizes, colours and the icons components wear."""

from __future__ import annotations

from PySide6.QtGui import QColor

from ...core import hydra
from ..icons import command_icon, sliders_icon


NODE_WIDTH = 110


NODE_HEIGHT = 28


PORT_RADIUS = 5


MARK_STEP = 13              # from one Graft, Flatten or Reverse mark on


MARK_FROM = 13              # the first mark's middle, in from the edge


PORT_REACH = 11             # how near a click or a wire's end has to be


PANEL_WIDTH = 220           # a panel's size: room for a few lines of text


PANEL_HEIGHT = 130


PANEL_HEAD = 22             # its title strip, over the text


COMPONENT_MIME = "application/x-serpentine-hydra-component"


SLIDER_WIDTH = 240


VALUE_WIDTH = 66


VALUE_GAP = 14              # between the value and the output


INPUT_ROW = 20              # height each input takes down the left


BODY = QColor("#34363b")


STATUS = {"warning": QColor("#a8742a"), "error": QColor("#a83a35")}


TEXT = QColor("#e4e5e7")


MUTED = QColor("#9a9b9e")


WIRE = QColor("#b9bcc4")


ACCENT = QColor("#d9a441")


PORT_COLOURS = {"point": QColor("#8fd18a"), "curve": QColor("#7fb3e6"),
         "brep": QColor("#e6c27f"), "mesh": QColor("#c9a6f0"),
         "number": QColor("#e4e5e7"), "geometry": QColor("#6fd0c0"),
         "vector": QColor("#f08a8a"), "any": QColor("#b9bcc4"),
         "boolean": QColor("#e6e07f"), "text": QColor("#e4e5e7")}


_ICONS: dict = {}


def component_icon(comp):
    """The toolbar's icon for what a component holds, made once."""
    if comp.icon not in _ICONS:
        # the slider wears the Properties panel's mark: values on rails
        _ICONS[comp.icon] = (sliders_icon()
                             if comp.icon == "sliders"
                             else command_icon(comp.icon) if comp.icon
                             else None)
    return _ICONS[comp.icon]


def marks(comp, flags, output):
    """How many Graft, Flatten or Reverse marks the most marked input, or
    output, carries."""
    ports = comp.outputs if output else comp.inputs
    return max((len(hydra.flags_of((flags or {}).get(
        hydra.flag_key(p.name, output)))) for p in ports), default=0)


def mark_room(count):
    return count * MARK_STEP + 4 if count else 0


FLAG_COLOUR = QColor("#e4e5e7")


HINT = {None: ACCENT, "add": QColor("#6fcf7a"),
         "remove": QColor("#e0605a")}
