"""Lower tinygrad Tensor / OnnxRunner graphs to the tiny3tpu ExecutionPlan and C/TPU code.

Consumes tinygrad's lazy UOp DAG directly, mapping movement ops to static index
views, recognizing both MatMul and Conv2D (im2col) contractions as hardware TPU
matmul nodes, and compiling through the shared tiny3tpu middle-end and C backend.
"""
from pathlib import Path
import collections
import math
import numpy as np

from ._schedule import ExecutionPlan, Node, ProgramError
from .compiler import CompileOptions, _compile_schedule


def _import_tinygrad():
    try:
        import tinygrad
        from tinygrad import Tensor, dtypes
        from tinygrad.uop.ops import Ops
        from tinygrad.nn.onnx import OnnxRunner
    except ImportError as exc:
        raise ProgramError('tinygrad frontend requires tinygrad with the UOp and ONNX APIs used by this frontend') from exc
    return tinygrad, Tensor, dtypes, Ops, OnnxRunner


_DTYPE_MAP = {
    'float': 'float32',
    'float32': 'float32',
    'int': 'int32',
    'int32': 'int32',
    'long': 'int32',
    'int64': 'int32',
    'short': 'int32',
    'int16': 'int32',
    'uint': 'uint32',
    'uint32': 'uint32',
    'ulong': 'uint32',
    'uint64': 'uint32',
    'ushort': 'uint32',
    'uint16': 'uint32',
    'char': 'int8',
    'int8': 'int8',
    'signed char': 'int8',
    'uchar': 'uint8',
    'uint8': 'uint8',
    'unsigned char': 'uint8',
    'bool': 'bool',
    '_bool': 'bool',
}


def _map_dtype(tg_dtype):
    name = getattr(tg_dtype, 'name', str(tg_dtype)).removeprefix('dtypes.')
    if name not in _DTYPE_MAP:
        raise ProgramError(f'unsupported tinygrad dtype {tg_dtype}')
    return _DTYPE_MAP[name]


def _vec_arg(u, rank):
    if u.op.name == 'VCONST':
        return tuple(int(x) for x in u.arg)
    if u.op.name == 'CONST':
        return (int(u.arg),) * rank
    raise ProgramError(f'expected constant shape/bounds vector, got {u.op}')


def _slice_permute_map(in_shape, drop_axes, perm, out_shape):
    """Build flat index map that slices `drop_axes` at 0 and permutes remaining axes by `perm`."""
    idx = np.arange(int(np.prod(in_shape)), dtype=np.int32).reshape(in_shape)
    slicer = tuple(0 if d in drop_axes else slice(None) for d in range(len(in_shape)))
    sliced = np.asarray(idx[slicer], dtype=np.int32)
    if perm:
        sliced = sliced.transpose(perm)
    return sliced.reshape(out_shape).ravel().tolist()


