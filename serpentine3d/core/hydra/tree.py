"""Data trees, as in Grasshopper: branches of items under paths, the
Graft, Flatten and Reverse flags, and how a tree is kept in a file."""

from __future__ import annotations

from .. import geometry as g
from .kinds import GeometryGroup, Vector, describe_item


def list_tree(tree, most: int = 12) -> list:
    """The items of a tree as lines, each after its place in its branch,
    [0], [1]..., the places in line: under a heading for each branch, with
    how much it holds, when there is more than one; at most `most` items,
    the rest counted."""
    lines, shown = [], 0
    several = len(tree.branches) > 1
    widest = len(str(max((len(b) for b in tree.branches.values()),
                         default=1) - 1))
    for path, branch in tree.branches.items():
        if shown >= most:
            break
        if several:
            lines.append("Branch {" + ";".join(str(i) for i in path) + "} · "
                         + count_said(Tree.of(branch)))
        for i, value in enumerate(branch):
            if shown >= most:
                break
            lines.append(("  " if several else "") + f"[{i:>{widest}}] "
                         + describe_item(value))
            shown += 1
    rest = len(tree) - shown
    if rest > 0:
        lines.append(f"… {rest} more")
    return lines


def count_said(tree) -> str:
    """How much a tree holds, in words: "empty", "1 item", "3 items"."""
    count = len(tree)
    if not count:
        return "empty"
    return f"{count} item" + ("" if count == 1 else "s")


# -- internalized data, as a graph file keeps it ------------------------------

def pack(value):
    """A value as plain data: a number, a point, a vector, or geometry as
    the bytes Serpentine keeps it in."""
    import base64
    if isinstance(value, str):
        return {"text": value}
    if isinstance(value, bool):
        return {"boolean": value}
    if isinstance(value, GeometryGroup):
        return {"group": [pack(shape) for shape in value.shapes]}
    if not isinstance(value, (int, float, tuple, Vector)):
        return {"geometry": base64.b64encode(
            g.shape_to_bytes(value)).decode("ascii")}
    if isinstance(value, Vector):
        return {"vector": [list(value.start), list(value.end)]}
    if isinstance(value, tuple):
        return {"point": list(value)}
    return {"number": value}


def unpack(data):
    import base64
    if "text" in data:
        return data["text"]
    if "boolean" in data:
        return bool(data["boolean"])
    if "number" in data:
        return data["number"]
    if "point" in data:
        return tuple(data["point"])
    if "vector" in data:
        start, end = data["vector"]
        return Vector(tuple(start), tuple(end))
    if "group" in data:
        return GeometryGroup(tuple(unpack(item) for item in data["group"]))
    return g.shape_from_bytes(base64.b64decode(data["geometry"]))


def pack_tree(tree) -> dict:
    return {"branches": [[list(path), [pack(v) for v in branch]]
                         for path, branch in tree.branches.items()]}


def unpack_tree(data) -> "Tree":
    return Tree({tuple(path): [unpack(v) for v in branch]
                 for path, branch in data.get("branches", [])})


class Tree:
    """Branches of items under paths, in order. Read as a sequence it is
    every item, branch after branch, so code that wants a list still has
    one."""

    def __init__(self, branches=None):
        self.branches: dict[tuple, list] = {
            tuple(path): list(items)
            for path, items in (branches or {}).items()}

    @classmethod
    def of(cls, items, path=(0,)):
        """A plain list, as a tree of one branch."""
        return cls({path: items})

    @property
    def items(self) -> list:
        return [item for branch in self.branches.values() for item in branch]

    def graft(self) -> "Tree":
        """Every item on a branch of its own, under its branch's path and
        its place in it: {0} with three items becomes {0;0} {0;1} {0;2}."""
        return Tree({path + (i,): [item]
                     for path, branch in self.branches.items()
                     for i, item in enumerate(branch)})

    def flatten(self) -> "Tree":
        return Tree.of(self.items)

    def reverse(self) -> "Tree":
        """Each branch's items the other way round, the branches kept."""
        return Tree({path: branch[::-1]
                     for path, branch in self.branches.items()})

    def merged(self, other: "Tree") -> "Tree":
        """Two trees in one input: a branch under a path both have takes
        both lists, one after the other."""
        out = Tree(self.branches)
        for path, branch in other.branches.items():
            out.branches.setdefault(path, []).extend(branch)
        return out

    def shape(self) -> str:
        """"item", "list" or "tree": what a wire carrying it is drawn as."""
        if len(self.branches) > 1:
            return "tree"
        return "item" if len(self) <= 1 else "list"

    def __len__(self):
        return sum(len(branch) for branch in self.branches.values())

    def __iter__(self):
        return iter(self.items)

    def __getitem__(self, index):
        return self.items[index]

    def __eq__(self, other):
        if isinstance(other, Tree):
            return self.branches == other.branches
        if isinstance(other, list):
            return self.items == other
        return NotImplemented

    def __repr__(self):
        return f"Tree({self.branches!r})"


# in the order they are applied: a branch is turned round, then grafted
# or flattened. Graft and Flatten rule each other out.
FLAGS = ("reverse", "graft", "flatten")


def flag_key(port_name: str, output: bool) -> str:
    """Where a port's Graft, Flatten or Reverse is kept in a node's params."""
    return ("out:" if output else "in:") + port_name


def flags_of(value) -> list:
    """A port's flags, kept as one name or a list of names, in the order
    they are applied."""
    names = [value] if isinstance(value, str) else list(value or ())
    return [f for f in FLAGS if f in names]


def apply_flag(tree: Tree, value) -> Tree:
    for flag in flags_of(value):
        tree = getattr(tree, flag)()
    return tree
