"""Exhaustively verify one five-input LUT composition and every other packed cell."""
import copy
from itertools import product
from synapse32_packed_equivalence import canonical_cells

PREFIX = '$abc$220657$auto$blifparse.cc:557:parse_blif$'
CONE = [PREFIX + n for n in ('221267', '221749', '237143')]
TARGET = CONE[-1]


def verify_packed_logic(original, candidate):
    gold = canonical_cells(original)
    gate = canonical_cells(candidate)
    assert set(gold) == set(gate) == {'top'}
    before, after = gold['top'], gate['top']
    assert set(before) == set(after)
    for name in before:
        if name != TARGET:
            assert before[name] == after[name], name
    a, b = copy.deepcopy(before[TARGET]), copy.deepcopy(after[TARGET])
    assert a['type'] == b['type'] == 'SLICE_LUTX'
    assert a['attributes']['X_ORIG_TYPE'] == 'LUT3'
    assert b['attributes']['X_ORIG_TYPE'] == 'LUT5'
    for cell in (a, b):
        cell['attributes'].pop('X_ORIG_TYPE')
        cell['parameters'].pop('INIT')
        cell.pop('connections')
        cell.pop('port_directions')
    assert a == b, 'Only target LUT truth table and its input wiring may change'

    def lut(cell):
        size = int(cell['attributes']['X_ORIG_TYPE'][3:])
        assert set(cell['connections']) == {'O'} | {f'I{i}' for i in range(size)}
        assert cell['port_directions']['O'] == 'output'
        for i in range(size):
            assert cell['port_directions'][f'I{i}'] == 'input'
        assert all(len(bits) == 1 for bits in cell['connections'].values())
        inputs = [cell['connections'][f'I{i}'][0] for i in range(size)]
        output = cell['connections']['O'][0]
        init = cell['parameters']['INIT']
        assert len(init) == 1 << size and set(init) <= {'0', '1'}
        return inputs, output, int(init, 2)

    steps = [lut(before[n]) for n in CONE]
    composed = lut(after[TARGET])
    outputs = {output for _, output, _ in steps}
    leaves = set(x for inputs, _, _ in steps for x in inputs) - outputs
    assert len(leaves) == 5 and set(composed[0]) == leaves
    assert composed[1] == steps[-1][1]
    for values in product((0, 1), repeat=len(leaves)):
        external = dict(zip(sorted(leaves), values))
        working = dict(external)
        for inputs, output, init in steps:
            index = sum(working[bit] << i for i, bit in enumerate(inputs))
            working[output] = (init >> index) & 1
        index = sum(external[bit] << i for i, bit in enumerate(composed[0]))
        assert working[composed[1]] == ((composed[2] >> index) & 1)
    return True
