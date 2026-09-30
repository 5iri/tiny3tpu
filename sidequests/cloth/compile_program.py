#!/usr/bin/env python3
"""Export cloth to StableHLO and compile it with the generic backend."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('upstream',type=Path)
    parser.add_argument('--out',type=Path,default=ROOT/'build-cloth/stablehlo')
    parser.add_argument('--affine-offload',action='store_true')
    parser.add_argument('--affine-policy',choices=('auto','force'),default='auto')
    args=parser.parse_args()
    sys.path.insert(0,str(args.upstream.resolve()))
    import jax.numpy as jnp
    import numpy as np
    from model import Cloth
    from tools.jax_stablehlo import export_function
    from tools.program import compile_stablehlo,CompileOptions,KC705
    cloth=Cloth(6,3)
    initial=jnp.concatenate(cloth.initial,axis=1)
    def step(x):return jnp.concatenate(cloth.advance((x[:,:3],x[:,3:]),1),axis=1)
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    artifact=export_function(step,initial,output=out/'cloth.mlirbc')
    report=compile_stablehlo(artifact,out/'cloth_program.h',CompileOptions(
        target=KC705,math_mode='freestanding',allow_approximation=True,
        affine_offload=args.affine_offload,affine_policy=args.affine_policy,coefficient_tolerance=.0002))
    (out/'compile-report.json').write_text(json.dumps(report,indent=2)+'\n')
    np.save(out/'input.npy',np.asarray(initial))
    print(json.dumps({k:report[k] for k in ('input_format','program','workspace_bytes','partitions')},indent=2))


if __name__=='__main__':main()
