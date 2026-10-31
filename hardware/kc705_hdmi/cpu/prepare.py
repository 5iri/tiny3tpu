#!/usr/bin/env python3
"""Export JAX, compile RV32 firmware, and compare all rotation outputs to JAX."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import jax
import numpy as np
from workload import ROOT, make_workload

sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.jax_stablehlo import export_function
from tools.program import CompileOptions, KC705_DIRECT, compile_stablehlo
from test_stablehlo_compiler import Compiled
from sidequests.showcase.build_support import compile_firmware


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=ROOT/'build-kc705-hdmi/cpu-firmware')
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    mesh=json.loads((ROOT/'hardware/kc705_hdmi/assets/mesh.json').read_text())
    fn=make_workload();phase=np.zeros(1,np.int32)
    artifact=export_function(fn,phase,output=out/'banana_spinner369.mlirbc')
    options=CompileOptions(target=KC705_DIRECT,math_mode='freestanding',
                           allow_approximation=True,gemm_policy='tpu',affine_offload=False)
    native=Compiled(artifact,options)
    expected=[]
    try:
        reference=jax.jit(fn)
        for p in range(256):
            x=np.array([p],np.int32);wanted=np.asarray(reference(x))
            status,got=native.run(x,mode=3)
            assert status==0
            np.testing.assert_array_equal(got[0],wanted,err_msg=f'phase {p}')
            expected.append(wanted)
        assert native.library.packed_backend_calls()==256
    finally:native.close()
    expected=np.stack(expected);np.save(out/'jax-coordinates.npy',expected)
    report=compile_stablehlo(artifact,out/'banana_spinner369.h',
        CompileOptions(target=KC705_DIRECT,symbol='banana_spinner369',math_mode='freestanding',
                       allow_approximation=True,gemm_policy='tpu',affine_offload=False))
    assert sum(row.get('device')=='tpu' for row in report['placement'])==1
    (out/'compile-report.json').write_text(json.dumps(report,indent=2)+'\n')
    # Keep one exact startup oracle in board RAM; all 256 phases are checked
    # above without storing a precomputed animation in the firmware.
    vertices=expected.shape[1]
    (out/'jax_expected.h').write_text('#define JAX_VERIFY_PHASES 1\n'+
        f'#define JAX_VERTEX_COUNT {vertices}\n'+
        f'static const int32_t jax_expected[JAX_VERIFY_PHASES][{vertices*3}]={{\n'+
        '{'+','.join(str(int(v)) for v in expected[0].reshape(-1))+'}\n};\n')
    build=compile_firmware(Path(__file__).with_name('firmware.c'),[out],out,
                           tpu_transport='direct',clock_hz=25200000,linker_script=Path(__file__).with_name('linker.ld'))
    build.update(workload='BananaSpinner369',vertices=vertices,triangles=len(mesh['faces']),
                 jax_version=jax.__version__,jax_native_exact_phases=256,
                 jax_native_exact_coordinates=int(expected.size),cores=2,array=[4,4],
                 display=[640,480],resident_animation_frames=False,jax_verify_phases=1,animation_hz=30)
    paths=[Path(__file__),Path(__file__).with_name('workload.py'),
           ROOT/'sidequests/showcase/build_support.py',ROOT/'include/tiny3tpu_hdmi.h',ROOT/'hardware/kc705_hdmi/assets/mesh.json',
           out/'banana_spinner369.mlirbc',out/'banana_spinner369.h',out/'jax_expected.h',out/'jax-coordinates.npy']
    build['workload_sha256']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    (out/'build-manifest.json').write_text(json.dumps(build,indent=2)+'\n')
    print(json.dumps({k:build[k] for k in ('workload','cores','array','jax_native_exact_coordinates','memory')},indent=2))


if __name__=='__main__':main()
