#!/usr/bin/env python3
"""Execute StableHLO-generated CPU/TPU programs against the AXIS accelerator RTL."""
import argparse
from pathlib import Path
import subprocess
import sys

try:
    import jax
    import jax.numpy as jnp
    import numpy as np
except ImportError:
    print('SKIP: JAX test dependencies unavailable')
    raise SystemExit(77)

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools.jax_stablehlo import export_function
from tools.program import compile_stablehlo,CompileOptions,KC705


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--cloth-artifact',type=Path)
    parser.add_argument('--cloth-input',type=Path)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(14)
    a=rng.integers(-128,128,(5,9),dtype=np.int8)
    b=rng.integers(-128,128,(9,7),dtype=np.int8)
    def dot(a,b):
        x=jax.lax.dot_general(a,b,(((1,),(0,)),((),())),preferred_element_type=jnp.int32)
        return x+jnp.int32(7),jnp.sum(x,axis=0)
    x=np.arange(48,dtype=np.float32).reshape(16,3)/32;y=x/2-1
    def affine(x,y):return (x-y)*2+(x+y)*3-x*4+y*2
    cases=[('dot',export_function(dot,a,b),[a,b]),
           ('affine',export_function(affine,x,y),[x,y])]
    def looped(x,n):
        weights=jnp.eye(3,dtype=jnp.int8)
        def step(_,state):
            y=jax.lax.dot_general(state.astype(jnp.int8),weights,(((1,),(0,)),((),())),preferred_element_type=jnp.int32)
            return y.astype(jnp.float32)+1
        return jax.lax.fori_loop(0,n,step,x)
    cases.append(('looped',export_function(looped,x,np.int32(3)),[x,np.int32(3)]))
    if args.cloth_artifact:
        if not args.cloth_input:parser.error('--cloth-artifact requires --cloth-input')
        cases.append(('cloth',args.cloth_artifact,[np.load(args.cloth_input)]))
    headers=[];statements=[]
    for name,source,inputs in cases:
        opts=CompileOptions(target=KC705,symbol=name,allow_approximation=True,
                            math_mode='freestanding',affine_offload=True,
                            affine_policy='force',
                            coefficient_tolerance=.0002 if name=='cloth' else 0.)
        report=compile_stablehlo(source,out/f'{name}.h',opts)
        headers.append(f'#include "{name}.h"')
        statements.append('{')
        for i,array in enumerate(inputs):
            typ={np.dtype('float32'):'float',np.dtype('int8'):'int8_t',np.dtype('int32'):'int32_t'}[array.dtype]
            data=','.join(float(v).hex()+'f' if typ=='float' else str(int(v)) for v in array.ravel())
            statements.append(f'{typ} input{i}[]={{'+data+'};')
        statements.append('const void *inputs[]={'+','.join('input'+str(i) for i in range(len(inputs)))+'};')
        for i,desc in enumerate(report['signature']['outputs']):
            typ='float' if desc['dtype']=='float32' else 'int32_t'
            size=int(np.prod(desc['shape']))
            statements.append(f'{typ} want{i}[{size}]={{}},got{i}[{size}]={{}};')
        count=len(report['signature']['outputs'])
        for prefix in ('want','got'):
            statements.append(f'void *{prefix}[]={{'+','.join(prefix+str(i) for i in range(count))+'};')
        statements += [f'static {name}_workspace work;',
                       f'if({name}_run(inputs,want,&work,&reference)||{name}_run(inputs,got,&work,&hardware))return 2;']
        for i in range(count):
            statements.append(f'if(std::memcmp(want{i},got{i},sizeof(want{i}))){{std::cerr<<"{name} output {i} mismatch\\n";return 3;}}')
        statements.append(f'std::cout<<"PASS {name}: generated CPU program + TPU RTL exact match\\n";')
        statements.append('}')
    source=r'''
#include <cstdint>
#include <cstring>
#include <iostream>
#include "tiny3tpu_mmio_backend.h"
#include "axis_mailbox_sim.hpp"
HEADERS
static int gemm(void *,const int8_t *a,const int8_t *b,int32_t *out,uint32_t m,uint32_t k,uint32_t n) {
    for(uint32_t i=0;i<m;i++)for(uint32_t j=0;j<n;j++) {
        int64_t sum=0;for(uint32_t t=0;t<k;t++)sum+=(int32_t)a[i*k+t]*b[t*n+j];
        if(sum<INT32_MIN||sum>INT32_MAX)return -1;
        out[i*n+j]=(int32_t)sum;
    }
    return 0;
}
int main() {
    Simulation sim;
    tiny3tpu_mmio io{&sim,read32,write32,1000};
    tiny3tpu_qgemm_backend hardware{&io,tiny3tpu_mmio_qgemm},reference{nullptr,gemm};
    STATEMENTS
    if(!sim.launches)return 4;
    std::cout<<"PASS StableHLO backend: "<<sim.launches<<" physical-design RTL launches\n";
}
'''.replace('HEADERS','\n'.join(headers)).replace('STATEMENTS','\n'.join(statements))
    (out/'check.cpp').write_text(source)
    def run(command,name):
        with (out/f'{name}.log').open('w') as log:
            result=subprocess.run([str(c) for c in command],stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out/f'{name}.log').read_text()[-12000:])
    for driver in ('mmio_backend','axis_mailbox'):
        run(['cc','-std=c11','-O2','-I'+str(ROOT/'include'),'-c',ROOT/f'src/{driver}.c','-o',out/f'{driver}.o'],driver)
    rtl=[ROOT/'multi-core'/n for n in ('synapse32_tpu_peripheral.sv','synapse32_axis_mailbox.sv',
         'tiny3tpu_axis.sv','tiny3tpu_axis_bridge.sv','tiny3tpu_axi.sv','top.v','tpu_core_wrapper.sv')]
    rtl += [ROOT/'systolic_array/rtl'/n for n in ('NxN_systolic_array.v','pe.v')]
    run(['verilator','--cc','--exe','--build','-j','2','-Wno-fatal','--top-module','synapse32_tpu_peripheral',
         '--Mdir',out/'obj','-CFLAGS',f'-std=c++17 -ffp-contract=off -I{ROOT}/include -I{ROOT}/tests -I{out}',
         '-LDFLAGS',f'{out}/mmio_backend.o {out}/axis_mailbox.o -lm',*rtl,out/'check.cpp'],'build')
    run([out/'obj/Vsynapse32_tpu_peripheral'],'run')
    print((out/'run.log').read_text(),end='')


if __name__=='__main__':main()
