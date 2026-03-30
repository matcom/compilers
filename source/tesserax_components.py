# coding: utf8
"""Tesserax-based diagram components for the Compilers course book."""

import math
import html
from typing import Optional

from tesserax import Rect, Text, Arrow, Circle, Group, Polyline
from tesserax.layout import RowLayout, HierarchicalLayout
from tesserax.core import Point, Component
from tesserax.color import Colors


def _escape(text: str) -> str:
    """Escape text for SVG."""
    return html.escape(str(text))


class Pipeline(Component):
    """A horizontal pipeline diagram with boxes and arrows."""

    def __init__(
        self,
        labels: list[str],
        edges: list,
        startshape: str = "box",
        endshape: str = "box",
        innershape: str = "box",
    ):
        super().__init__()
        self.labels = labels
        self.edges = edges
        self.startshape = startshape
        self.endshape = endshape
        self.innershape = innershape

    def _get_shape(self, index: int) -> str:
        if index == 0:
            return self.startshape
        elif index == len(self.labels) - 1:
            return self.endshape
        return self.innershape

    def _build(self) -> Group:
        box_width = 80
        box_height = 40
        gap = 30

        with Group() as g:
            with RowLayout(gap=gap) as row:
                boxes = []
                for i, label in enumerate(self.labels):
                    shape = self._get_shape(i)
                    if shape != "plaintext":
                        r = Rect(box_width, box_height, fill=Colors.LightBlue, stroke=Colors.DarkBlue, width=2)
                        boxes.append(r)
                    else:
                        boxes.append(None)

            for i, (box, label) in enumerate(zip(boxes, self.labels)):
                if box is not None:
                    Text(_escape(label), size=12, fill=Colors.Black).align_to(box, "center")

            for (start_idx, end_idx, label) in self.edges:
                if start_idx == end_idx:
                    box = boxes[start_idx]
                    if box is not None:
                        cx = box.anchor("center").x
                        cy = box.anchor("top").y
                        loop_r = 25
                        p1 = Point(cx - loop_r * 0.7, cy - loop_r)
                        p2 = Point(cx, cy - loop_r * 1.5)
                        p3 = Point(cx + loop_r * 0.7, cy - loop_r)
                        Polyline([p1, p2, p3], stroke=Colors.DarkGray, marker_end="arrow", width=1.5)
                        if label:
                            Text(_escape(label), size=10, fill=Colors.DarkGray).translated(cx, cy - loop_r * 2 - 5)
                else:
                    start_box = boxes[start_idx]
                    end_box = boxes[end_idx]
                    if start_box is not None and end_box is not None:
                        Arrow(start_box.anchor("right"), end_box.anchor("left"))
                        if label:
                            mid_x = (start_box.anchor("right").x + end_box.anchor("left").x) / 2
                            mid_y = start_box.anchor("right").y - 12
                            Text(_escape(label), size=10, fill=Colors.DarkGray).translated(mid_x, mid_y)

        return g


class Tree(Component):
    """A hierarchical tree diagram with circles and arrows."""

    def __init__(self, root: str, *children: "Tree"):
        super().__init__()
        self.root = root
        self.children = list(children)

    def _collect_nodes(self):
        """Collect all nodes and edges."""
        nodes = {}
        edges = []

        def traverse(tree: Tree, parent_label: Optional[str] = None):
            if tree.root not in nodes:
                nodes[tree.root] = tree
            if parent_label:
                edges.append((parent_label, tree.root))
            for child in tree.children:
                traverse(child, tree.root)

        traverse(self)
        return nodes, edges

    def _build(self) -> Group:
        nodes, edges = self._collect_nodes()

        node_shapes = {}
        for label, tree in nodes.items():
            is_root = label == self.root
            node_shapes[label] = Circle(25, fill=Colors.LightYellow if is_root else Colors.LightBlue, stroke=Colors.DarkBlue, width=1.5)

        with Group() as g:
            with HierarchicalLayout(orientation="vertical") as layout:
                for label in nodes:
                    layout.add(node_shapes[label])
                for parent_label, child_label in edges:
                    layout.connect(node_shapes[parent_label], node_shapes[child_label])
                layout.root(node_shapes[self.root])

            for parent_label, child_label in edges:
                Arrow(node_shapes[parent_label].anchor("bottom"), node_shapes[child_label].anchor("top"))

            for label, shape in node_shapes.items():
                Text(_escape(label), size=12, fill=Colors.Black).align_to(shape, "center")

        return g


