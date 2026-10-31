"""List Item and Remove Item."""

from __future__ import annotations

from . import COMPONENTS, Component
from ..kinds import HydraError, Port


def _list_item(L, i):
    if not L:
        raise HydraError("The list is empty")
    # a fraction is rounded to the nearest place; past either end the
    # index wraps round, so -1 is the last, as in Grasshopper
    return L[int(round(i)) % len(L)]


COMPONENTS["list_item"] = Component(
    "list_item", "List Item", "List",
    inputs=(Port("L", "any", access="list", label="List",
                 description="The list to take an item from"),
            Port("i", "number", 0.0, label="Index",
                 description="Which item: 0 is the first, -1 the last")),
    outputs=(Port("Item", "any", label="Item",
                  description="The item taken"),),
    icon="listitem", solve=_list_item,
    description="The item at index i of list L, counting from 0; -1 is "
                "the last, and an index past the end wraps round")


def _remove_item(L, i):
    # the places to take out, rounded and wrapped round as List Item's are
    gone = {int(round(index)) % len(L) for index in i} if L else set()
    return [item for place, item in enumerate(L) if place not in gone]


COMPONENTS["remove_item"] = Component(
    "remove_item", "Remove Item", "List",
    inputs=(Port("L", "any", access="list", label="List",
                 description="The list to take items out of"),
            Port("i", "number", access="list", label="Index",
                 description="Which items to take out: 0 is the first, "
                             "-1 the last")),
    outputs=(Port("L", "any", access="list", label="List",
                  description="The list without them"),),
    icon="listremove", solve=_remove_item,
    description="List L without the items at the indices i, as Cull Index "
                "does in Grasshopper; -1 is the last")
