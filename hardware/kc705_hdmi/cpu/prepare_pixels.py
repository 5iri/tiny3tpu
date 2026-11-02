#!/usr/bin/env python3
"""Build the generic framebuffer fixture; JAX is used only offline."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import jax
import numpy as np
from pixels_workload import transform

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT/'tests')]
from tools.jax_stablehlo import export_function
from tools.program import CompileOptions, KC705_DIRECT, compile_stablehlo
from test_stablehlo_compiler import Compiled
from sidequests.showcase.build_support import compile_firmware


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    out = p.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=True)
    artifact = export_function(transform,np.zeros(1,np.int32),output=out/'program.mlirbc')
    options = CompileOptions(target=KC705_DIRECT,math_mode='freestanding',allow_approximation=True,gemm_policy='tpu')
    native = Compiled(artifact,options)
    expected = []
    try:
        reference = jax.jit(transform)
        for phase in range(64):
            x=np.array([phase],np.int32);want=np.asarray(reference(x))
            status,got=native.run(x,mode=3)
            assert status==0
            np.testing.assert_array_equal(got[0],want)
            expected.append(want)
        assert native.library.backend_calls()+native.library.packed_backend_calls()==64
    finally:
        native.close()
    np.save(out/'coordinates.npy',np.stack(expected))
    from dataclasses import replace
    report=compile_stablehlo(artifact,out/'pixels_program.h',replace(options,symbol='pixels_program'))
    (out/'compile-report.json').write_text(json.dumps(report,indent=2)+'\n')
    build=compile_firmware(Path(__file__).with_name('pixels_firmware.c'),[out],out,
        tpu_transport='direct',clock_hz=25200000,linker_script=Path(__file__).with_name('linker.ld'))
    build.update(workload='cpu-rgb565',framebuffer_abi='PFB1',framebuffer=[160,120],
                 pixel_format='RGB565',display=[640,480],cores=2,array=[4,4],
                 jax_native_exact_coordinates=1024,training=False,
                 scope='Architecture fixture; no MJX simulation or RL training in this firmware')
    paths=[Path(__file__),Path(__file__).with_name('pixels_workload.py'),
           ROOT/'include/tiny3tpu_framebuffer.h',ROOT/'sidequests/showcase/build_support.py',
           out/'program.mlirbc',out/'pixels_program.h',out/'coordinates.npy']
    build['workload_sha256']={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in paths}
    (out/'build-manifest.json').write_text(json.dumps(build,indent=2)+'\n')
    print(json.dumps(build['memory'],indent=2))


if __name__=='__main__':main()
