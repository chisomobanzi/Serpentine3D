"""Hydra's components, by category. Each category's module adds its
components to COMPONENTS; a new component is a function and an entry
there, nothing else."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from ..kinds import Port


@dataclass(frozen=True)
class Component:
    key: str
    title: str
    category: str
    inputs: tuple[Port, ...] = ()
    outputs: tuple[Port, ...] = ()
    # the kinds of model object it holds, picked with its Set action
    picks: tuple[str, ...] = ()
    icon: str = ""            # the toolbar icon the editor shows it with
    description: str = ""
    params: dict = field(default_factory=dict)
    # works out one set of outputs from one item of each input
    solve: Callable | None = None
    # the right-click action that sets the inputs by picking in the model
    sets: str = ""
    # makes its outputs from more than its inputs: given the graph, the
    # node, the model's scene and what is solved so far, it gives a Result
    made: Callable | None = None

    @property
    def plural(self) -> str:
        noun = self.title.lower()
        return noun + ("es" if noun.endswith("sh") else "s")


COMPONENTS: dict[str, Component] = {}


# the node bar's tabs: what goes in, the numbers and lists worked on, then
# the geometry changed and made
CATEGORIES = ("Geometry", "Input", "Math", "List", "Text", "Vector",
              "Curve", "Transform", "Mesh")


# What the search on the canvas offers before anything is typed: the
# components every graph starts from. The rest are found by typing.
QUICK = ("point", "curve", "brep", "mesh", "slider")


# The short names a Grasshopper hand types to find a component.
NICKNAMES = {
    "point": ("pt",), "curve": ("crv",), "mesh": ("msh",),
    "slider": ("num", "sl"), "construct_point": ("pt", "cpt"),
    "toggle": ("bool", "true", "false"), "pipeline": ("pipe",),
    "panel": ("text", "note"),
    "delaunay": ("tri", "triangulate"),
    "vector": ("vec",), "rotate": ("rot",), "move": ("mv",),
    "list_item": ("item", "li"),
    "remove_item": ("cull", "delete", "ri"),
    "addition": ("add", "plus", "+"), "subtraction": ("sub", "minus"),
    "multiplication": ("mul", "times", "*"), "division": ("div", "/"),
    "series": ("ser",), "range": ("rng",), "random": ("rnd", "rand"),
    "unit_x": ("x", "ux"), "unit_y": ("y", "uy"), "unit_z": ("z", "uz"),
    "contour": ("con", "section", "slice"),
    "round": ("int",), "concatenate": ("concat", "join", "&"),
    "text_tag": ("tag", "label", "text"),
    "deconstruct_point": ("dpt", "decon", "xyz"),
    "point_on_curve": ("poc", "eval"),
    "group": ("grp",), "ungroup": ("ungrp", "explode"),
}


def find_components(text: str) -> list[str]:
    """The components a search for `text` finds, best first: those whose
    name starts with it or that go by it for short, then those with a word
    that starts with it, then the rest that have it in their name or
    category."""
    words = text.lower().split()
    if not words:
        return list(QUICK)
    order = list(COMPONENTS)
    found = []
    phrase = " ".join(words)
    for key, comp in COMPONENTS.items():
        title = comp.title.lower()
        short = NICKNAMES.get(key, ())
        said = " ".join((title, comp.category.lower(), key) + short)
        if not all(w in said for w in words):
            continue
        rank = (0 if title.startswith(phrase) or phrase in short
                else 1 if any(t.startswith(words[0]) for t in title.split())
                else 2)
        found.append((rank, order.index(key), key))
    return [key for _rank, _at, key in sorted(found)]


@dataclass
class Result:
    outputs: dict = field(default_factory=dict)
    status: str = "ok"            # ok | warning | error
    message: str = ""


# each adds its own components, in the order the node bar shows them
from . import (  # noqa: E402,F401
    geometry, inputs, maths, lists, text, vector, curve, transform, mesh)
