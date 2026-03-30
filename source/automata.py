# coding: utf8

import pydot

from .base import Graph


class Automaton(Graph):
    def __init__(self, start, final, states, shape='circle'):
        self.start = start
        self.states = states
        self.final = final
        self._shape = shape

    def graph(self):
        G = pydot.Dot(rankdir='LR', margin=0.1)
        G.add_node(pydot.Node('start', shape='plaintext', label='', width=0, height=0))

        for (start, tran), end in self.states.items():
            G.add_node(pydot.Node(start, shape=self._shape, style='bold' if start in self.final else ''))
            G.add_node(pydot.Node(end, shape=self._shape, style='bold' if end in self.final else ''))
            G.add_edge(pydot.Edge(start, end, label=tran, labeldistance=2))

        G.add_edge(pydot.Edge('start', self.start, label='', style='dashed'))
        return G
