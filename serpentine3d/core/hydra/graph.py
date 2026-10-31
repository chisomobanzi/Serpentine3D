"""The graph: components and the wires between them, solved in order."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from .. import geometry as g
from .components import COMPONENTS, Component, Result
from .kinds import (
    GEOMETRY_KINDS, HydraError, Port, Vector, arrow, coerce, fits,
    kind_said, said_of, shapes_in, takes,
)
from .tree import Tree, apply_flag, flag_key, pack_tree, unpack_tree


@dataclass
class Node:
    id: str
    key: str
    x: float = 0.0
    y: float = 0.0
    params: dict = field(default_factory=dict)
    preview: bool = True
    # internalized data read back from params, kept so it is read once,
    # not on every solve; never saved
    memo: dict = field(default_factory=dict, repr=False, compare=False)

    @property
    def component(self) -> Component:
        return COMPONENTS[self.key]

    @property
    def title(self) -> str:
        """The name it was given, or its component's."""
        return self.params.get("name") or self.component.title

    def rename(self, name: str):
        """Give it a name of its own; none, or its component's, takes the
        component's back."""
        name = (name or "").strip()
        if not name or name == self.component.title:
            self.params.pop("name", None)
        else:
            self.params["name"] = name

    def internal(self, key: str):
        """The data internalized under `key`, as a tree, or None."""
        packed = self.params.get("internal", {}).get(key)
        if packed is None:
            return None
        if key not in self.memo:
            self.memo[key] = unpack_tree(packed)
        return self.memo[key]

    def set_internal(self, key: str, tree):
        """Keep `tree` in the graph under `key`, or let it go with None."""
        kept = self.params.setdefault("internal", {})
        self.memo.pop(key, None)
        if tree is None:
            kept.pop(key, None)
        else:
            kept[key] = pack_tree(tree)
        if not kept:
            self.params.pop("internal")


@dataclass(frozen=True)
class Wire:
    source: str
    output: str
    target: str
    input: str


