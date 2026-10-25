"""User text: the keys and values an object carries, Rhino's Attribute
User Text.

A part number, a room, a row in somebody's schedule: what a drawing says
about an object that its geometry cannot. A .3dm is where it mostly comes
from and goes back to, so it is kept by Rhino's rules, or a round trip
would change it:

- a key is matched without regard to case, one character at a time, so
  Part and PART are one key while Straße and STRASSE are two, and setting
  one keeps the spelling it already had;
- a value is never empty, because setting one to nothing is how Rhino
  takes a key away, and a key is never empty either;
- the pairs keep the order they were given in.

An object with none holds None rather than an empty dict, like the other
optional attributes on `SceneObject`. Nothing here changes the dict it is
given: an undo checkpoint shares the object's, and editing it in place
would edit the past.
"""

from __future__ import annotations


def key_in(text: dict | None, key: str) -> str | None:
    """How `text` spells `key`, if it holds it at all."""
    folded = key.lower()
    return next((k for k in text or {} if k.lower() == folded), None)


def value_of(text: dict | None, key: str) -> str | None:
    """The value under `key`, however its case is written."""
    found = key_in(text, key)
    return None if found is None else text[found]


def with_value(text: dict | None, key: str, value: str) -> dict | None:
    """`text` with `key` set to `value`, or taken away if `value` is empty."""
    if not key:
        raise ValueError("a key needs a name")
    out = dict(text or {})
    found = key_in(out, key)
    if not value:
        out.pop(found, None)
    else:
        out[key if found is None else found] = value
    return out or None


def renamed(text: dict | None, old: str, new: str) -> dict | None:
    """`text` with the key `old` called `new`, keeping its value and place.

    Refused, with ValueError, when `new` is empty or names another key:
    taking that key's place would throw its value away.
    """
    if not new:
        raise ValueError("a key needs a name")
    out = dict(text or {})
    found = key_in(out, old)
    if found is None:
        raise KeyError(old)
    clash = key_in({k: v for k, v in out.items() if k != found}, new)
    if clash is not None:
        raise ValueError(f"there is already a key called {clash}")
    return {(new if k == found else k): v for k, v in out.items()}


def merged(*texts: dict | None) -> dict | None:
    """Several objects' text as one, a later one winning a key they share.

    How a piece of a placed block comes by its text: the block's first,
    then any block inside it, then the piece's own.
    """
    out = None
    for text in texts:
        for key, value in (text or {}).items():
            if key and value:
                out = with_value(out, key, value)
    return out


def cleaned(text) -> dict | None:
    """Whatever a file or a script handed over, as Rhino could hold it.

    A number where text belongs is kept as its text, and a pair with
    nothing in its key or its value is left out, not refused: a .serp
    written by hand or by an assistant should still open.
    """
    if not isinstance(text, dict):
        return None
    return merged({str(k): "" if v is None else str(v)
                   for k, v in text.items()})
