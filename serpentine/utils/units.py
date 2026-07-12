"""Document units: parsing and formatting of lengths.

Model coordinates are stored in *document units*. The unit system defines
how typed lengths are interpreted and how measurements are displayed.
Feet-and-inches input follows drafting conventions: 3'6", 3'-6 1/2",
6", 0.5", 3', and bare numbers are document units.
"""

from __future__ import annotations

import re
from fractions import Fraction

UNITS = ("mm", "cm", "m", "in", "ft")

TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4, "ft": 304.8}

UNIT_LABELS = {
    "mm": "millimetres", "cm": "centimetres", "m": "metres",
    "in": "inches", "ft": "feet & inches",
}

_SUFFIXES = [
    ("mm", "mm"), ("cm", "cm"), ("m", "m"),
    ("in", "in"), ('"', "in"), ("ft", "ft"), ("'", "ft"),
]

_NUM = r"-?\d+(?:\.\d+)?|-?\.\d+"

# 3'6", 3'-6 1/2", 12' 4.5", 3'
_FTIN = re.compile(
    rf"^\s*(?P<neg>-)?\s*(?P<ft>{_NUM})\s*'\s*-?\s*"
    rf"(?:(?P<inch>{_NUM})?\s*(?:\s(?P<num>\d+)/(?P<den>\d+))?\s*\"?)?\s*$")
# 6 1/2" or 1/2"
_IN_FRAC = re.compile(
    rf"^\s*(?P<neg>-)?\s*(?:(?P<inch>{_NUM})\s+)?(?P<num>\d+)/(?P<den>\d+)"
    rf"\s*(?:\"|in)\s*$")


def convert(value: float, from_units: str, to_units: str) -> float:
    return value * TO_MM[from_units] / TO_MM[to_units]


def parse_length(text: str, doc_units: str = "mm") -> float | None:
    """Parse a typed length into document units. None if unparseable."""
    text = text.strip()
    if not text:
        return None

    m = _FTIN.match(text)
    if m and "'" in text:
        try:
            feet = float(m.group("ft"))
            inches = float(m.group("inch") or 0.0)
            if m.group("num"):
                inches += float(Fraction(int(m.group("num")),
                                         int(m.group("den"))))
            total_in = abs(feet) * 12.0 + inches
            sign = -1.0 if (m.group("neg") or feet < 0) else 1.0
            return sign * convert(total_in, "in", doc_units)
        except (ValueError, ZeroDivisionError):
            return None

    m = _IN_FRAC.match(text)
    if m:
        try:
            inches = float(m.group("inch") or 0.0)
            inches += float(Fraction(int(m.group("num")),
                                     int(m.group("den"))))
            sign = -1.0 if m.group("neg") else 1.0
            return sign * convert(inches, "in", doc_units)
        except (ValueError, ZeroDivisionError):
            return None

    lowered = text.lower()
    for suffix, unit in _SUFFIXES:
        if lowered.endswith(suffix):
            body = lowered[: -len(suffix)].strip()
            try:
                return convert(float(body), unit, doc_units)
            except ValueError:
                return None

    try:
        return float(text)
    except ValueError:
        return None


def format_length(value: float, doc_units: str = "mm",
                  precision: int = 3, fraction_denominator: int = 16) -> str:
    """Format a document-unit length for display."""
    if doc_units == "ft":
        return _format_ft_in(value, fraction_denominator)
    if doc_units == "in":
        return f"{_trim(value, precision)}\""
    return f"{_trim(value, precision)} {doc_units}"


def _format_ft_in(value_ft: float, denom: int) -> str:
    sign = "-" if value_ft < 0 else ""
    total_in = abs(value_ft) * 12.0
    frac = Fraction(round(total_in * denom), denom)
    inches_whole = int(frac)
    feet, inches = divmod(inches_whole, 12)
    remainder = frac - inches_whole
    parts = f"{inches}"
    if remainder:
        parts += f" {remainder.numerator}/{remainder.denominator}"
    return f'{sign}{feet}\'-{parts}"'


def _trim(value: float, precision: int) -> str:
    s = f"{value:.{precision}f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-") else "0"
