"""Lower row-wise affine JAX islands to the existing int8 QGEMM IR.

Only a bounded arithmetic subset is accepted. Nonlinear operations and
multiplication of two input-dependent values are rejected. Signed wider
inputs use two base-256 digits, preserving integer inputs exactly.
"""
from pathlib import Path
import json
import numpy as np

class LoweringError(ValueError):
    pass

def lower_rowwise_affine(function, rows, columns, output_path):
    if not isinstance(rows,int) or not isinstance(columns,int) or rows<=0 or columns<=0:
        raise LoweringError('rows and columns must be positive integers')
    import jax
    import jax.numpy as jnp
    from tools.jax_export import export_function
    closed=jax.make_jaxpr(function)(jnp.zeros((rows,columns),dtype=jnp.float32))
    dependencies={id(v):False for v in closed.jaxpr.constvars}
    dependencies.update({id(v):True for v in closed.jaxpr.invars})
    allowed={'slice','squeeze','broadcast_in_dim','concatenate','add','sub','mul','neg','convert_element_type','reshape','transpose','stack'}
    for eqn in closed.jaxpr.eqns:
        name=eqn.primitive.name
        if name not in allowed:raise LoweringError(f'unsupported affine primitive: {name}')
        deps=[dependencies.get(id(v),False) for v in eqn.invars]
        if name=='convert_element_type' and any(deps) and not np.issubdtype(eqn.outvars[0].aval.dtype,np.floating):
            raise LoweringError('input-dependent integer cast is nonlinear')
        if name=='mul' and all(deps):raise LoweringError('nonlinear input-dependent multiplication')
        for v in eqn.outvars:dependencies[id(v)]=any(deps)
    zero=np.asarray(function(jnp.zeros((rows,columns),jnp.float32)))
    if zero.ndim!=2 or zero.shape[0]!=rows:raise LoweringError('expected row-wise rank-2 output')
    if np.any(zero):raise LoweringError('nonzero affine bias requires a separate CPU operation')
    # Extract coefficients after the IR dependence proof; verify row independence
    # and identical coefficients, rather than trusting a few random probes.
    jac=np.asarray(jax.jacfwd(function)(jnp.zeros((rows,columns),jnp.float32)))
    weights=jac[0,:,0,:].T
    wanted=np.zeros_like(jac)
    for r in range(rows):wanted[r,:,r,:]=weights.T
    if not np.allclose(jac,wanted,rtol=0,atol=1e-6):raise LoweringError('coefficients differ by row or mix rows')
    rounded=np.rint(weights)
    if not np.allclose(weights,rounded,rtol=0,atol=2e-4):raise LoweringError('noninteger coefficients need an explicit quantization policy')
    if (rounded< -128).any() or (rounded>127).any():raise LoweringError('coefficient outside signed int8')
    w=jnp.asarray(rounded,dtype=jnp.int8)
    def gemm(x):return jax.lax.dot_general(x,w,(((1,),(0,)),((),())),preferred_element_type=jnp.int32)
    graph=export_function(gemm,jnp.zeros((2*rows,columns),dtype=jnp.int8),output_path)
    return {'weights':rounded.astype(np.int8).tolist(),'input_shape':[rows,columns],
            'output_shape':list(zero.shape),'lowered_shape':[2*rows,columns],
            'passes':['prove_affine_dependence','extract_rowwise_matrix','round_with_explicit_coefficient_bound','split_signed16_base256','export_QGEMM'],
            'max_coefficient_rounding_error':float(abs(weights-rounded).max()),'graph':graph}

def split_signed16(values):
    a=np.asarray(values)
    if not np.issubdtype(a.dtype,np.integer) or (a< -32640).any() or (a>32639).any():
        raise LoweringError('wide input outside balanced two-digit range')
    low=((a.astype(np.int32)+128)%256)-128
    high=(a.astype(np.int32)-low)//256
    return low.astype(np.int8),high.astype(np.int8)