class Graph:
    def __init__(self):
        self.nodes: dict[str, Node] = {}
        self.wires: list[Wire] = []
        # components drawn together on one background: a group's id, and
        # the ids of the components in it; a component is in one at most
        self.groups: dict[str, list[str]] = {}
        self.group_names: dict[str, str] = {}   # those given a name

    def add_node(self, key: str, x: float = 0.0, y: float = 0.0,
                 params: dict | None = None, node_id: str | None = None):
        if key not in COMPONENTS:
            raise HydraError(f"Unknown component '{key}'")
        comp = COMPONENTS[key]
        values = {"refs": []} if comp.picks else dict(comp.params)
        values.update(params or {})
        node = Node(node_id or uuid.uuid4().hex[:8], key, float(x), float(y),
                    values)
        self.nodes[node.id] = node
        return node

    def remove_node(self, node_id: str):
        self.nodes.pop(node_id, None)
        self.wires = [w for w in self.wires
                      if node_id not in (w.source, w.target)]
        self._leave_groups([node_id])

    # --------------------------------------------------------------- groups

    def group(self, node_ids, group_id: str | None = None) -> str | None:
        """Put these components in a group of their own, out of any they
        were in. Returns the group's id, or None for no components."""
        ids = [nid for nid in dict.fromkeys(node_ids) if nid in self.nodes]
        if not ids:
            return None
        self._leave_groups(ids)
        group_id = group_id or uuid.uuid4().hex[:8]
        self.groups[group_id] = ids
        return group_id

    def add_to_group(self, group_id: str, node_ids) -> list:
        """Put these components in a group as well, out of any other they
        were in; its name stays. Returns those it took."""
        members = self.groups.get(group_id)
        if members is None:
            return []
        fresh = [nid for nid in dict.fromkeys(node_ids)
                 if nid in self.nodes and nid not in members]
        if fresh:
            for gid in [g for g in self.groups if g != group_id]:
                self.groups[gid] = [n for n in self.groups[gid]
                                    if n not in fresh]
                if not self.groups[gid]:
                    self.ungroup(gid)
            members.extend(fresh)
        return fresh

    def ungroup(self, group_id: str):
        """The group gone; its components stay where they are."""
        self.groups.pop(group_id, None)
        self.group_names.pop(group_id, None)

    def name_group(self, group_id: str, name: str):
        """Give a group a name, shown over it; an empty one takes it away."""
        name = (name or "").strip()
        if group_id not in self.groups:
            return
        if name:
            self.group_names[group_id] = name
        else:
            self.group_names.pop(group_id, None)

    def group_of(self, node_id: str) -> str | None:
        return next((gid for gid, ids in self.groups.items()
                     if node_id in ids), None)

    def _leave_groups(self, node_ids):
        gone = set(node_ids)
        for gid in list(self.groups):
            self.groups[gid] = [n for n in self.groups[gid] if n not in gone]
            if not self.groups[gid]:
                self.ungroup(gid)

    def connect(self, source: str, output: str, target: str,
                input: str, add: bool = False) -> Wire:
        """Wire an output into an input. A new wire takes the place of the
        one already there; with `add` it goes in beside it, and the input
        takes both lists, one after the other, as Shift does in
        Grasshopper."""
        src, dst = self.nodes.get(source), self.nodes.get(target)
        if src is None or dst is None:
            raise HydraError("Both ends of a wire need a component")
        if output not in [p.name for p in src.component.outputs]:
            raise HydraError(f"{src.component.title} has no output {output}")
        if input not in [p.name for p in dst.component.inputs]:
            raise HydraError(f"{dst.component.title} has no input {input}")
        if source == target or self._reaches(target, source):
            raise HydraError("A wire cannot loop back into its own source")
        out_kind = _port(src.component.outputs, output).kind
        in_kind = _port(dst.component.inputs, input).kind
        if not takes(in_kind, out_kind):
            raise HydraError(f"{dst.component.title} {input} takes "
                             f"{kind_said(in_kind)}, not {kind_said(out_kind)}")
        wire = Wire(source, output, target, input)
        if not add:
            self.wires = [w for w in self.wires
                          if (w.target, w.input) != (target, input)]
        if wire not in self.wires:
            self.wires.append(wire)
        return wire

    def wire_between(self, source, output, target, input):
        """The wire from that output into that input, if there is one."""
        wire = Wire(source, output, target, input)
        return wire if wire in self.wires else None

    def disconnect(self, wire: Wire):
        if wire in self.wires:
            self.wires.remove(wire)

    def _reaches(self, start: str, goal: str) -> bool:
        stack, seen = [start], set()
        while stack:
            node = stack.pop()
            if node == goal:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(w.target for w in self.wires if w.source == node)
        return False

    def order(self) -> list[str]:
        """Every component after the ones wired into it."""
        waiting = {nid: 0 for nid in self.nodes}
        for w in self.wires:
            waiting[w.target] += 1
        ready = [nid for nid, n in waiting.items() if n == 0]
        order = []
        while ready:
            nid = ready.pop(0)
            order.append(nid)
            for w in self.wires:
                if w.source == nid:
                    waiting[w.target] -= 1
                    if waiting[w.target] == 0:
                        ready.append(w.target)
        return order

    def solve(self, scene) -> dict[str, Result]:
        results: dict[str, Result] = {}
        for nid in self.order():
            results[nid] = self._solve_node(self.nodes[nid], scene, results)
        return results

    def _solve_node(self, node: Node, scene, results) -> Result:
        result = self._made(node, scene, results)
        # an output's Graft or Flatten, on what it hands on
        flags = node.params.get("flags", {})
        for name, tree in list(result.outputs.items()):
            result.outputs[name] = apply_flag(
                tree, flags.get(flag_key(name, True)))
        return result

    def _made(self, node: Node, scene, results) -> Result:
        comp = node.component
        if comp.solve is not None:
            return self._compute(node, results)
        if comp.made is not None:
            return comp.made(self, node, scene, results)
        if not comp.picks:
            return Result({comp.outputs[0].name:
                           Tree.of([node.params["value"]])})
        kept = node.internal("out")
        if kept is not None:
            # internalized: the graph's own copy, whatever the model holds
            return Result({comp.outputs[0].name: kept})
        refs = node.params.get("refs", [])
        found = [obj for obj in map(scene.get, refs) if obj is not None]
        result = Result({comp.outputs[0].name:
                         Tree.of([o.shape for o in found])})
        if not refs:
            result.status = "warning"
            result.message = (f"Right-click and {comp.sets}... to pick "
                              f"{comp.plural} in the model")
        elif len(found) < len(refs):
            result.status = "warning"
            gone = len(refs) - len(found)
            result.message = (f"{gone} picked object"
                              + (" is" if gone == 1 else "s are")
                              + " no longer in the model")
        return result

    def input_values(self, node_id: str, port: Port, results) -> tuple:
        """What reaches an input, as the component works on it, and whether
        it comes by wire: the source's output if one is wired in; if not,
        what was internalized in it, or set for it by picking in the model,
        or else its default. The input's Graft or Flatten is applied."""
        node = self.nodes[node_id]
        flag = node.params.get("flags", {}).get(flag_key(port.name, False))
        wires = [w for w in self.wires
                 if w.target == node_id and w.input == port.name]
        if not wires:
            kept = node.internal(port.name)
            if kept is not None:
                return apply_flag(kept, flag), False
            picked = node.params.get("set", {}).get(port.name)
            if picked is not None:
                return apply_flag(Tree.of([tuple(picked)]), flag), False
            values = [] if port.default is None else [port.default]
            return apply_flag(Tree.of(values), flag), False
        return apply_flag(self.wired_tree(node_id, port.name, results),
                          flag), True

    def wired_tree(self, node_id, input, results) -> "Tree":
        """What the wires into an input bring, before its own flags:
        several wires' trees in one, in the order they were wired."""
        tree = Tree()
        for wire in self.wires:
            if wire.target == node_id and wire.input == input:
                source = results.get(wire.source)
                if source is not None:
                    tree = tree.merged(source.outputs.get(wire.output,
                                                          Tree()))
        return tree

    # ---------------------------------------------------------- internalize

    def internalize(self, node_id, scene) -> int:
        """Keep a geometry component's objects as the graph's own copy, no
        longer the model's: deleted or changed there, they stay as they
        were here. Returns how many."""
        from ...script_runtime import isolated_copy
        node = self.nodes[node_id]
        found = [obj for obj in map(scene.get, node.params.get("refs", []))
                 if obj is not None]
        if not found:
            raise HydraError("Nothing picked to internalize")
        node.set_internal("out", Tree.of([isolated_copy(o.shape)
                                          for o in found]))
        node.params["refs"] = []
        return len(found)

    def internalize_input(self, node_id, input, results) -> int:
        """Keep what the wires bring into an input as the input's own, and
        take the wires away. Its flags stay and still apply. Returns how
        many items."""
        tree = self.wired_tree(node_id, input, results)
        if not len(tree):
            raise HydraError("No data comes into it to internalize")
        self.nodes[node_id].set_internal(input, tree)
        self.wires = [w for w in self.wires
                      if (w.target, w.input) != (node_id, input)]
        return len(tree)

    def _compute(self, node: Node, results) -> Result:
        comp = node.component
        empty = {p.name: Tree() for p in comp.outputs}
        args, missing = {}, []
        for port in comp.inputs:
            tree, _wired = self.input_values(node.id, port, results)
            if not len(tree) and port.optional:
                tree = Tree.of([None])      # worked without, as asked
            elif not len(tree):
                missing.append(port.name)
            args[port.name] = tree
        if missing:
            said = "Connect " + " and ".join(missing)
            if comp.sets:
                said += f", or right-click and {comp.sets}..."
            return Result(empty, "warning", said)
        # the branches pair by the longest list, and the paths of the input
        # with the most of them name the branches that come out
        branches = {name: list(tree.branches.items())
                    for name, tree in args.items()}
        widest = max(branches.values(), key=len)
        outs = {p.name: Tree() for p in comp.outputs}
        for b in range(len(widest)):
            pair = {name: bs[min(b, len(bs) - 1)][1]
                    for name, bs in branches.items()}
            whole = {p.name for p in comp.inputs if p.access == "list"}
            items = {name: values for name, values in pair.items()
                     if name not in whole}
            made = {p.name: [] for p in comp.outputs}
            if all(pair.values()):
                # then, within the pair, their items the same way; a list
                # input takes its branch whole, every time
                for i in range(max((len(v) for v in items.values()),
                                   default=1)):
                    kinds = {p.name: p.kind for p in comp.inputs}
                    item = {name: coerce(kinds[name],
                                         values[min(i, len(values) - 1)])
                            for name, values in items.items()}
                    item.update({name: list(pair[name]) for name in whole})
                    wrong = self._misfit(comp, item)
                    if wrong:
                        return Result(empty, "error", wrong)
                    try:
                        value = comp.solve(**item)
                    except (HydraError, g.GeometryError, ValueError,
                            RuntimeError) as exc:
                        return Result(empty, "error",
                                      str(exc) or type(exc).__name__)
                    # a component with several outputs gives one value for
                    # each, in their order
                    values = (value if len(comp.outputs) > 1 else (value,))
                    for port, given in zip(comp.outputs, values):
                        # an output that gives lists gives its items to the
                        # branch, not the list as one item
                        if port.access == "list":
                            made[port.name].extend(given)
                        else:
                            made[port.name].append(given)
            for name, items in made.items():
                outs[name].branches[widest[b][0]] = items
        return Result(outs)

    @staticmethod
    def _misfit(comp, item):
        """What is wrong with the items a component is about to work on,
        when something that may carry anything brought the wrong thing."""
        for port in comp.inputs:
            values = (item[port.name] if port.access == "list"
                      else [item[port.name]])
            for value in values:
                if value is None and port.optional:
                    continue            # left empty, as it may be
                if not fits(port.kind, value):
                    return (f"{comp.title} {port.name} takes "
                            f"{kind_said(port.kind)}, not {said_of(value)}")
        return ""

    def preview_shapes(self, results: dict[str, Result], only=None,
                       hidden=False) -> list:
        """What the components show in the model: the shown ones, or with
        `only` those components, and with `hidden` the hidden among them
        too."""
        shapes = []
        for nid, result in results.items():
            if only is not None and nid not in only:
                continue
            if not (hidden or self.nodes[nid].preview):
                continue
            for port in self.nodes[nid].component.outputs:
                values = result.outputs.get(port.name, [])
                if port.kind in GEOMETRY_KINDS:
                    shapes.extend(shapes_in(values))
                elif port.kind == "vector":
                    # one with no length has nothing to show
                    shapes.extend(arrow(v.start, v.end) for v in values
                                  if v.length > 1e-12)
                elif port.kind == "any":
                    # what it carries shows as what it is
                    shapes.extend(shapes_in(values))
                    shapes.extend(arrow(v.start, v.end) for v in values
                                  if isinstance(v, Vector)
                                  and v.length > 1e-12)
        return shapes

    # ------------------------------------------------------------- copying

    def part(self, node_ids) -> dict:
        """Some components and the wires between them, as to_dict writes a
        graph: what Copy puts on the clipboard. Wires from components left
        out stay behind, as they do in Grasshopper."""
        ids = set(node_ids)
        data = self.to_dict()
        data["nodes"] = [n for n in data["nodes"] if n["id"] in ids]
        data["wires"] = [w for w in data["wires"]
                         if w[0] in ids and w[2] in ids]
        # a group copied whole goes with them
        data["groups"] = [g for g in data["groups"]
                          if all(n in ids for n in g[1])]
        return data

    def paste(self, data: dict, dx: float = 0.0, dy: float = 0.0) -> list:
        """Add a copied part as new components, moved by dx and dy, wired
        among themselves as they were. Returns the new components' ids."""
        import copy
        fresh = {}
        for item in data.get("nodes", []):
            if item.get("key") not in COMPONENTS:
                continue
            node = self.add_node(item["key"], item.get("x", 0.0) + dx,
                                 item.get("y", 0.0) + dy,
                                 copy.deepcopy(item.get("params")))
            node.preview = bool(item.get("preview", True))
            fresh[item.get("id")] = node.id
        for source, output, target, input in data.get("wires", []):
            if source in fresh and target in fresh:
                try:
                    self.connect(fresh[source], output, fresh[target], input)
                except HydraError:
                    pass
        for entry in data.get("groups", []):
            gid = self.group([fresh[n] for n in entry[1] if n in fresh])
            if gid is not None and len(entry) > 2:
                self.name_group(gid, entry[2])
        return list(fresh.values())

    # ---------------------------------------------------------- persistence

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "nodes": [{"id": n.id, "key": n.key, "x": n.x, "y": n.y,
                       "params": dict(n.params), "preview": n.preview}
                      for n in self.nodes.values()],
            "wires": [[w.source, w.output, w.target, w.input]
                      for w in self.wires],
            "groups": [[gid, list(ids)] + ([self.group_names[gid]]
                                           if gid in self.group_names else [])
                       for gid, ids in self.groups.items()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Graph":
        graph = cls()
        for item in data.get("nodes", []):
            if item.get("key") not in COMPONENTS:
                continue
            node = graph.add_node(item["key"], item.get("x", 0.0),
                                  item.get("y", 0.0), item.get("params"),
                                  node_id=item.get("id"))
            node.preview = bool(item.get("preview", True))
        for wire in data.get("wires", []):
            try:
                graph.connect(*wire)
            except (HydraError, TypeError):
                pass
        for entry in data.get("groups", []):
            try:
                gid, members, *name = entry
                graph.group(members, gid)
                graph.name_group(gid, name[0] if name else "")
            except (TypeError, ValueError, IndexError):
                pass
        return graph


def _port(ports, name) -> Port:
    return next(p for p in ports if p.name == name)
