#!/usr/bin/env python3
"""Execute generated freestanding code on VexRiscv + TPU RTL, with no host compute.

This test harness uses one float32 input/output. The compiler itself supports
multiple mixed-type arguments. Optional artifacts allow application smoke tests.
"""
import argparse
from pathlib import Path
import subprocess
import sys
import json
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from test_stablehlo_compiler import Compiled
from tools.program import CompileOptions,KC705,KC705_ROCKET,KC705_CORDIC,compile_stablehlo
from tools.jax_stablehlo import export_function


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--artifact',type=Path)
    parser.add_argument('--input',type=Path)
    parser.add_argument('--no-affine',action='store_true')
    parser.add_argument('--force-affine',action='store_true')
    parser.add_argument('--no-fusion',action='store_true')
    parser.add_argument('--cordic',action='store_true',help='Enable the hardware exponential target and real CORDIC peripheral')
    parser.add_argument('--profile',action='store_true',help='Measure CPU/TPU callback cycles on the same RTL')
    parser.add_argument('--cpu',choices=('vexriscv','rocket'),default='vexriscv')
    parser.add_argument('--steps',type=int,default=1,help='Repeat a shape-preserving state update on board')
    parser.add_argument('--synapse32-dir',type=Path,default=ROOT.parent/'synapse32')
    args=parser.parse_args()
    if args.cordic and args.cpu!='vexriscv':parser.error('--cordic currently requires VexRiscv')
    if args.steps<1:parser.error('--steps must be positive')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    if args.artifact:
        if not args.input:parser.error('--artifact requires --input')
        source=args.artifact;data=np.load(args.input)
    else:
        import jax,jax.numpy as jnp
        data=np.arange(15,dtype=np.float32).reshape(3,5)-7
        weights=jnp.arange(20,dtype=jnp.int8).reshape(5,4)-10
        def workload(x):
            y=jax.lax.dot_general(x.astype(jnp.int8),weights,(((1,),(0,)),((),())),preferred_element_type=jnp.int32)
            y=jnp.sqrt(jnp.abs(y.astype(jnp.float32))+1)/3
            indices=jnp.array([0,2],jnp.int32)+(x[0,0]>0).astype(jnp.int32)
            updates=jnp.sin(y[indices])+jnp.cos(y[indices])
            y=y.at[indices].add(updates)
            count=jnp.where(x[0,0]<0,jnp.int32(3),jnp.int32(1))
            identity=jnp.eye(4,dtype=jnp.int8)[None,:,:]
            def step(_,state):
                product=jax.lax.dot_general(state[None,:,:].astype(jnp.int8),identity,
                    (((2,),(1,)),((0,),(0,))),preferred_element_type=jnp.int32)
                return product[0].astype(jnp.float32)+1
            return jnp.max(jax.lax.fori_loop(0,count,step,y),axis=0)
        source=export_function(workload,data)
    options=CompileOptions(target=KC705_ROCKET if args.cpu=='rocket' else KC705,math_mode='freestanding',allow_approximation=True,
                           affine_offload=not args.no_affine,coefficient_tolerance=.0002,
                           affine_policy='force' if args.force_affine else 'auto',fusion=not args.no_fusion)
    native=Compiled(source,options)
    try:
        status,outputs=native.run(data)
        if status or len(outputs)!=1 or outputs[0].dtype!=np.float32:
            raise RuntimeError('SoC fixture requires one successful float32 output')
        if args.steps>1:
            if outputs[0].shape!=data.shape:raise RuntimeError('Repeated steps require matching input/output shapes')
            for _ in range(args.steps-1):
                status,outputs=native.run(outputs[0])
                if status:raise RuntimeError('Native repeated step failed')
        (out/'program.h').write_text((native.path/'program.h').read_text())
        (out/'compile-report.json').write_text(json.dumps(native.report,indent=2)+'\n')
    finally:native.close()
    if args.cordic:
        from dataclasses import replace
        report=compile_stablehlo(source,out/'program.h',replace(options,target=KC705_CORDIC))
        (out/'compile-report.json').write_text(json.dumps(report,indent=2)+'\n')
    initial=','.join(float(v).hex()+'f' for v in data.ravel())
    expected=','.join(str(int(v))+'U' for v in outputs[0].ravel().view(np.uint32))
    (out/'fixture.h').write_text('static float state[]={'+initial+'};\nstatic const uint32_t expected[]={'+expected+'};\n')
    firmware=r'''
#include <stddef.h>
#include "program.h"
#include "fixture.h"
#include "tiny3tpu_axis_mailbox.h"
#include "tiny3tpu_mmio_backend.h"
static t3p_workspace workspace;
static float result[T3P_OUTPUT_0_ELEMENTS];
void *memcpy(void *d,const void *s,size_t n){unsigned char *a=d;const unsigned char *b=s;for(size_t i=0;i<n;i++)a[i]=b[i];return d;}
void *memset(void *d,int x,size_t n){unsigned char *a=d;for(size_t i=0;i<n;i++)a[i]=(unsigned char)x;return d;}
static int rd(void *u,uint32_t a,uint32_t *v){(void)u;*v=*(volatile uint32_t *)(uintptr_t)(0x20001000U+a);return 0;}
static int wr(void *u,uint32_t a,uint32_t v){(void)u;*(volatile uint32_t *)(uintptr_t)(0x20001000U+a)=v;return 0;}
int main(void){
    tiny3tpu_axis_mailbox mailbox;
    if(tiny3tpu_axis_mailbox_init(&mailbox,0,rd,wr,1000))return 1;
    tiny3tpu_mmio io={&mailbox,tiny3tpu_axis_mailbox_read32,tiny3tpu_axis_mailbox_write32,1000};
    tiny3tpu_qgemm_backend be={&io,tiny3tpu_mmio_qgemm};
    const void *inputs[]={state};void *outputs[]={result};
    int status=t3p_run(inputs,outputs,&workspace,&be);
    if(status)return 10-status;
    for(unsigned i=0;i<T3P_OUTPUT_0_ELEMENTS;i++) {
        union {float f;uint32_t u;} value={result[i]};
        if(value.u!=expected[i])return 100+i;
    }
    *(volatile uint32_t *)(uintptr_t)0x20002004U=T3P_OUTPUT_0_ELEMENTS;
    return 0;
}
'''
    if args.steps>1:
        firmware=firmware.replace('int status=t3p_run(inputs,outputs,&workspace,&be);',
            'int status=0;for(unsigned step=0;step<'+str(args.steps)+';step++){\n'
            'status=t3p_run(inputs,outputs,&workspace,&be);if(status)break;memcpy(state,result,sizeof(state));}\n')
    if args.profile:
        firmware=firmware.replace('int main(void){', '''static uint32_t tpu_cycles,calls;
static uint32_t clock_cycles(void){return *(volatile uint32_t *)(uintptr_t)0x20002008U;}
static int timed_gemm(void *user,const int8_t *a,const int8_t *b,int32_t *c,uint32_t m,uint32_t k,uint32_t n){
 uint32_t start=clock_cycles();int status=tiny3tpu_mmio_qgemm(user,a,b,c,m,k,n);
 tpu_cycles+=clock_cycles()-start;calls++;return status;
}
int main(void){''')
        firmware=firmware.replace('be={&io,tiny3tpu_mmio_qgemm}','be={&io,timed_gemm}')
        firmware=firmware.replace('    int status=', '    uint32_t start=clock_cycles();int status=')
        firmware=firmware.replace('    if(status)return 10-status;',
            '    uint32_t total=clock_cycles()-start;\n    if(status)return 10-status;')
        marker='*(volatile uint32_t *)(uintptr_t)0x20002004U=T3P_OUTPUT_0_ELEMENTS;'
        firmware=firmware.replace(marker,'''*(volatile uint32_t *)(uintptr_t)0x20002004U=total;
    *(volatile uint32_t *)(uintptr_t)0x20002004U=tpu_cycles;
    *(volatile uint32_t *)(uintptr_t)0x20002004U=calls;\n    '''+marker)
    (out/'firmware.c').write_text(firmware)
    harness=r'''
#include "Vvexriscv_tpu_soc.h"
#include <iostream>
int main(int argc,char **argv){
    Verilated::commandArgs(argc,argv);
    Vvexriscv_tpu_soc d;
    d.rst=1;d.ready_to_run=0;d.uart_rx=1;d.ext_req_ready=0;
    d.ext_resp_valid=0;d.ext_resp_rdata=0;d.ext_resp_error=0;
    unsigned reports=0;
    for(unsigned cycle=0;cycle<150000000;cycle++) {
        if(cycle==20){d.rst=0;d.ready_to_run=1;}
        d.clk=0;d.eval();d.clk=1;d.eval();
        if(d.fault||d.ext_req_valid){std::cerr<<"fault or external memory access\n";return 2;}
        if(d.report_valid)reports=d.report_data;
        if(d.exit_valid){
            std::cout<<"CPU exit="<<d.exit_code<<" outputs="<<reports<<" cycles="<<cycle<<" no external memory\n";
            return d.exit_code||!reports?3:0;
        }
    }
    std::cerr<<"timeout\n";return 4;
}
'''
    if args.profile:
        harness=harness.replace('if(d.report_valid)reports=d.report_data;',
            'if(d.report_valid){reports=d.report_data;std::cout<<"measurement="<<reports<<"\\n";}')
    top='rocket_tpu_soc' if args.cpu=='rocket' else 'vexriscv_tpu_soc'
    harness=harness.replace('vexriscv_tpu_soc',top)
    (out/'check.cpp').write_text(harness)
    def run(command,name):
        with (out/f'{name}.log').open('w') as log:
            result=subprocess.run([str(c) for c in command],stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError((out/f'{name}.log').read_text()[-10000:])
    cpu_flags=(['-march=rv64imafdc_zicsr_zifencei','-mabi=lp64d','-mcmodel=medany'] if args.cpu=='rocket'
               else ['-march=rv32im_zicsr_zifencei','-mabi=ilp32'])
    startup=ROOT/('hardware/kc705_rocket/start.S' if args.cpu=='rocket' else 'hardware/synapse32/start.S')
    run(['riscv64-unknown-elf-gcc',*cpu_flags,'-Os',
         '-ffreestanding','-fno-builtin','-nostdlib','-ffp-contract=off','-msmall-data-limit=0',
         '-ffunction-sections','-fdata-sections','-Wall','-Wextra','-Werror','-I'+str(ROOT/'include'),
         '-I'+str(out),'-Wl,--no-relax,--gc-sections','-T'+str(ROOT/'hardware/synapse32/bringup.ld'),
         startup,out/'firmware.c',ROOT/'src/mmio_backend.c',
         ROOT/'src/axis_mailbox.c','-lgcc','-o',out/'firmware.elf'],'firmware')
    run(['riscv64-unknown-elf-size',out/'firmware.elf'],'size')
    run(['riscv64-unknown-elf-objcopy','-O','verilog','--verilog-data-width=4',
         '--change-addresses=-0x80000000',out/'firmware.elf',out/'firmware.hex'],'image')
    uart=args.synapse32_dir.resolve()
    rtl=[ROOT/'hardware/kc705_vexriscv/vexriscv_tpu_soc.sv',ROOT/'third_party/vexriscv/VexRiscv_Lite.v',uart/'rtl/core_modules/uart.v']
    if args.cpu=='rocket':
        rtl=[ROOT/'hardware/kc705_rocket'/n for n in ('rocket_tpu_soc.sv','rocket_wb.sv','axi64_to_wb32.sv')]
        rtl += [ROOT/'third_party/rocket'/n for n in (
            'freechips.rocketchip.system.LitexConfig_linux_1_1.v',
            'freechips.rocketchip.system.LitexConfig_linux_1_1.behav_srams.v',
            'plusarg_reader.v','AsyncResetReg.v','EICG_wrapper.v')]
        rtl += [uart/'rtl/core_modules/uart.v']
    if args.cordic:rtl += [ROOT/'hardware/math'/n for n in ('tiny3tpu_cordic_exp.sv','tiny3tpu_cordic_mmio.sv')]
    rtl += [ROOT/'multi-core'/n for n in ('synapse32_tpu_peripheral.sv','synapse32_axis_mailbox.sv','tiny3tpu_axis.sv',
            'tiny3tpu_axis_bridge.sv','tiny3tpu_axi.sv','top.v','tpu_core_wrapper.sv')]
    rtl += [ROOT/'systolic_array/rtl'/n for n in ('NxN_systolic_array.v','pe.v')]
    run(['verilator','--cc','--exe','--build','-j','2','-Wno-fatal','-DPRINTF_COND=0','--top-module',top,
         '--Mdir',out/'obj',*(['-GENABLE_CORDIC=1'] if args.cordic else []),f'-GBOOT_HEX="{out}/firmware.hex"','-I'+str(uart/'rtl/include'),*rtl,out/'check.cpp'],'build')
    run([out/('obj/V'+top)],'run')
    if args.profile:
        values=[int(line.split('=')[1]) for line in (out/'run.log').read_text().splitlines() if line.startswith('measurement=')]
        if len(values)!=4:raise RuntimeError('Missing profiling reports')
        (out/'profile.json').write_text(json.dumps(dict(total_cycles=values[0],tpu_callback_cycles=values[1],
            cpu_and_conversion_cycles=values[0]-values[1],backend_calls=values[2],verified_words=values[3],
            clock_hz=100000000,cpu=args.cpu,steps=args.steps,
            scope='instrumented full CPU+TPU RTL; state remains on board between steps'),indent=2)+'\n')
    print((out/'size.log').read_text(),end='')
    print((out/'run.log').read_text(),end='')


if __name__=='__main__':main()