class TinygradLowering:
    def __init__(self, Tensor, dtypes, Ops):
        self.Tensor = Tensor
        self.dtypes = dtypes
        self.Ops = Ops
        self.plan = ExecutionPlan()
        self.env = {}
        self.int8_carrier = {}
        self.bcast_axes = {}
        self.dynamic = set()
        self.source_ops = collections.Counter()

    def _emit_index(self, src_vid, shape, dtype, mapping, op_name='index'):
        p = self.plan
        src_val = p.values[src_vid]
        if src_val.data is not None:
            arr = src_val.data.ravel()[np.asarray(mapping, dtype=np.int64)].reshape(shape)
            p.folded += 1
            return p.value(shape, dtype, arr)
        return p.operation('index', [src_vid], shape, dtype, map=mapping,
                           source={'op': f'tinygrad.{op_name}', 'location': 'uop'})

    def _emit_pad(self, src_vid, in_shape, out_shape, begins, dtype):
        p = self.plan
        src_val = p.values[src_vid]
        if src_val.data is not None:
            out = np.zeros(out_shape, dtype=dtype)
            slices = tuple(slice(b, b + s) for b, s in zip(begins, in_shape))
            out[slices] = src_val.data.reshape(in_shape)
            p.folded += 1
            return p.value(out_shape, dtype, out)
        grid = np.indices(in_shape)
        padded_coords = [grid[d] + int(begins[d]) for d in range(len(in_shape))]
        # Handle negative padding (crop) if any coordinate falls outside out_shape
        valid = np.ones(in_shape, dtype=bool)
        clamped = []
        for d, coord in enumerate(padded_coords):
            valid &= (coord >= 0) & (coord < out_shape[d])
            clamped.append(np.clip(coord, 0, max(0, out_shape[d] - 1)))
        flat = np.ravel_multi_index(clamped, out_shape)
        scatter_map = np.where(valid, flat, -1).ravel().tolist()
        zero = p.value(out_shape, dtype, np.zeros(out_shape, dtype))
        return p.operation('scatter-add', [zero, src_vid], out_shape, dtype, map=scatter_map,
                           source={'op': 'tinygrad.PAD', 'location': 'uop'})

    def _get_int8_carrier(self, u):
        if u in self.int8_carrier:
            return self.int8_carrier[u]
        if u in self.env:
            v = self.plan.values[self.env[u]]
            if v.dtype == 'int8':
                self.int8_carrier[u] = v.id
                return v.id
            if v.data is not None and v.dtype in ('int32', 'uint8', 'float32'):
                arr = np.asarray(v.data)
                if np.all(arr == np.rint(arr)) and np.all(arr >= -128) and np.all(arr <= 127):
                    cid = self.plan.value(v.shape, 'int8', arr.astype(np.int8))
                    self.int8_carrier[u] = cid
                    return cid
        return None

    def _try_lower_contraction(self, u, out_shape, out_dtype):
        """Recognize MatMul, Batched MatMul, and Conv2D (im2col) from REDUCE_AXIS(ADD, MUL)."""
        Ops = self.Ops
        reduce_op, reduce_axes = u.arg
        if reduce_op is not Ops.ADD or not reduce_axes:
            return None
        mul_u = u.src[0]
        if mul_u.op is Ops.CAST and mul_u.src[0].op is Ops.MUL:
            mul_u = mul_u.src[0]
        if mul_u.op is not Ops.MUL:
            return None

        op0, op1 = mul_u.src
        mul_shape = tuple(int(d) for d in mul_u._shape)
        rank = len(mul_shape)
        reduce_axes = tuple(sorted(int(a) for a in reduce_axes))
        reduce_set = set(reduce_axes)

        b0 = self.bcast_axes.get(op0, set())
        b1 = self.bcast_axes.get(op1, set())
        # Neither operand should be broadcast along a non-trivial reduction axis
        if any(mul_shape[d] > 1 and (d in b0 or d in b1) for d in reduce_axes):
            return None

        # Determine whether this is an int8 -> int32 TPU contraction or float32 contraction
        c0 = self._get_int8_carrier(op0) if out_dtype == 'int32' else None
        c1 = self._get_int8_carrier(op1) if out_dtype == 'int32' else None
        if out_dtype == 'int32' and c0 is not None and c1 is not None:
            vid0, vid1, mat_dtype = c0, c1, 'int8'
        elif out_dtype == 'float32' and self.plan.values[self.env[op0]].dtype == 'float32' and self.plan.values[self.env[op1]].dtype == 'float32':
            vid0, vid1, mat_dtype = self.env[op0], self.env[op1], 'float32'
        else:
            return None

        free0, free1, batch_axes = [], [], []
        for d in range(rank):
            if d in reduce_set:
                continue
            if mul_shape[d] == 1:
                batch_axes.append(d)
            elif d in b1 and d not in b0:
                free0.append(d)
            elif d in b0 and d not in b1:
                free1.append(d)
            elif d not in b0 and d not in b1:
                batch_axes.append(d)
            else:
                batch_axes.append(d)

        # Order M_axes and N_axes so that if both are non-empty, M_axes comes first in output axis order.
        # For Conv2D (B, G, Cout, H_out, W_out, Cin, KH, KW), op1 (weights) has Cout (axis 2)
        # and op0 (im2col activations) has (H_out, W_out) (axes 3, 4). Putting weights as LHS (Cout, K)
        # and activations as RHS (K, H_out*W_out) yields (Cout, H_out*W_out) directly in NCHW layout!
        if free0 and free1 and min(free1) < min(free0):
            vid0, vid1 = vid1, vid0
            free0, free1 = free1, free0

        batch = int(np.prod([mul_shape[d] for d in batch_axes])) if batch_axes else 1
        m = int(np.prod([mul_shape[d] for d in free0])) if free0 else 1
        n = int(np.prod([mul_shape[d] for d in free1])) if free1 else 1
        k = int(np.prod([mul_shape[d] for d in reduce_axes]))

        has_batch = batch > 1
        active_batch = [d for d in batch_axes if mul_shape[d] > 1] if has_batch else []
        drop_batch = [d for d in batch_axes if mul_shape[d] == 1]

        # Build LHS of shape (batch, m, k) or (m, k) by slicing free1 + drop_batch at 0
        lhs_drop = set(free1) | set(drop_batch)
        lhs_kept = [d for d in range(rank) if d not in lhs_drop]
        lhs_order = active_batch + free0 + list(reduce_axes)
        lhs_perm = [lhs_kept.index(d) for d in lhs_order]
        lhs_shape = (batch, m, k) if has_batch else (m, k)
        lhs_map = _slice_permute_map(mul_shape, lhs_drop, lhs_perm, lhs_shape)
        lhs_mat = self._emit_index(vid0, lhs_shape, mat_dtype, lhs_map, 'matmul_lhs')

        # Build RHS of shape (batch, k, n) or (k, n) by slicing free0 + drop_batch at 0
        rhs_drop = set(free0) | set(drop_batch)
        rhs_kept = [d for d in range(rank) if d not in rhs_drop]
        rhs_order = active_batch + list(reduce_axes) + free1
        rhs_perm = [rhs_kept.index(d) for d in rhs_order]
        rhs_shape = (batch, k, n) if has_batch else (k, n)
        rhs_map = _slice_permute_map(mul_shape, rhs_drop, rhs_perm, rhs_shape)
        rhs_mat = self._emit_index(vid1, rhs_shape, mat_dtype, rhs_map, 'matmul_rhs')

        mm_shape = (batch, m, n) if has_batch else (m, n)
        mm_vid = self.plan.operation('matmul', [lhs_mat, rhs_mat], mm_shape, out_dtype,
                                     source={'op': 'tinygrad.matmul', 'location': 'uop'})

        # Map mm_vid (active_batch + free0 + free1) to out_shape
        mm_axes_order = active_batch + free0 + free1
        non_reduced = [d for d in range(rank) if d not in reduce_set and mul_shape[d] > 1]
        if mm_axes_order == non_reduced:
            out_map = list(range(int(np.prod(out_shape))))
        else:
            inter_shape = tuple(mul_shape[d] for d in mm_axes_order)
            inv_perm = [mm_axes_order.index(d) for d in non_reduced]
            out_map = np.arange(int(np.prod(out_shape)), dtype=np.int32).reshape(inter_shape).transpose(inv_perm).ravel().tolist()
        return self._emit_index(mm_vid, out_shape, out_dtype, out_map, 'matmul_out')

    def lower(self, output_uops, input_tensors):
        Ops = self.Ops
        p = self.plan

        # Register runtime inputs
        for t in input_tensors:
            shape = tuple(int(d) for d in t.shape)
            dtype = _map_dtype(t.dtype)
            vid = p.value(shape, dtype)
            p.inputs.append(vid)
            u = t.uop
            self.env[u] = vid
            self.bcast_axes[u] = set()
            self.dynamic.add(u)
            if dtype == 'int8':
                self.int8_carrier[u] = vid
            if u.base is not u and u.base not in self.env:
                base_shape = tuple(int(d) for d in u.base._shape)
                base_vid = self._emit_index(vid, base_shape, dtype, list(range(int(np.prod(shape)))), 'input_base')
                self.env[u.base] = base_vid
                self.bcast_axes[u.base] = set()
                self.dynamic.add(u.base)
                if dtype == 'int8':
                    self.int8_carrier[u.base] = base_vid

        sink = Ops.SINK if hasattr(Ops, 'SINK') else None
        all_nodes = []
        seen = set()
        for out_u in output_uops:
            for node in out_u.toposort():
                if node not in seen:
                    seen.add(node)
                    all_nodes.append(node)

        # Propagate dynamic taint
        for u in all_nodes:
            if u in self.dynamic or any(s in self.dynamic for s in u.src):
                self.dynamic.add(u)

        movement_ops = {Ops.RESHAPE, Ops.PERMUTE, Ops.EXPAND, Ops.SHRINK, Ops.FLIP, Ops.PAD, Ops.DETACH, Ops.CONTIGUOUS}

        for u in all_nodes:
            if u in self.env:
                continue
            if u.op in (Ops.DEVICE, Ops.UNIQUE, Ops.LUNIQUE, Ops.NOOP):
                continue
            if u._shape is None:
                continue
            if getattr(u.dtype, 'count', 1) > 1 or 'weakint' in str(u.dtype):
                # Shape / bound helper vector for movement ops
                continue

            shape = tuple(int(d) for d in u._shape)
            dtype = _map_dtype(u.dtype)
            self.source_ops[f'tinygrad.{u.op.name}'] += 1

            # Constant folding for non-dynamic base/compute UOps (keep movement/cast ops structured
            # so constant weight tensors stay compact and preserve broadcast metadata for matmul/conv2d)
            if u not in self.dynamic and (u.op not in movement_ops and u.op is not Ops.CAST or not u.src or u.src[0] not in self.env):
                if u.op is Ops.CONST:
                    arr = np.full(shape, u.arg, dtype=dtype)
                else:
                    arr = np.asarray(self.Tensor(u).numpy(), dtype=dtype).reshape(shape)
                vid = p.value(shape, dtype, arr)
                self.env[u] = vid
                self.bcast_axes[u] = set()
                if dtype == 'int8':
                    self.int8_carrier[u] = vid
                continue

            if u.op in (Ops.DETACH, Ops.CONTIGUOUS):
                src = u.src[0]
                self.env[u] = self.env[src]
                self.bcast_axes[u] = set(self.bcast_axes.get(src, set()))
                if src in self.int8_carrier:
                    self.int8_carrier[u] = self.int8_carrier[src]
                continue

            if u.op is Ops.RESHAPE:
                src = u.src[0]
                in_shape = tuple(int(d) for d in src._shape)
                mapping = list(range(int(np.prod(shape))))
                self.env[u] = self._emit_index(self.env[src], shape, dtype, mapping, 'RESHAPE')
                # Preserve broadcast axes across pure size-1 insertions/removals where possible
                src_bcast = self.bcast_axes.get(src, set())
                if not src_bcast:
                    self.bcast_axes[u] = set()
                else:
                    self.bcast_axes[u] = set()
                c_src = self._get_int8_carrier(src)
                if c_src is not None:
                    self.int8_carrier[u] = self._emit_index(c_src, shape, 'int8', mapping, 'RESHAPE_i8')
                continue

            if u.op is Ops.PERMUTE:
                src = u.src[0]
                in_shape = tuple(int(d) for d in src._shape)
                perm = tuple(int(x) for x in u.arg)
                mapping = np.arange(int(np.prod(in_shape)), dtype=np.int32).reshape(in_shape).transpose(perm).ravel().tolist()
                self.env[u] = self._emit_index(self.env[src], shape, dtype, mapping, 'PERMUTE')
                parent_bcast = self.bcast_axes.get(src, set())
                self.bcast_axes[u] = {d for d, ax in enumerate(perm) if ax in parent_bcast}
                c_src = self._get_int8_carrier(src)
                if c_src is not None:
                    self.int8_carrier[u] = self._emit_index(c_src, shape, 'int8', mapping, 'PERMUTE_i8')
                continue

            if u.op is Ops.EXPAND:
                src = u.src[0]
                in_shape = tuple(int(d) for d in src._shape)
                mapping = np.broadcast_to(np.arange(int(np.prod(in_shape)), dtype=np.int32).reshape(in_shape), shape).ravel().tolist()
                self.env[u] = self._emit_index(self.env[src], shape, dtype, mapping, 'EXPAND')
                new_bcast = {d for d, (si, so) in enumerate(zip(in_shape, shape)) if si == 1 and so > 1}
                self.bcast_axes[u] = set(self.bcast_axes.get(src, set())) | new_bcast
                c_src = self._get_int8_carrier(src)
                if c_src is not None:
                    self.int8_carrier[u] = self._emit_index(c_src, shape, 'int8', mapping, 'EXPAND_i8')
                continue

            if u.op is Ops.SHRINK:
                src = u.src[0]
                in_shape = tuple(int(d) for d in src._shape)
                begins = _vec_arg(u.src[1], len(in_shape))
                ends = _vec_arg(u.src[2], len(in_shape))
                slices = tuple(slice(b, e) for b, e in zip(begins, ends))
                mapping = np.arange(int(np.prod(in_shape)), dtype=np.int32).reshape(in_shape)[slices].ravel().tolist()
                self.env[u] = self._emit_index(self.env[src], shape, dtype, mapping, 'SHRINK')
                self.bcast_axes[u] = set(self.bcast_axes.get(src, set()))
                c_src = self._get_int8_carrier(src)
                if c_src is not None:
                    self.int8_carrier[u] = self._emit_index(c_src, shape, 'int8', mapping, 'SHRINK_i8')
                continue

            if u.op is Ops.FLIP:
                src = u.src[0]
                in_shape = tuple(int(d) for d in src._shape)
                axes = tuple(i for i, flag in enumerate(u.arg) if flag)
                mapping = np.flip(np.arange(int(np.prod(in_shape)), dtype=np.int32).reshape(in_shape), axis=axes).ravel().tolist()
                self.env[u] = self._emit_index(self.env[src], shape, dtype, mapping, 'FLIP')
                self.bcast_axes[u] = set(self.bcast_axes.get(src, set()))
                c_src = self._get_int8_carrier(src)
                if c_src is not None:
                    self.int8_carrier[u] = self._emit_index(c_src, shape, 'int8', mapping, 'FLIP_i8')
                continue

            if u.op is Ops.PAD:
                src = u.src[0]
                in_shape = tuple(int(d) for d in src._shape)
                begins = _vec_arg(u.src[1], len(in_shape))
                self.env[u] = self._emit_pad(self.env[src], in_shape, shape, begins, dtype)
                self.bcast_axes[u] = set()
                c_src = self._get_int8_carrier(src)
                if c_src is not None:
                    self.int8_carrier[u] = self._emit_pad(c_src, in_shape, shape, begins, 'int8')
                continue

            if u.op is Ops.CAST:
                src = u.src[0]
                src_vid = self.env[src]
                src_dtype = p.values[src_vid].dtype
                if src_dtype == dtype:
                    self.env[u] = src_vid
                elif p.values[src_vid].data is not None:
                    p.folded += 1
                    self.env[u] = p.value(shape, dtype, p.values[src_vid].data.astype(dtype))
                else:
                    self.env[u] = p.operation('convert_element_type', [src_vid], shape, dtype,
                                              source={'op': 'tinygrad.CAST', 'location': 'uop'})
                self.bcast_axes[u] = set(self.bcast_axes.get(src, set()))
                if dtype == 'int8':
                    self.int8_carrier[u] = self.env[u]
                elif dtype == 'int32':
                    c_src = self._get_int8_carrier(src)
                    if c_src is not None:
                        self.int8_carrier[u] = c_src
                continue

            if u.op is Ops.REDUCE_AXIS:
                mm = self._try_lower_contraction(u, shape, dtype)
                if mm is not None:
                    self.env[u] = mm
                    self.bcast_axes[u] = set()
                    continue
                reduce_op, axes = u.arg
                axes = tuple(int(a) for a in axes)
                src = u.src[0]
                src_vid = self.env[src]
                in_shape = tuple(int(d) for d in src._shape)
                grid = np.indices(in_shape)
                out_coords = [np.zeros_like(grid[0]) if d in axes else grid[d] for d in range(len(in_shape))]
                mapping = np.ravel_multi_index(out_coords, shape).ravel().tolist() if shape else [0] * int(np.prod(in_shape))
                if reduce_op is Ops.ADD and dtype != 'bool':
                    self.env[u] = p.operation('reduce_sum', [src_vid], shape, dtype, map=mapping,
                                              source={'op': 'tinygrad.REDUCE_ADD', 'location': 'uop'})
                elif reduce_op is Ops.MAX:
                    init_val = (-np.inf if dtype == 'float32'
                                else np.iinfo(np.dtype(dtype)).min if dtype != 'bool' else False)
                    init_vid = p.value((), dtype, np.asarray(init_val, dtype=dtype))
                    self.env[u] = p.operation('reduce', [src_vid, init_vid], shape, dtype,
                                              map=mapping, reducer='max',
                                              source={'op': 'tinygrad.REDUCE_MAX', 'location': 'uop'})
                elif reduce_op is Ops.MUL:
                    init_vid = p.value((), dtype, np.asarray(1, dtype=dtype))
                    self.env[u] = p.operation('reduce', [src_vid, init_vid], shape, dtype,
                                              map=mapping, reducer='mul',
                                              source={'op': 'tinygrad.REDUCE_MUL', 'location': 'uop'})
                else:
                    raise ProgramError(f'unsupported tinygrad reduction {reduce_op}')
                self.bcast_axes[u] = set()
                continue

            if u.op is Ops.EXP2:
                src = u.src[0]
                # Recognize EXP2(x * c) -> exp(x * (c * ln2)), simplifying c*ln2 == +/-1
                base_vid = None
                if src.op is Ops.MUL:
                    s0, s1 = src.src
                    v0, v1 = p.values[self.env[s0]], p.values[self.env[s1]]
                    if v1.data is not None or v0.data is not None:
                        var_u, const_val = (s0, v1) if v1.data is not None else (s1, v0)
                        scaled = np.asarray(const_val.data, dtype=np.float32) * np.float32(np.log(2.0))
                        if np.allclose(scaled, 1.0, rtol=1e-5, atol=1e-5):
                            base_vid = self.env[var_u]
                        elif np.allclose(scaled, -1.0, rtol=1e-5, atol=1e-5):
                            base_vid = p.operation('neg', [self.env[var_u]], shape, 'float32',
                                                   source={'op': 'tinygrad.EXP2_neg', 'location': 'uop'})
                        else:
                            c_vid = p.value(const_val.shape, 'float32', scaled.reshape(const_val.shape))
                            base_vid = p.operation('mul', [self.env[var_u], c_vid], shape, 'float32',
                                                   source={'op': 'tinygrad.EXP2_scale', 'location': 'uop'})
                if base_vid is None:
                    ln2 = p.value((1,) * len(shape), 'float32', np.full((1,) * len(shape), np.log(2.0), dtype=np.float32))
                    base_vid = p.operation('mul', [self.env[src], ln2], shape, 'float32',
                                           source={'op': 'tinygrad.EXP2_scale', 'location': 'uop'})
                self.env[u] = p.operation('exp', [base_vid], shape, 'float32',
                                          source={'op': 'tinygrad.EXP2', 'location': 'uop'})
                self.bcast_axes[u] = set(self.bcast_axes.get(src, set()))
                continue

            if u.op is Ops.RECIPROCAL:
                src = u.src[0]
                one_shape = (1,) * len(shape)
                one = p.value(one_shape, 'float32', np.ones(one_shape, dtype=np.float32))
                self.env[u] = p.operation('div', [one, self.env[src]], shape, 'float32',
                                          source={'op': 'tinygrad.RECIPROCAL', 'location': 'uop'})
                self.bcast_axes[u] = set(self.bcast_axes.get(src, set()))
                continue

            if u.op is Ops.TRUNC:
                src_vid = self.env[u.src[0]]
                if dtype != 'float32':
                    self.env[u] = src_vid
                else:
                    zero = p.value((1,) * len(shape), 'float32', np.zeros((1,) * len(shape), dtype=np.float32))
                    is_neg = p.operation('lt', [src_vid, zero], shape, 'bool')
                    fl_pos = p.operation('floor', [src_vid], shape, 'float32')
                    neg_x = p.operation('neg', [src_vid], shape, 'float32')
                    fl_neg = p.operation('neg', [p.operation('floor', [neg_x], shape, 'float32')], shape, 'float32')
                    self.env[u] = p.operation('select_n', [is_neg, fl_pos, fl_neg], shape, 'float32',
                                              source={'op': 'tinygrad.TRUNC', 'location': 'uop'})
                self.bcast_axes[u] = set(self.bcast_axes.get(u.src[0], set()))
                continue

            if u.op in (Ops.SQRT, Ops.SIN, Ops.NEG):
                op_map = {Ops.SQRT: 'sqrt', Ops.SIN: 'sin', Ops.NEG: 'neg'}
                src = u.src[0]
                self.env[u] = p.operation(op_map[u.op], [self.env[src]], shape, dtype,
                                          source={'op': f'tinygrad.{u.op.name}', 'location': 'uop'})
                self.bcast_axes[u] = set(self.bcast_axes.get(src, set()))
                continue

            if u.op is Ops.WHERE:
                cond, on_true, on_false = u.src
                # ExecutionPlan select_n takes [predicate, on_false, on_true]
                self.env[u] = p.operation('select_n', [self.env[cond], self.env[on_false], self.env[on_true]],
                                          shape, dtype, source={'op': 'tinygrad.WHERE', 'location': 'uop'})
                self.bcast_axes[u] = (self.bcast_axes.get(cond, set()) &
                                      self.bcast_axes.get(on_true, set()) &
                                      self.bcast_axes.get(on_false, set()))
                continue

            binary_map = {
                Ops.ADD: 'or' if dtype == 'bool' else 'add',
                Ops.SUB: 'sub',
                Ops.MUL: 'and' if dtype == 'bool' else 'mul',
                Ops.FDIV: 'div',
                Ops.MAX: 'max',
                Ops.CMPLT: 'lt',
                Ops.CMPNE: 'ne',
                Ops.CMPEQ: 'eq',
                Ops.AND: 'and',
                Ops.OR: 'or',
                Ops.XOR: 'xor',
            }
            if u.op in binary_map:
                s0, s1 = u.src
                v0, v1 = self.env[s0], self.env[s1]
                # Propagate int8_carrier through x + 0 or x - 0 (e.g. OnnxRunner zero_point=0 adjustment)
                if u.op in (Ops.ADD, Ops.SUB) and dtype == 'int32':
                    val0, val1 = p.values[v0], p.values[v1]
                    if val1.data is not None and np.all(val1.data == 0):
                        c0 = self._get_int8_carrier(s0)
                        if c0 is not None:
                            self.int8_carrier[u] = c0
                        self.env[u] = v0
                        self.bcast_axes[u] = set(self.bcast_axes.get(s0, set()))
                        continue
                    if u.op is Ops.ADD and val0.data is not None and np.all(val0.data == 0):
                        c1 = self._get_int8_carrier(s1)
                        if c1 is not None:
                            self.int8_carrier[u] = c1
                        self.env[u] = v1
                        self.bcast_axes[u] = set(self.bcast_axes.get(s1, set()))
                        continue
                # Recognize x * -1 as neg(x) to preserve bcast_axes and simplify
                if u.op is Ops.MUL and dtype == 'float32':
                    val0, val1 = p.values[v0], p.values[v1]
                    if val1.data is not None and np.all(val1.data == -1.0):
                        self.env[u] = p.operation('neg', [v0], shape, dtype,
                                                  source={'op': 'tinygrad.NEG', 'location': 'uop'})
                        self.bcast_axes[u] = set(self.bcast_axes.get(s0, set()))
                        continue
                    if val0.data is not None and np.all(val0.data == -1.0):
                        self.env[u] = p.operation('neg', [v1], shape, dtype,
                                                  source={'op': 'tinygrad.NEG', 'location': 'uop'})
                        self.bcast_axes[u] = set(self.bcast_axes.get(s1, set()))
                        continue

                self.env[u] = p.operation(binary_map[u.op], [v0, v1], shape, dtype,
                                          source={'op': f'tinygrad.{u.op.name}', 'location': 'uop'})
                self.bcast_axes[u] = self.bcast_axes.get(s0, set()) & self.bcast_axes.get(s1, set())
                continue

            raise ProgramError(f'tinygrad UOp {u.op} ({dtype}{shape}) has no backend lowering')

        p.outputs = [self.env[out_u] for out_u in output_uops]
        p.validate()
        return p


