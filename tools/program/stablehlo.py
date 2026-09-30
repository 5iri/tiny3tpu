"""Lower verified StableHLO MLIR to a private buffer schedule and target code.

Uses MLIR's parser/verifier and StableHLO's reference interpreter for constant
evaluation. No Jaxpr, source function, or workload-specific pattern is consumed.
"""
from pathlib import Path
import collections
import numpy as np
from ._schedule import ExecutionPlan, Node, ProgramError
from .compiler import _compile_schedule


def _bindings():
    try:
        from jaxlib.mlir import ir
        from jaxlib.mlir.dialects import stablehlo, func
        import jaxlib.mlir._mlir_libs._jax_mlir_ext as registration
    except ImportError as exc:
        raise ProgramError('StableHLO compiler requires the tested jaxlib MLIR bindings (see docs_stablehlo.md)') from exc
    registry = ir.DialectRegistry()
    registration.register_dialects(registry)
    context = ir.Context()
    context.append_dialect_registry(registry)
    context.load_all_available_dialects()
    stablehlo.register_dialect(context)
    return ir, stablehlo, func, context


class Lowering:
    def __init__(self, module, ir, hlo, func):
        self.ir, self.hlo, self.func = ir, hlo, func
        self.plan = ExecutionPlan()
        self.functions = {}
        self.calls = []
        self.source_ops = collections.Counter()
        for item in module.body.operations:
            op = item.operation
            if op.name != 'func.func':
                self.fail(op, 'only func.func definitions are supported at module scope')
            self.functions[ir.StringAttr(op.attributes['sym_name']).value] = op

    def fail(self, op, message):
        raise ProgramError(f'{op.name} at {op.location}: {message}')

    def spec(self, typ):
        try:
            tensor = self.ir.RankedTensorType(typ)
        except ValueError as exc:
            raise ProgramError(f'backend requires ranked tensors, got {typ}') from exc
        shape = tuple(tensor.shape)
        element = str(tensor.element_type)
        types = {'f32': 'float32', 'i32': 'int32', 'ui32': 'uint32',
                 'i8': 'int8', 'ui8': 'uint8', 'i1': 'bool'}
        if element not in types or any(d <= 0 for d in shape):
            raise ProgramError(f'backend has no storage lowering for {typ}; requires positive static shapes and supported element types')
        return shape, types[element]

    def ints(self, attr):
        return [int(x) for x in attr]

    def evaluate(self, op, arrays, index_result=False):
        """Run a pure constant expression using StableHLO's own semantics."""
        ir = self.ir
        types = [r.type for r in op.results]
        if index_result:
            types = [ir.RankedTensorType.get(self.spec(types[0])[0], ir.IntegerType.get_signless(32))]
        with ir.Location.unknown():
            module = ir.Module.create()
            with ir.InsertionPoint(module.body):
                function = self.func.FuncOp('main', ([], types))
                block = function.add_entry_block()
            with ir.InsertionPoint(block):
                operands = []
                for original, array in zip(op.operands, arrays):
                    # Explicit types preserve signedness; bindings pack numpy bools.
                    typ = original.type
                    if index_result and not operands:
                        typ = ir.RankedTensorType.get(array.shape, ir.IntegerType.get_signless(32))
                    data = np.asarray(array)
                    try:
                        attr = ir.DenseElementsAttr.get(np.ascontiguousarray(data), type=typ)
                    except Exception as exc:
                        self.fail(op, f'cannot materialize constant {array.dtype}{array.shape} as {typ}: {exc}')
                    operands.append(self.hlo.ConstantOp(attr).result)
                clone = op.clone()
                for i, value in enumerate(operands):
                    clone.operands[i] = value
                for result, typ in zip(clone.results, types):
                    result.set_type(typ)
                self.func.ReturnOp(list(clone.results))
            if not module.operation.verify():
                self.fail(op, 'constant evaluation module failed verification')
            return [np.asarray(a).reshape(self.spec(t)[0]).astype(self.spec(t)[1])
                    for a, t in zip(self.hlo.eval_module(module, []), types)]

    def function(self, name, args):
        if name not in self.functions:
            raise ProgramError(f'missing function definition @{name}')
        if name in self.calls or len(self.calls) >= 64:
            raise ProgramError(f'recursive/deep call to @{name} has no backend lowering')
        op = self.functions[name]
        if len(op.regions[0].blocks) != 1:
            self.fail(op, 'function requires a single entry block')
        self.calls.append(name)
        result = self.block(op.regions[0].blocks[0], args, {})
        self.calls.pop()
        return result

    def block(self, block, args, outer):
        env = dict(outer)
        if len(args) != len(block.arguments):
            raise ProgramError('block argument count mismatch')
        env.update(zip(block.arguments, args))
        p = self.plan
        for item in block.operations:
            op = item.operation
            name = op.name
            self.source_ops[name] += 1
            ins = [env[v] for v in op.operands]
            values = [p.values[i] for i in ins]
            if name in ('func.return', 'stablehlo.return'):
                return ins
            if name == 'func.call':
                outs = self.function(self.ir.FlatSymbolRefAttr(op.attributes['callee']).value, ins)
            elif name == 'stablehlo.composite':
                # Use the supplied decomposition, never infer semantics from a name.
                outs = self.function(self.ir.FlatSymbolRefAttr(op.attributes['decomposition']).value, ins)
            elif name == 'stablehlo.while':
                carry = ins
                unroll_limit=16
                for iteration in range(unroll_limit+1):
                    cond = self.block(op.regions[0].blocks[0], carry, env)
                    predicate = p.values[cond[0]].data
                    if predicate is not None and not bool(predicate):
                        break
                    if predicate is None or iteration == unroll_limit:
                        carry = self.runtime_while(op, carry, env)
                        break
                    carry = self.block(op.regions[1].blocks[0], carry, env)
                if predicate is not None and not bool(predicate):
                    p.inlined_loops += 1
                outs = carry
            elif name == 'stablehlo.constant':
                shape, dtype = self.spec(op.results[0].type)
                data = np.asarray(self.ir.DenseElementsAttr(op.attributes['value'])).reshape(shape)
                outs = [p.value(shape, dtype, data)]
            else:
                if len(op.results) != 1:
                    self.fail(op, 'multi-result operation has no backend lowering')
                shape, dtype = self.spec(op.results[0].type)
                # Validate operation semantics even when operands happen to be constant.
                opcode, inputs, params = self.operation(op, ins, shape, dtype)
                if all(v.data is not None for v in values):
                    result = self.evaluate(op, [v.data for v in values])[0]
                    outs = [p.value(shape, dtype, result)]
                    p.folded += 1
                else:
                    out = p.value(shape, dtype)
                    params['source'] = {'op': name, 'location': str(op.location)}
                    p.nodes.append(Node(opcode, inputs, out, params))
                    outs = [out]
            if len(outs) != len(op.results):
                self.fail(op, 'lowered result count mismatch')
            env.update(zip(op.results, outs))
        raise ProgramError('block has no return terminator')

    def runtime_while(self, op, carry, env):
        """Outline condition/body into reusable CPU functions with explicit captures."""
        outer = self.plan
        defined = set()
        used = []
        def walk(region):
            for block in region.blocks:
                defined.update(block.arguments)
                for child in block.operations:
                    defined.update(child.operation.results)
                    used.extend(child.operation.operands)
                    for nested in child.operation.regions:
                        walk(nested)
        for region in op.regions:
            walk(region)
        captures = list(dict.fromkeys(v for v in used if v not in defined))
        capture_ids = [env[v] for v in captures]
        body_block = op.regions[1].blocks[0]
        terminator = list(body_block.operations)[-1].operation
        invariant = [v == a and outer.values[i].data is not None
                     for v, a, i in zip(terminator.operands, body_block.arguments, carry)]
        regions = []
        bindings = []
        try:
            for region in op.regions:
                child = ExecutionPlan()
                self.plan = child
                args = []
                mapping = {}
                slots = []
                for slot, oid in enumerate(carry + capture_ids):
                    value = outer.values[oid]
                    constant = (invariant[slot] if slot < len(carry) else value.data is not None)
                    vid = child.value(value.shape, value.dtype, value.data if constant else None)
                    if not constant:
                        child.inputs.append(vid)
                        slots.append(slot)
                    if slot < len(carry):args.append(vid)
                    else:mapping[captures[slot-len(carry)]] = vid
                child.outputs = self.block(region.blocks[0], args, mapping)
                child.validate();child.dce()
                regions.append(child)
                bindings.append(slots)
        finally:
            self.plan = outer
        outs = [outer.value(*self.spec(v.type)) for v in op.results]
        outer.nodes.append(Node('while', carry+capture_ids, outs[0], {
            'regions': regions, 'bindings': bindings, 'carry_count': len(carry),
            'source': {'op': op.name, 'location': str(op.location)}}, outs[1:]))
        return outs

    def reducer(self, op):
        block = op.regions[0].blocks[0]
        ops = [o.operation for o in block.operations]
        if len(block.arguments)!=2:return None
        if len(ops)==1 and ops[0].name=='stablehlo.return':
            if list(ops[0].operands)==[block.arguments[1]]:return 'set'
            if list(ops[0].operands)==[block.arguments[0]]:return 'keep'
        reducers={'stablehlo.add':'add','stablehlo.multiply':'mul','stablehlo.maximum':'max',
                  'stablehlo.minimum':'min','stablehlo.and':'and','stablehlo.or':'or','stablehlo.xor':'xor'}
        if (len(ops)==2 and ops[0].name in reducers and
            set(ops[0].operands)==set(block.arguments) and ops[1].name=='stablehlo.return' and
            list(ops[1].operands)==list(ops[0].results)):
            return reducers[ops[0].name]
        return None

    def operation(self, op, ins, shape, dtype):
        p = self.plan
        values = [p.values[i] for i in ins]
        attrs = op.attributes
        name = op.name.removeprefix('stablehlo.')
        simple = {'add': 'add', 'subtract': 'sub', 'multiply': 'mul', 'divide': 'div',
                  'negate': 'neg', 'abs': 'abs', 'sqrt': 'sqrt', 'atan2': 'atan2',
                  'minimum': 'min', 'maximum': 'max', 'sign': 'sign', 'convert': 'convert_element_type',
                  'sine':'sin','cosine':'cos','exponential':'exp','and':'and','or':'or','xor':'xor','not':'not'}
        if op.name.startswith('stablehlo.') and name in simple:
            return simple[name], ins, {}
        if name=='iota':
            # With static result dimensions this has no runtime operands.
            return 'iota',ins,{}
        if name == 'compare':
            direction = self.hlo.ComparisonDirectionAttr(attrs['comparison_direction']).value.lower()
            mode = self.hlo.ComparisonTypeAttr(attrs['compare_type']).value
            expected = 'FLOAT' if values[0].dtype == 'float32' else 'UNSIGNED' if values[0].dtype.startswith('uint') else 'SIGNED'
            if mode != expected:
                self.fail(op, f'comparison mode {mode} is not supported for {values[0].dtype}')
            return direction, ins, {}
        if name == 'select':
            return 'select_n', [ins[0], ins[2], ins[1]], {}
        if name=='gather' and values[1].data is None:
            dn=self.hlo.GatherDimensionNumbers(attrs['dimension_numbers'])
            return 'gather',ins,{
                field:list(getattr(dn,field)) for field in ('offset_dims','collapsed_slice_dims',
                    'operand_batching_dims','start_indices_batching_dims','start_index_map')
            }|{'index_vector_dim':dn.index_vector_dim,'slice_sizes':self.ints(attrs['slice_sizes'])}
        if name in ('reshape', 'slice', 'transpose', 'broadcast_in_dim', 'gather'):
            source = np.arange(values[0].size, dtype=np.int32).reshape(values[0].shape)
            mapping = self.evaluate(op, [source] + [v.data for v in values[1:]], index_result=True)[0]
            return 'index', ins[:1], {'map': mapping.ravel().tolist()}
        if name == 'concatenate':
            return name, ins, {'axis': self.ir.IntegerAttr(attrs['dimension']).value}
        if name == 'reduce':
            reducer=self.reducer(op)
            if len(ins)!=2 or reducer not in ('add','mul','min','max','and','or','xor'):
                self.fail(op,'reduction requires a single supported associative reducer')
            axes = self.ints(attrs['dimensions'])
            mapping = []
            for index in np.ndindex(values[0].shape):
                kept = tuple(v for a, v in enumerate(index) if a not in axes)
                mapping.append(int(np.ravel_multi_index(kept, shape)) if shape else 0)
            return 'reduce', ins, {'map': mapping,'reducer':reducer}
        if name == 'scatter':
            dn = self.hlo.ScatterDimensionNumbers(attrs['scatter_dimension_numbers'])
            reducer=self.reducer(op)
            if len(ins)!=3 or reducer is None:
                self.fail(op,'scatter requires a single supported update function')
            idx=values[1].data
            # Preserve the compact precomputed address path for static row updates.
            # Runtime/general indices use the dimensional address generator below.
            if (reducer=='add' and idx is not None and idx.ndim==2 and idx.shape[1]==1 and
                list(dn.scattered_dims_to_operand_dims)==[0] and list(dn.inserted_window_dims)==[0] and
                list(dn.update_window_dims)==list(range(1,len(values[2].shape))) and
                dn.index_vector_dim==1 and not list(dn.input_batching_dims) and
                not list(dn.scatter_indices_batching_dims)):
                width=int(np.prod(values[0].shape[1:]))
                mapping=[int(i)*width+c if 0<=i<values[0].shape[0] else -1 for i in idx.ravel() for c in range(width)]
                return 'scatter-add',[ins[0],ins[2]],{'map':mapping}
            return 'scatter',ins,{
                field:list(getattr(dn,field)) for field in ('update_window_dims','inserted_window_dims',
                    'input_batching_dims','scatter_indices_batching_dims','scattered_dims_to_operand_dims')
            }|{'index_vector_dim':dn.index_vector_dim,'reducer':reducer}
        if name == 'dot_general':
            dn = self.hlo.DotDimensionNumbers(attrs['dot_dimension_numbers'])
            if 'algorithm' in attrs:
                self.fail(op, 'explicit dot algorithm has no backend lowering')
            if 'precision_config' in attrs and any(self.hlo.PrecisionAttr(a).value != 'DEFAULT' for a in attrs['precision_config']):
                self.fail(op, 'non-default dot precision has no backend lowering')
            lb=list(dn.lhs_batching_dimensions);rb=list(dn.rhs_batching_dimensions)
            lc=list(dn.lhs_contracting_dimensions);rc=list(dn.rhs_contracting_dimensions)
            lf=[d for d in range(len(values[0].shape)) if d not in lb+lc]
            rf=[d for d in range(len(values[1].shape)) if d not in rb+rc]
            def extent(value,axes):return int(np.prod([value.shape[d] for d in axes]))
            batch=extent(values[0],lb);m=extent(values[0],lf);k=extent(values[0],lc);cols=extent(values[1],rf)
            matrix_inputs=[]
            for value,perm,dimensions in ((values[0],lb+lf+lc,(m,k)),(values[1],rb+rc+rf,(k,cols))):
                newshape=(batch,*dimensions) if lb else dimensions
                mapping=np.arange(value.size).reshape(value.shape).transpose(perm).ravel().tolist()
                if value.data is not None:
                    matrix_inputs.append(p.value(newshape,value.dtype,value.data.transpose(perm).reshape(newshape)))
                else:matrix_inputs.append(p.operation('index',[value.id],newshape,value.dtype,map=mapping))
            result_shape=(batch,m,cols) if lb else (m,cols)
            result=p.operation('matmul',matrix_inputs,result_shape,dtype,
                               source={'op':op.name,'location':str(op.location)})
            return 'index',[result],{'map':list(range(int(np.prod(shape))))}
        self.fail(op, 'no backend legalization registered')


