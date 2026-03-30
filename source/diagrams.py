# coding: utf8

import pydot

from .base import Graph


class Pipeline(Graph):
    """Represents a pipeline diagram.

    `nodes` is a dictionary of nodes `name` -> `shape`.
    `edges` is a list of edges, tuples of the form `(name, name, label)`.
    `**kwargs` is a list of args passed to `pydot` directly.

    >>> Pipeline(['HULK', 'AST-HULK', 'AST-CIL', 'MIPS'], [
        (0, 1, 'lexer/parser'),
        (1, 1, 'semántica'),
        (1, 2, 'generación'),
        (2, 3, 'generación')
    ])
    """

    def __init__(self, nodes, edges, startshape='box', endshape='box', innershape='box'):
        self.nodes = nodes
        self.edges = edges
        self.startshape = startshape
        self.endshape = endshape
        self.innershape = innershape

    def graph(self):
        G = pydot.Dot(rankdir='LR', margin=0.1, rank='same')

        for i, node in enumerate(self.nodes):
            if i == 0:
                shape = self.startshape
            elif i == len(self.nodes) - 1:
                shape = self.endshape
            else:
                shape = self.innershape

            G.add_node(pydot.Node(i, shape=shape, label=node))

        for (start, end, label) in self.edges:
            G.add_edge(pydot.Edge(start, end, label=label, labeldistance=2))

        return G


class Lexer(Graph):
    def __init__(self, string, state=-1):
        self.string = string
        self.state = state

    def graph(self):
        graph = pydot.Dot(margin=0.1, nodesep=0.05)

        for i,x in enumerate(self.string):
            if i == self.state:
                graph.add_node(pydot.Node(i, label=x, shape='box', width=0.3, height=0.3, style='filled', fillcolor='black', fontcolor='white'))
            else:
                graph.add_node(pydot.Node(i, label=x, shape='box', width=0.3, height=0.3, style='solid'))

        return graph