class Lexer(Component):
    """A token sequence visualization."""

    def __init__(self, tokens: list[str], highlight: int = -1):
        super().__init__()
        self.tokens = tokens
        self.highlight = highlight

    def _build(self) -> Group:
        token_width = 35
        token_height = 30
        gap = 2

        with Group() as g:
            with RowLayout(gap=gap) as row:
                for i, token in enumerate(self.tokens):
                    if i == self.highlight:
                        Rect(token_width, token_height, fill=Colors.LightSalmon, stroke=Colors.DarkRed, width=2)
                    else:
                        Rect(token_width, token_height, fill=Colors.White, stroke=Colors.LightGray, width=1)

            for i, (shape, token) in enumerate(zip(row.shapes, self.tokens)):
                Text(_escape(token), size=10, fill=Colors.Black).align_to(shape, "center")

        return g


class Automaton(Component):
    """An automaton (DFA/NFA) visualization."""

    def __init__(self, start: str, final: list[str], states: dict):
        super().__init__()
        self.start = start
        self.final = final
        self.states = states

    def _get_boundary_point(self, center: Point, target: Point, radius: float) -> Point:
        dx = target.x - center.x
        dy = target.y - center.y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist == 0:
            return center
        return Point(
            center.x + (dx / dist) * radius,
            center.y + (dy / dist) * radius,
        )

    def _build(self) -> Group:
        radius = 22

        unique_states = {self.start}
        for (s1, _), s2 in self.states.items():
            unique_states.add(s1)
            unique_states.add(s2)
        unique_states = sorted(unique_states, key=lambda x: (x != self.start, x))

        state_positions = {}
        n = len(unique_states)
        cols = min(4, n)
        rows = (n + cols - 1) // cols
        horiz_gap = 100
        vert_gap = 80
        start_x = 80
        start_y = 60

        for i, state in enumerate(unique_states):
            col = i % cols
            row = i // cols
            x = start_x + col * horiz_gap
            y = start_y + row * vert_gap
            state_positions[state] = Point(x, y)

        with Group() as g:
            for state in unique_states:
                is_final = state in self.final
                pos = state_positions[state]
                Circle(radius, fill=Colors.White, stroke=Colors.Black, width=2).translated(pos.x, pos.y)
                if is_final:
                    Circle(radius - 4, fill=Colors.Transparent, stroke=Colors.Black, width=1.5).translated(pos.x, pos.y)

            drawn_edges = set()
            for (s1, symbol), s2 in self.states.items():
                edge_key = tuple(sorted([s1, s2])) + (symbol,)
                if edge_key not in drawn_edges or s1 == s2:
                    drawn_edges.add(edge_key)
                    src_pos = state_positions[s1]
                    dst_pos = state_positions[s2]

                    if s1 == s2:
                        loop_r = 25
                        p1 = Point(src_pos.x - loop_r * 0.7, src_pos.y - loop_r)
                        p2 = Point(src_pos.x, src_pos.y - loop_r * 1.5)
                        p3 = Point(src_pos.x + loop_r * 0.7, src_pos.y - loop_r)
                        Polyline([p1, p2, p3], stroke=Colors.DarkGray, marker_end="arrow", width=1.5)
                        Text(_escape(symbol), size=10, fill=Colors.DarkGray).translated(src_pos.x, src_pos.y - loop_r * 2 - 5)
                    else:
                        p1 = self._get_boundary_point(src_pos, dst_pos, radius)
                        p2 = self._get_boundary_point(dst_pos, src_pos, radius)
                        Arrow(p1, p2)
                        mid_x = (p1.x + p2.x) / 2
                        mid_y = (p1.y + p2.y) / 2 - 8
                        Text(_escape(symbol), size=10, fill=Colors.DarkGray).translated(mid_x, mid_y)

            start_pos = state_positions[self.start]
            Arrow(Point(start_pos.x - 50, start_pos.y), Point(start_pos.x - radius - 5, start_pos.y))

            for state in unique_states:
                pos = state_positions[state]
                Text(_escape(state), size=12, fill=Colors.Black).translated(pos.x, pos.y)

        return g
