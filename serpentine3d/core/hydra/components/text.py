"""Concatenate, and Text Tag: lettering placed in the model."""

from __future__ import annotations

import numpy as np

from ... import geometry as g
from . import COMPONENTS, Component
from ..kinds import HydraError, Port, Vector, as_text, coordinates


def _concatenate(A, B):
    return as_text(A) + as_text(B)


COMPONENTS["concatenate"] = Component(
    "concatenate", "Concatenate", "Text",
    inputs=(Port("A", "any", label="Text or number",
                 description="What comes first; a number is written as it "
                             "is, without trailing zeros"),
            Port("B", "any", "", label="Text or number",
                 description="What comes after, such as \" m\" or "
                             "\" m above sea level\"")),
    outputs=(Port("T", "text", label="Text", description="A and B joined"),),
    icon="concatenate", solve=_concatenate,
    description="A and B joined into one text: a height and its unit, a "
                "name and its number")


def _text_tag(P, T, H, D):
    from ...text_object import TextShape
    text = as_text(T)
    if not text.strip():
        raise HydraError("There is no text to show")
    if H <= 0:
        raise HydraError("Height must be more than 0")
    # it lies flat and reads along D seen from above, never upside down
    along = np.array([*D.components[:2], 0.0], float)
    if np.linalg.norm(along) < 1e-12:
        along = np.array([1.0, 0.0, 0.0])
    along /= np.linalg.norm(along)
    if along[0] < -1e-9 or (abs(along[0]) <= 1e-9 and along[1] < 0):
        along = -along
    up = np.array([0.0, 0.0, 1.0])
    side = np.cross(up, along)
    frame = np.eye(4)
    frame[:3, 0], frame[:3, 1], frame[:3, 2] = along, side, up
    # centred on P, across as well as along
    frame[:3, 3] = np.asarray(coordinates(P), float) - side * H / 2
    return g.apply_matrix(TextShape(text, H, alignment="center"), frame)


COMPONENTS["text_tag"] = Component(
    "text_tag", "Text Tag", "Text",
    inputs=(Port("P", "point", label="Point",
                 description="Where the text stands, its middle"),
            Port("T", "any", label="Text or number",
                 description="What it says; a number is written without "
                             "trailing zeros"),
            Port("H", "number", 1.0, label="Height",
                 description="How tall its capitals are"),
            Port("D", "vector", Vector((0.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
                 label="Direction",
                 description="Which way it reads, as along a curve; along X "
                             "unless set, and never upside down")),
    outputs=(Port("Tag", "geometry", label="Text",
                  description="The lettering, cast into the model as text "
                              "to edit"),),
    icon="texttag", solve=_text_tag,
    description="Text lying flat at P, H tall, reading along D: a label "
                "on a plan, such as a contour's height")
