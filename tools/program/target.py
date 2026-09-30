"""Backend capabilities and legalization, independent of the source frontend."""
from dataclasses import dataclass, asdict
import numpy as np
from ._schedule import ProgramError
from .cost import AffineCostModel


CPU_OPS = frozenset(('add', 'add_any', 'sub', 'mul', 'div', 'neg', 'abs', 'sqrt',
    'acos', 'atan2', 'sin', 'cos', 'min', 'max', 'lt', 'le', 'gt', 'ge', 'eq', 'ne', 'select_n', 'sign',
    'convert_element_type', 'integer_pow', 'index', 'reduce_sum', 'scatter-add',
    'concatenate', 'stack', 'matmul', 'while', 'gather', 'scatter', 'reduce', 'and', 'or', 'xor', 'not'))


@dataclass(frozen=True)
class Target:
    name: str
    cpu_ops: frozenset = CPU_OPS
    qgemm: bool = False
    # Worst-case signed int8 dot product must fit the backend's int32 output.
    qgemm_max_k: int = 131071
    libm: bool = True
    workspace_limit_bytes: int | None = None
    affine_cost_model: AffineCostModel | None = None

    def describe(self):
        result = asdict(self)
        result['cpu_ops'] = sorted(self.cpu_ops)
        return result


CPU = Target('portable-c')
KC705 = Target('kc705-cpu-tpu', qgemm=True, libm=False, affine_cost_model=AffineCostModel())
# A separate target keeps the RV32 soft-float cost estimates off Rocket's FPU.
# Approximate affine placement stays on the CPU until its transport is measured;
# exact int8 GEMM still uses the existing hardware backend.
KC705_ROCKET = Target('kc705-rocket-tpu', qgemm=True, libm=False)