def compile_tinygrad(fn_or_outputs, example_inputs, output, options=None):
    """Trace a tinygrad function or Tensor outputs and compile to freestanding C / TPU code."""
    _, Tensor, dtypes, Ops, _ = _import_tinygrad()
    if isinstance(example_inputs, (np.ndarray, Tensor)):
        example_list = [example_inputs]
    else:
        example_list = list(example_inputs)

    input_tensors = []
    for item in example_list:
        if isinstance(item, Tensor):
            input_tensors.append(Tensor.empty(*item.shape, dtype=item.dtype))
        else:
            arr = np.asarray(item)
            tg_dtype = getattr(dtypes, _DTYPE_MAP[str(arr.dtype)])
            input_tensors.append(Tensor.empty(*arr.shape, dtype=tg_dtype))

    if callable(fn_or_outputs):
        res = fn_or_outputs(*input_tensors) if len(input_tensors) != 1 else fn_or_outputs(input_tensors[0])
    else:
        res = fn_or_outputs

    if isinstance(res, dict):
        output_tensors = list(res.values())
    elif isinstance(res, (tuple, list)):
        output_tensors = list(res)
    else:
        output_tensors = [res]

    lowering = TinygradLowering(Tensor, dtypes, Ops)
    plan = lowering.lower([t.uop for t in output_tensors], input_tensors)
    report = _compile_schedule(plan, output, options)
    report['input_format'] = 'tinygrad'
    report['source_operations'] = dict(lowering.source_ops)
    return report


