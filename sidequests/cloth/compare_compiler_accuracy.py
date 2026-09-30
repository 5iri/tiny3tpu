#!/usr/bin/env python3
"""Isolate float evaluation, freestanding math and TPU quantization trajectory error."""
import argparse
import ctypes
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('upstream',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'build-stablehlo/accuracy/isolation.json')
    args=parser.parse_args()
    sys.path.insert(0,str(args.upstream.resolve()))
    import numpy as np
    import jax.numpy as jnp
    from model import Cloth
    from test_stablehlo_compiler import Compiled
    from tools.jax_stablehlo import export_function
    from tools.program import CompileOptions,KC705
    model=Cloth(6,3)
    initial=np.concatenate(model.initial,axis=1).astype(np.float32)
    def step(x):return jnp.concatenate(model.advance((x[:,:3],x[:,3:]),1),axis=1)
    artifact=export_function(step,initial)
    refs={n:np.concatenate(model.advance(model.initial,n),axis=1) for n in (1,7680,11520)}
    policies={
        'cpu_libm':CompileOptions(),
        'cpu_freestanding':CompileOptions(target=KC705,math_mode='freestanding',allow_approximation=True),
        'tpu_affine':CompileOptions(target=KC705,math_mode='freestanding',allow_approximation=True,
                                    affine_offload=True,affine_policy='force',coefficient_tolerance=.0002),
    }
    report={}
    for name,options in policies.items():
        compiled=Compiled(artifact,options)
        try:
            state=initial.copy()
            pointers=(ctypes.c_void_p*1)(state.ctypes.data)
            records=[]
            for n in range(1,max(refs)+1):
                status=compiled.library.run(pointers,pointers,0)
                if status:raise RuntimeError(f'{name} failed at step {n}: {status}')
                if n in refs:
                    records.append({'steps':n,'position_error_m':float(abs(state[:,:3]-refs[n][:,:3]).max()),
                                    'velocity_error':float(abs(state[:,3:]-refs[n][:,3:]).max())})
            report[name]=records
        finally:compiled.close()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
