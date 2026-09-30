"""Exact finite ROBDD equivalence for combinational packed LUT/mux cones.

Every cut is independent; no vector sampling or assumptions on reachable state.
The node cap fails closed, and the independent primitive SAT proof is separate.
"""
from functools import lru_cache
from synapse32_packed_counter_encoding import logical


def compare(old, new, cuts, outputs, node_limit=1000000):
    assert len(cuts) == len(set(cuts))
    nodes = [None, None]
    unique = {}
    def node(var, low, high):
        if low == high:
            return low
        key = (var, low, high)
        if key not in unique:
            assert len(nodes) < node_limit, 'BDD node cap exceeded'
            unique[key] = len(nodes)
            nodes.append(key)
        return unique[key]
    def rank(u):
        return nodes[u][0] if u > 1 else len(cuts)
    @lru_cache(None)
    def ite(s, high, low):
        if s == 0: return low
        if s == 1: return high
        if high == low: return high
        if high == 1 and low == 0: return s
        var = min(rank(s), rank(high), rank(low))
        def split(u, bit):
            return nodes[u][1 + bit] if rank(u) == var else u
        return node(var, ite(split(s, 0), split(high, 0), split(low, 0)),
                    ite(split(s, 1), split(high, 1), split(low, 1)))
    variables = {b: node(i, 0, 1) for i, b in enumerate(cuts)}
    def evaluate(cells):
        values = dict(variables)
        for cell in cells.values():
            width, ports, mask = logical(cell)
            inputs = [values[ports[f'I{i}']] for i in range(width)]
            def table(i, offset):
                if i == width: return (mask >> offset) & 1
                return ite(inputs[i], table(i + 1, offset | (1 << i)), table(i + 1, offset))
            assert ports['O'] not in values, 'duplicate driver or output aliases cut'
            values[ports['O']] = table(0, 0)
        return [values[b] for b in outputs]
    a, b = evaluate(old), evaluate(new)
    assert a == b, 'BDD equivalence failed'
    return dict(passed=True, independent_cuts=len(cuts), outputs=len(outputs),
                bdd_nodes=len(nodes), method='canonical reduced ordered BDD equality')