def compile_stablehlo(source, output, options=None, *, entry='main'):
    """Compile MLIR text or a StableHLO portable artifact (bytes or Path).

    The source artifact is the public compiler contract. The returned report
    describes lowered operations, memory, precision policy and CPU/TPU placement.
    """
    if isinstance(source, Path):
        source = source.read_bytes()
    ir, hlo, func, context = _bindings()
    try:
        with context, ir.Location.unknown():
            if isinstance(source, bytes) and source.startswith(b'ML\xefR'):
                module = hlo.deserialize_portable_artifact(context, source)
            else:
                module = ir.Module.parse(source.decode() if isinstance(source, bytes) else source)
            module.operation.verify()
            for key in ('mhlo.num_partitions', 'mhlo.num_replicas'):
                if key in module.operation.attributes and ir.IntegerAttr(module.operation.attributes[key]).value != 1:
                    raise ProgramError(f'{key}: distributed execution is not supported by this backend')
            lowering = Lowering(module, ir, hlo, func)
            if entry not in lowering.functions:
                raise ProgramError(f'entry function @{entry} not found')
            function = lowering.functions[entry]
            p = lowering.plan
            p.inputs = [p.value(*lowering.spec(a.type)) for a in function.regions[0].blocks[0].arguments]
            p.outputs = lowering.function(entry, p.inputs)
            p.validate()
            report = _compile_schedule(p, output, options)
            report['input_format'] = 'StableHLO'
            report['entry'] = entry
            report['source_operations'] = dict(lowering.source_ops)
            return report
    except ProgramError:
        raise
    except Exception as exc:
        raise ProgramError(f'StableHLO parsing/lowering failed: {exc}') from exc