def compile_onnx_via_tinygrad(onnx_source, output, options=None, *, input_shapes=None):
    """Load an ONNX model using tinygrad's OnnxRunner and compile to freestanding C / TPU code."""
    _, Tensor, dtypes, _, OnnxRunner = _import_tinygrad()
    model_path = Path(onnx_source) if isinstance(onnx_source, (str, Path)) else Tensor(np.frombuffer(onnx_source, dtype=np.uint8))
    runner = OnnxRunner(model_path)

    input_tensors = []
    input_names = list(runner.graph_inputs.keys())
    for name in input_names:
        spec = runner.graph_inputs[name]
        shape = tuple(input_shapes[name] if input_shapes and name in input_shapes else
                      tuple(int(d) if isinstance(d, int) else 1 for d in spec.shape))
        dtype_name = _map_dtype(spec.dtype)
        tg_dtype = getattr(dtypes, dtype_name)
        input_tensors.append(Tensor.empty(*shape, dtype=tg_dtype))

    def trace_fn(*args):
        feed = dict(zip(input_names, args)) if len(input_names) > 1 else {input_names[0]: args[0]}
        outputs = runner(feed)
        return [outputs[name] for name in runner.graph_outputs]

    report = compile_tinygrad(trace_fn, input_tensors, output, options)
    report['input_format'] = 'tinygrad-onnx'
    report['onnx_inputs'] = input_names
    report['onnx_outputs'] = list(runner.graph_outputs)
    return report
