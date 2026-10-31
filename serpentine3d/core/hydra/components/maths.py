"""Addition, Subtraction, Multiplication and Division, and the lists of
numbers a graph is built on: Series, Range and Random."""

from __future__ import annotations

import math
import random
import re

from . import COMPONENTS, Component
from ..kinds import HydraError, Port, format_number
from ..tree import Tree, pack_tree

MOST_NUMBERS = 100_000      # the longest list Series, Range or Random make


def _operation(key, title, sign, solve, b_default, description):
    COMPONENTS[key] = Component(
        key, title, "Math",
        inputs=(Port("A", "number", 0.0, description="The first number"),
                Port("B", "number", b_default,
                     description="The second number")),
        outputs=(Port("Result", "number", description=f"A {sign} B"),),
        icon=key, solve=solve, description=description)


def _divide(A, B):
    if B == 0:
        raise HydraError("B is 0, and nothing can be divided by 0")
    return A / B


_operation("addition", "Addition", "+", lambda A, B: A + B, 0.0,
           "A plus B")
_operation("subtraction", "Subtraction", "-", lambda A, B: A - B, 0.0,
           "A minus B")
_operation("multiplication", "Multiplication", "×", lambda A, B: A * B, 1.0,
           "A times B")
_operation("division", "Division", "÷", _divide, 1.0, "A divided by B")


_SIGNS = {"+": "addition", "-": "subtraction", "*": "multiplication",
          "x": "multiplication", "×": "multiplication", "/": "division",
          "÷": "division", ":": "division"}
_TYPED = re.compile(r"\s*([-+*x×/÷:])\s*(\d+(?:[.,]\d*)?|[.,]\d+)\s*$",
                    re.IGNORECASE)


def operation_from_text(text: str):
    """What a sign and a number typed into the search, +2, -0.5, *3 or /4,
    stand for: the operation, its settings with the number kept in B, and
    how it is said, A + 2. None if it is not that."""
    m = _TYPED.match(text)
    if m is None:
        return None
    sign, typed = m.group(1).lower(), m.group(2).replace(",", ".")
    value = float(typed)
    if not math.isfinite(value):
        return None
    key = _SIGNS[sign]
    places = len(typed.split(".", 1)[1]) if "." in typed else 0
    shown = {"*": "×", "x": "×", "/": "÷", ":": "÷"}.get(sign, sign)
    said = f"A {shown} {format_number(value, places)}"
    return key, {"internal": {"B": pack_tree(Tree.of([value]))}}, said


def _count(n, what="Count") -> int:
    count = int(round(n))
    if count < 0:
        raise HydraError(f"{what} cannot be less than 0")
    if count > MOST_NUMBERS:
        raise HydraError(f"{what} can be at most {MOST_NUMBERS:,}")
    return count


def _series(S, N, C):
    return [S + N * i for i in range(_count(C))]


COMPONENTS["series"] = Component(
    "series", "Series", "Math",
    inputs=(Port("S", "number", 0.0, label="Start",
                 description="The first number"),
            Port("N", "number", 1.0, label="Step",
                 description="What each number adds to the one before"),
            Port("C", "number", 10.0, label="Count",
                 description="How many numbers")),
    outputs=(Port("Series", "number", access="list",
                  description="The numbers"),),
    icon="series", solve=_series,
    description="C numbers from S on, each N more than the one before: "
                "0, 1, 2 ... by default")


def _range(S, E, N):
    steps = _count(N, "Steps")
    if steps == 0:
        return [S]
    return [S + (E - S) * i / steps for i in range(steps + 1)]


COMPONENTS["range"] = Component(
    "range", "Range", "Math",
    inputs=(Port("S", "number", 0.0, label="Start",
                 description="Where the range starts"),
            Port("E", "number", 1.0, label="End",
                 description="Where the range ends"),
            Port("N", "number", 10.0, label="Steps",
                 description="How many equal steps it is divided into")),
    outputs=(Port("Range", "number", access="list",
                  description="The numbers, S and E among them"),),
    icon="range", solve=_range,
    description="The range from S to E divided into N equal steps: N + 1 "
                "numbers, S and E among them")


def _random(Min, Max, N, Seed):
    draw = random.Random(int(round(Seed)))
    return [draw.uniform(Min, Max) for _ in range(_count(N))]


COMPONENTS["random"] = Component(
    "random", "Random", "Math",
    inputs=(Port("Min", "number", 0.0, label="Lowest",
                 description="The lowest a number can be"),
            Port("Max", "number", 1.0, label="Highest",
                 description="The highest a number can be"),
            Port("N", "number", 10.0, label="Count",
                 description="How many numbers"),
            Port("Seed", "number", 1.0,
                 description="Another seed, other numbers; the same seed, "
                             "the same numbers every time")),
    outputs=(Port("Numbers", "number", access="list",
                  description="The random numbers"),),
    icon="random", solve=_random,
    description="N random numbers between Min and Max, the same ones for "
                "the same Seed")


def _round(N, D):
    places = int(round(D))
    if places < 0:
        raise HydraError("Decimals cannot be less than 0")
    return round(N, places)


COMPONENTS["round"] = Component(
    "round", "Round", "Math",
    inputs=(Port("N", "number", label="Number",
                 description="The number to round"),
            Port("D", "number", 0.0, label="Decimals",
                 description="How many places after the point: none "
                             "unless set")),
    outputs=(Port("R", "number", label="Result",
                  description="N rounded to D places"),),
    icon="round", solve=_round,
    description="N rounded to D decimal places, to a whole number unless "
                "set")
