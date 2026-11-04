"""Hydra: a visual graph of components, in the spirit of Grasshopper. Kept
free of Qt so the graph solves the same in tests and in the editor.

The geometry components each hold model objects of their kind, set by
picking them, and hand them on as a list. A Number Slider hands on one
number, between a range and to as many decimal places as it is set to.

Every wire carries a tree, as in Grasshopper: branches of items, each
branch under a path such as {0} or {0;1}. A plain list is a tree of one
branch, {0}. A component pairs its inputs' branches by the longest list,
then within each pair of branches their items the same way, reusing the
last of the shorter: three curves and one angle make three rotated curves.
Graft, set on a port, puts every item on a branch of its own; Flatten puts
them all on one; Reverse turns each branch round, and goes with either.

kinds.py says what flows along the wires, tree.py how it is held, graph.py
solves the graph, and components/ has the components, a module per
category.
"""

from .kinds import (
    GEOMETRY_KINDS, GeometryGroup, HydraError, Port, Vector, arrow, as_text,
    coerce, coordinates, number_text, shapes_in,
    describe, describe_item, fits, format_number, is_shape, kind_said,
    said_of, takes,
)
from .tree import (
    FLAGS, Tree, apply_flag, count_said, flag_key, flags_of, list_tree,
    pack, pack_tree, unpack, unpack_tree,
)
from .components import (
    CATEGORIES, COMPONENTS, NICKNAMES, QUICK, Component, Result,
    find_components,
)
from .components.geometry import COMPONENTS_PLURAL
from .components.maths import MOST_NUMBERS, operation_from_text
from .components.mesh import faceted
from .components.inputs import (
    MAX_DECIMALS, PIPE_TYPES, panel_from_text, panel_lines, parse_number,
    piped, set_decimals, set_range, set_slider, slider_from_text,
    type_into_slider,
)
from .graph import Graph, Node, Wire
