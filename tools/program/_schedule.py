"""Private buffer schedule used during StableHLO-to-C lowering, not an input IR."""
from dataclasses import dataclass, field
import collections
import math
import numpy as np


class ProgramError(ValueError):
    pass


DTYPES = ('float32', 'int32', 'uint32', 'bool', 'int8', 'uint8')


@dataclass
class Value:
    id: int
    shape: tuple
    dtype: str
    data: object = None

    @property
    def size(self):
        return math.prod(self.shape)


@dataclass
class Node:
    op: str
    inputs: list
    output: int
    params: dict = field(default_factory=dict)
    extra_outputs: list = field(default_factory=list)

    @property
    def outputs(self):
        return [self.output, *self.extra_outputs]


class ExecutionPlan:
    def __init__(self):
        self.values = []
        self.nodes = []
        self.inputs = []
        self.outputs = []
        self.folded = 0
        self.inlined_loops = 0

    def value(self, shape, dtype, data=None):
        dtype = str(np.dtype(dtype))
        shape = tuple(shape)
        if dtype not in DTYPES:
            raise ProgramError(f'unsupported IR dtype {dtype}')
        if any(not isinstance(d, (int, np.integer)) or d <= 0 for d in shape):
            raise ProgramError(f'IR requires positive static dimensions, got {shape}')
        shape = tuple(int(d) for d in shape)
        if math.prod(shape) > 0x7fffffff:
            raise ProgramError('tensor exceeds signed 32-bit indexing limit')
        array = None if data is None else np.asarray(data, dtype=dtype).reshape(shape)
        value = Value(len(self.values), shape, dtype, array)
        self.values.append(value)
        return value.id

    def const(self, value):
        array = np.asarray(value)
        return self.value(array.shape, array.dtype, array)

    def operation(self, op, inputs, shape, dtype, **params):
        output = self.value(shape, dtype)
        self.nodes.append(Node(op, list(inputs), output, params))
        return output

    def validate(self):
        """Structural verification; target legality is a separate compiler pass."""
        def ids(items):
            return all(isinstance(i, int) and 0 <= i < len(self.values) for i in items)
        if not ids(self.inputs + self.outputs) or not self.outputs:
            raise ProgramError('invalid function input/output IDs (at least one output required)')
        if len(set(self.inputs)) != len(self.inputs):
            raise ProgramError('duplicate function input')
        available = {v.id for v in self.values if v.data is not None}
        if any(i in available for i in self.inputs):
            raise ProgramError('a function input cannot also be a constant')
        available.update(self.inputs)
        for index, node in enumerate(self.nodes):
            prefix = f'node {index} ({node.op}, value {node.output})'
            if not ids(node.inputs + node.outputs):
                raise ProgramError(f'{prefix}: invalid value ID')
            if any(i in available for i in node.outputs) or len(set(node.outputs)) != len(node.outputs):
                raise ProgramError(f'{prefix}: SSA value has multiple definitions')
            if any(i not in available for i in node.inputs):
                raise ProgramError(f'{prefix}: operand has no preceding definition')
            available.update(node.outputs)
        if any(i not in available for i in self.outputs):
            raise ProgramError('function output has no definition')
        return self

    def dce(self):
        live = set(self.outputs)
        kept = []
        for node in reversed(self.nodes):
            if live.intersection(node.outputs):
                kept.append(node)
                live.update(node.inputs)
                live.update(node.outputs)
        self.nodes = list(reversed(kept))
        return live | set(self.inputs)

    def summary(self):
        return {'nodes': len(self.nodes),
                'operations': dict(collections.Counter(n.op for n in self.nodes)),
                'constant_folded': self.folded, 'static_loops_inlined': self.inlined_loops}
