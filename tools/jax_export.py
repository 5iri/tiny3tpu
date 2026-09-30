#!/usr/bin/env python3
"""Minimal JAX exporter for the current int32 QGEMM contract."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Any

class ExportError(ValueError):
    pass

def _jax():
    try:
        import jax
        import jax.numpy as jnp
    except ImportError as exc:
        raise ExportError("JAX is required for the JAX exporter") from exc
    return jax, jnp

def _const(var, consts, jnp):
    value = consts.get(id(var))
    if value is None and hasattr(var, "val"):
        value = var.val
    return None if value is None else jnp.asarray(value)

def export_function(function, example_input, output_path: str | Path) -> dict[str, Any]:
    jax, jnp = _jax()
    x = jnp.asarray(example_input)
    if x.dtype != jnp.int8 or x.ndim != 2:
        raise ExportError("example_input must be a static rank-2 int8 array")
    closed = jax.make_jaxpr(function)(x)
    jp = closed.jaxpr
    if len(jp.invars) != 1:
        raise ExportError("only one input argument is supported")
    consts = {id(v): value for v, value in zip(jp.constvars, closed.consts)}
    values = {id(jp.invars[0]): (0, tuple(x.shape), "i8")}
    tensors = [{"id": 0, "name": "input", "dtype": "i8", "layout": "packed", "shape": list(x.shape), "scale": 1.0, "zero_point": 0, "flags": ["input"]}]
    operations = []
    produced_qgemm_outputs = set()
    next_id = 1
    last_gemm = None
    fused_bias = False
    # JAX represents rank-1 bias promotion as broadcast_in_dim. Keep it
    # symbolic until the following add so it never becomes a fake tensor.
    broadcast_consts = {}
    uses = {}
    for eqn in jp.eqns:
        for var in eqn.invars:
            uses[id(var)] = uses.get(id(var), 0) + 1
    for var in jp.outvars:
        uses[id(var)] = uses.get(id(var), 0) + 1
    def add_tensor(name, shape, dtype, flags=None, data=None):
        nonlocal next_id
        item = {"id": next_id, "name": name, "dtype": dtype, "layout": "packed", "shape": list(shape), "scale": 1.0, "zero_point": 0}
        if flags: item["flags"] = list(flags)
        if data is not None: item["data"] = [int(v) for v in data]
        tensors.append(item); result = (next_id, tuple(shape), dtype); next_id += 1
        return result
    for eqn in jp.eqns:
        primitive = eqn.primitive.name
        if len(eqn.outvars) != 1: raise ExportError(f"unsupported JAX primitive: {primitive}")
        outvar = eqn.outvars[0]
        if any(not isinstance(d, int) or d <= 0 for d in outvar.aval.shape):
            raise ExportError(f"{primitive} must have static positive dimensions")
        if primitive == "broadcast_in_dim":
            if len(eqn.invars) != 1:
                raise ExportError("broadcast_in_dim must have one operand")
            value = _const(eqn.invars[0], consts, jnp)
            dims = tuple(eqn.params.get("broadcast_dimensions", ()))
            shape = tuple(outvar.aval.shape)
            if value is None or value.dtype != jnp.int32 or value.ndim != 1:
                raise ExportError("only closed-over rank-1 int32 bias broadcast is supported")
            if len(shape) != 2 or tuple(value.shape) != (shape[1],) or dims != (1,):
                raise ExportError("bias broadcast must expand [N] to [M,N]")
            if uses.get(id(outvar), 0) != 1:
                raise ExportError("bias broadcast must have exactly one consumer")
            broadcast_consts[id(outvar)] = value
        elif primitive == "dot_general":
            if len(eqn.invars) != 2: raise ExportError("dot_general requires two operands")
            lhs = values.get(id(eqn.invars[0])); weight = _const(eqn.invars[1], consts, jnp)
            if lhs is None or weight is None: raise ExportError("dot_general requires input and closed-over constant weight")
            if lhs[2] != "i8" or weight.dtype != jnp.int8 or weight.ndim != 2: raise ExportError("dot_general requires rank-2 int8 operands")
            dimension_numbers = eqn.params.get("dimension_numbers")
            if not isinstance(dimension_numbers, tuple) or len(dimension_numbers) != 2:
                raise ExportError("only rank-2 [M,K] x [K,N] dot_general is supported; invalid dimension_numbers")
            contracting, batch = dimension_numbers
            if (not isinstance(contracting, tuple) or len(contracting) != 2 or
                    not all(isinstance(axes, tuple) and len(axes) == 1 for axes in contracting) or
                    not isinstance(batch, tuple) or len(batch) != 2 or
                    not all(isinstance(axes, tuple) for axes in batch)):
                raise ExportError("only rank-2 [M,K] x [K,N] dot_general is supported; invalid axis structure")
            ((lc,), (rc,)), (lb, rb) = contracting, batch
            if (lc, rc) != (1, 0) or lb or rb: raise ExportError("only rank-2 [M,K] x [K,N] dot_general is supported; batch axes are rejected")
            if lhs[1][1] != weight.shape[0] or outvar.aval.dtype != jnp.int32: raise ExportError("dot_general must produce int32 with matching [M,K] x [K,N] shapes")
            w = add_tensor("weight", (weight.shape[1], weight.shape[0]), "i8", ["constant"], weight.T.reshape(-1))
            b = add_tensor("bias", (weight.shape[1],), "i32", ["constant"], [0] * weight.shape[1])
            out = add_tensor("dense", tuple(outvar.aval.shape), "i32")
            last_gemm = {"opcode": "qgemm", "inputs": [lhs[0], w[0], b[0]], "outputs": [out[0]], "params": {"flags": 0}}
            operations.append(last_gemm); values[id(outvar)] = out
            produced_qgemm_outputs.add(id(outvar))
        elif primitive in ("add", "add_any"):
            if last_gemm is None: raise ExportError("bias add must immediately follow dot_general")
            lhs = values.get(id(eqn.invars[0])); bias = _const(eqn.invars[1], consts, jnp)
            if bias is None: bias = broadcast_consts.get(id(eqn.invars[1]))
            if lhs is None or bias is None:
                lhs, bias = values.get(id(eqn.invars[1])), _const(eqn.invars[0], consts, jnp)
                if bias is None: bias = broadcast_consts.get(id(eqn.invars[0]))
            if lhs is None or bias is None or bias.dtype != jnp.int32 or bias.ndim != 1 or tuple(bias.shape) != (lhs[1][-1],): raise ExportError("optional bias must be a closed-over rank-1 int32 constant")
            if last_gemm["outputs"][0] != lhs[0]: raise ExportError("bias add does not consume the dot output")
            if fused_bias or uses.get(id(eqn.invars[0]), 0) > 1 or uses.get(id(eqn.invars[1]), 0) > 1:
                raise ExportError("exactly one bias fusion is supported; repeated/shared bias use is rejected")
            tensors[last_gemm["inputs"][2]]["data"] = [int(v) for v in bias.tolist()]
            values[id(eqn.outvars[0])] = lhs
            # The add is represented by the fused QGEMM, so its result is
            # still a supported produced value.  Keep identity/input/constant
            # returns rejected: only successful bias fusion gets this mark.
            produced_qgemm_outputs.add(id(eqn.outvars[0]))
            fused_bias = True
        else:
            raise ExportError(f"unsupported JAX primitive for minimal exporter: {primitive}; relu/reshape/argmax are rejected")
    if len(jp.outvars) != 1:
        raise ExportError("only one output is supported")
    if id(jp.outvars[0]) not in produced_qgemm_outputs:
        raise ExportError("unsupported JAX primitive or identity/no-op function; each output must be a produced QGEMM result")
    output_id = values[id(jp.outvars[0])][0]; tensors[output_id]["flags"] = ["output"]
    graph = {"tensors": tensors, "operations": operations, "inputs": [0], "outputs": [output_id], "description": "minimal JAX int32 QGEMM export"}
    Path(output_path).write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
    return graph

def main():
    argparse.ArgumentParser(description=__doc__).parse_args()
    raise SystemExit("CLI requires a Python function; use export_function()")
if __name__ == "__main__": main()
