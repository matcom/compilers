# coding: utf8

import uuid
import pydot

from .base import Graph


class Tree(Graph):
    def __init__(self, root, *children):
        self.id = str(uuid.uuid4())
        self.root = root
        self.children = children

    def graph(self, parent=None, graph=None):
        if graph is None:
            graph = pydot.Dot()

        graph.add_node(pydot.Node(self.id, label=self.root))

        if parent is not None:
            graph.add_edge(pydot.Edge(parent, self.id))

        for child in self.children:
            child.graph(self.id, graph)

        return graph