def legalize(program, target, *, math_mode='libm', allow_approximation=False):
    """Verify every operation and return its target placement. Never silently fall back."""
    program.validate()
    assignments = []
    for number, n in enumerate(program.nodes):
        out = program.values[n.output]
        args = [program.values[i] for i in n.inputs]
        prefix = f'{target.name}: node {number} ({n.op}, value {n.output}, {out.dtype}{out.shape})'

        def require(condition, message):
            if not condition:
                raise ProgramError(f'{prefix}: {message}')

        device = 'cpu'
        if n.op == 'while':
            require('while' in target.cpu_ops, 'target has no runtime control-flow lowering')
            count=n.params['carry_count']
            require(count==len(n.outputs) and count<=len(args), 'invalid loop carry signature')
            cond,body=n.params['regions']
            require(len(cond.outputs)==1 and cond.values[cond.outputs[0]].dtype=='bool' and
                    cond.values[cond.outputs[0]].shape==(), 'loop condition must return a scalar bool')
            require(len(body.outputs)==count, 'loop body carry count mismatch')
            for i,vid in enumerate(n.outputs):
                result=program.values[vid];bv=body.values[body.outputs[i]]
                require((result.shape,result.dtype)==(args[i].shape,args[i].dtype)==(bv.shape,bv.dtype),
                        'loop carry type mismatch')
            for region in (cond,body):
                legalize(region,target,math_mode=math_mode,allow_approximation=allow_approximation)
        elif n.op == 'tpu_affine':
            require(target.qgemm, 'requires an int8 QGEMM backend')
            require(allow_approximation, 'fixed-point affine lowering requires allow_approximation')
            require(out.dtype == 'float32' and len(out.shape) == 2, 'invalid affine result')
            require(0 < len(args) <= target.qgemm_max_k, 'affine K exceeds backend capacity')
            require(all(a.dtype == 'float32' and a.size == out.shape[0] for a in args), 'invalid affine operands')
            require(n.params.get('digits') in (2, 3) and 0 <= n.params.get('fraction_bits', -1) <= 30,
                    'invalid fixed-point encoding')
            rows = []
            for group in n.params.get('groups', []):
                weights = np.asarray(group['weights'])
                require(weights.shape == (len(args), out.shape[1]) and
                        np.all(weights == np.rint(weights)) and np.all(abs(weights) <= 127),
                        'invalid signed int8 coefficients')
                rows.extend(group['rows'])
            require(sorted(rows) == list(range(out.shape[0])), 'affine row groups must cover each row exactly once')
            device = 'tpu'
        else:
            if n.op == 'matmul':
                require(len(args)==2 and len(args[0].shape) in (2,3) and len(args[1].shape)==len(args[0].shape),
                        'requires two rank-2 or rank-3 operands')
                require(args[0].shape[:-2]==args[1].shape[:-2] and args[0].shape[-1]==args[1].shape[-2] and
                        out.shape==(*args[0].shape[:-2],args[0].shape[-2],args[1].shape[-1]),'incompatible matrix shapes')
                integer = all(a.dtype == 'int8' for a in args) and out.dtype == 'int32'
                floating = all(a.dtype == 'float32' for a in args) and out.dtype == 'float32'
                require(integer or floating, 'supports f32×f32→f32 or i8×i8→i32')
                if integer:
                    require(args[0].shape[-1] <= target.qgemm_max_k, 'K can overflow int32 accumulation')
                    if target.qgemm:
                        device = 'tpu'
            require(device == 'tpu' or n.op in target.cpu_ops,
                    'no backend implementation or registered legalization')
            if n.op in ('gather','scatter'):
                require(len(args)==(2 if n.op=='gather' else 3), 'invalid indexing operands')
                require(args[1].dtype in ('int32','uint32','int8','uint8'), 'indices must be integers')
                require(args[0].dtype==out.dtype, 'indexing result dtype mismatch')
                if n.op=='scatter':
                    require(args[0].shape==out.shape and args[2].dtype==out.dtype,'scatter shape/type mismatch')
            if n.op=='reduce':
                require(len(args)==2 and args[1].shape==() and all(a.dtype==out.dtype for a in args),
                        'reducer requires equal element types and a scalar initializer')
                mapping=n.params['map']
                require(len(mapping)==args[0].size and all(0<=i<out.size for i in mapping),'invalid reduction map')
            if n.op in ('reduce','scatter'):
                reducer=n.params['reducer']
                require(reducer in ('add','mul','min','max','and','or','xor','set','keep'),'unsupported reducer')
                if reducer in ('and','or','xor'):require(out.dtype!='float32','bitwise reducer requires integer or boolean type')
            if n.op in ('sqrt', 'acos', 'atan2', 'sin', 'cos'):
                require(len(args) == (2 if n.op == 'atan2' else 1) and all(a.dtype == out.dtype == 'float32' for a in args), 'requires float32')
                require(math_mode != 'libm' or target.libm, 'target has no libm; explicitly select freestanding math')
                require(math_mode != 'freestanding' or allow_approximation,
                        'freestanding math requires allow_approximation')
            binary = ('add', 'add_any', 'sub', 'mul', 'div', 'atan2', 'min', 'max', 'lt', 'le', 'gt', 'ge', 'eq', 'ne','and','or','xor')
            unary = ('neg', 'abs', 'sqrt', 'acos', 'sin', 'cos', 'sign', 'convert_element_type', 'integer_pow','not')
            if n.op in binary + unary + ('select_n',):
                require(len(args) == (2 if n.op in binary else 3 if n.op == 'select_n' else 1), 'wrong operand count')
                require(np.broadcast_shapes(*(a.shape for a in args)) == out.shape, 'invalid elementwise broadcast')
                if n.op in ('lt', 'le', 'gt', 'ge', 'eq', 'ne'):
                    require(out.dtype == 'bool' and args[0].dtype == args[1].dtype, 'invalid comparison types')
                elif n.op == 'select_n':
                    require(args[0].dtype in ('bool', 'int32') and args[1].dtype == args[2].dtype == out.dtype,
                            'select requires a predicate and two equal-typed alternatives')
                elif n.op != 'convert_element_type':
                    require(all(a.dtype == out.dtype for a in args), 'operand/result dtype mismatch')
                    require(out.dtype != 'bool' or n.op in ('and','or','xor','not'), 'boolean arithmetic has no lowering')
                if n.op in ('and','or','xor','not'):require(out.dtype!='float32','bitwise operation requires integer/boolean type')
                if n.op == 'div':
                    require(out.dtype == 'float32', 'integer division semantics have no lowering')
                if n.op == 'integer_pow':
                    require(n.params.get('exponent') == 2, 'only exponent 2 is currently legalized')
            if n.op in ('index', 'reduce_sum', 'scatter-add'):
                require(len(args) == (2 if n.op == 'scatter-add' else 1), 'wrong operand count')
                require(all(a.dtype == out.dtype for a in args), 'index/reduction dtype mismatch')
                mapping = n.params.get('map', [])
                count = out.size if n.op == 'index' else args[-1].size
                limit = args[0].size if n.op == 'index' else out.size
                minimum = -1 if n.op == 'scatter-add' else 0
                require(len(mapping) == count and all(isinstance(i, int) and minimum <= i < limit for i in mapping),
                        'invalid static index map')
                if n.op == 'scatter-add':
                    require(args[0].shape == out.shape, 'scatter result must match base shape')
                if n.op != 'index':
                    require(out.dtype != 'bool', 'boolean reduction has no lowering')
            if n.op in ('concatenate', 'stack'):
                require(bool(args) and all(a.dtype == out.dtype for a in args), 'incompatible concatenation types')
                try:
                    expected = (np.concatenate if n.op == 'concatenate' else np.stack)(
                        [np.empty(a.shape, dtype=np.uint8) for a in args], axis=n.params['axis']).shape
                except (ValueError, KeyError) as exc:
                    raise ProgramError(f'{prefix}: invalid concatenation shape/axis') from exc
                require(expected == out.shape, 'concatenation result shape mismatch')
        assignments.append({'node': number, 'value': n.output, 'op': n.op, 'device': device})
    return assignments
