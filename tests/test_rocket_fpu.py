#!/usr/bin/env python3
"""Check Rocket FP32/FP64 operations against independent binary32/64 vectors."""
import argparse
from pathlib import Path
import subprocess
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from kc705_rocket_build import rocket_sources


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    rng=np.random.default_rng(273)
    header=[]
    for bits,dtype,uint in [(32,np.float32,np.uint32),(64,np.float64,np.uint64)]:
        finfo=np.finfo(dtype)
        special=np.array([0.,-0.,1.,-1.,2.,-2.,finfo.tiny,-finfo.tiny,finfo.smallest_subnormal,
                          -finfo.smallest_subnormal,finfo.max,-finfo.max,np.inf,-np.inf,np.nan],dtype=dtype)
        # Full-range exponent/mantissa samples, including nonfinite patterns.
        raw=rng.integers(0,np.iinfo(uint).max,49,dtype=uint)
        x=np.concatenate([special,raw.view(dtype)])
        y=np.roll(x,5)
        with np.errstate(all='ignore'):
            values=np.stack([x,y,x+y,x-y,x*y,x/y,np.sqrt(x)],axis=1)
        rows=['{'+','.join(hex(int(v))+('ULL' if bits==64 else 'U') for v in row)+'}' for row in values.view(uint)]
        header.append('static const uint'+str(bits)+'_t cases'+str(bits)+'[][7]={'+','.join(rows)+'};')
    (out/'vectors.h').write_text('\n'.join(header)+'\n')
    (out/'firmware.c').write_text(r'''
#include <stdint.h>
#include "vectors.h"
static int equal32(uint32_t a,uint32_t b){return a==b||((a&0x7fffffffU)>0x7f800000U&&(b&0x7fffffffU)>0x7f800000U);}
static int equal64(uint64_t a,uint64_t b){return a==b||((a&0x7fffffffffffffffULL)>0x7ff0000000000000ULL&&(b&0x7fffffffffffffffULL)>0x7ff0000000000000ULL);}
int main(void){
 for(unsigned i=0;i<64;i++){
  union {uint32_t u;float f;} a={cases32[i][0]},b={cases32[i][1]},r;
  for(unsigned op=0;op<5;op++){
   switch(op){case 0:r.f=a.f+b.f;break;case 1:r.f=a.f-b.f;break;case 2:r.f=a.f*b.f;break;
    case 3:r.f=a.f/b.f;break;default:__asm__ volatile("fsqrt.s %0,%1":"=f"(r.f):"f"(a.f));}
   if(!equal32(r.u,cases32[i][op+2]))return 100+i*5+op;
  }
  union {uint64_t u;double f;} c={cases64[i][0]},d={cases64[i][1]},s;
  for(unsigned op=0;op<5;op++){
   switch(op){case 0:s.f=c.f+d.f;break;case 1:s.f=c.f-d.f;break;case 2:s.f=c.f*d.f;break;
    case 3:s.f=c.f/d.f;break;default:__asm__ volatile("fsqrt.d %0,%1":"=f"(s.f):"f"(c.f));}
   if(!equal64(s.u,cases64[i][op+2]))return 1000+i*5+op;
  }
 }
 *(volatile uint32_t *)(uintptr_t)0x20002004U=640;
 return 0;
}
''')
    (out/'check.cpp').write_text(r'''
#include "Vrocket_tpu_soc.h"
#include <iostream>
int main(int argc,char **argv){
 Verilated::commandArgs(argc,argv);Vrocket_tpu_soc d;
 d.rst=1;d.ready_to_run=0;d.uart_rx=1;d.ext_req_ready=0;
 d.ext_resp_valid=0;d.ext_resp_rdata=0;d.ext_resp_error=0;
 unsigned reports=0;
 for(unsigned cycle=0;cycle<2000000;cycle++){
  if(cycle==20){d.rst=0;d.ready_to_run=1;}
  d.clk=0;d.eval();d.clk=1;d.eval();
  if(d.fault||d.ext_req_valid)return 2;
  if(d.report_valid)reports=d.report_data;
  if(d.exit_valid){std::cout<<"exit="<<d.exit_code<<" verified="<<reports<<" cycles="<<cycle<<"\n";return d.exit_code||reports!=640?3:0;}
 }
 std::cerr<<"timeout\n";return 4;
}
''')
    def run(cmd,name):
        with (out/(name+'.log')).open('w') as log:
            result=subprocess.run(list(map(str,cmd)),stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError((out/(name+'.log')).read_text()[-5000:])
    run(['riscv64-unknown-elf-gcc','-march=rv64imafdc_zicsr_zifencei','-mabi=lp64d','-mcmodel=medany',
         '-Os','-ffreestanding','-fno-builtin','-nostdlib','-ffp-contract=off','-msmall-data-limit=0',
         '-Wl,--no-relax,--gc-sections','-T'+str(ROOT/'hardware/synapse32/bringup.ld'),
         ROOT/'hardware/kc705_rocket/start.S',out/'firmware.c','-lgcc','-o',out/'firmware.elf'],'firmware')
    run(['riscv64-unknown-elf-objcopy','-O','verilog','--verilog-data-width=4',
         '--change-addresses=-0x80000000',out/'firmware.elf',out/'firmware.hex'],'image')
    rtl=rocket_sources()+[ROOT/'hardware/kc705_rocket'/n for n in ('rocket_tpu_soc.sv','rocket_wb.sv','axi64_to_wb32.sv')]
    uart=ROOT.parent/'synapse32'
    rtl += [uart/'rtl/core_modules/uart.v']
    rtl += [ROOT/'multi-core'/n for n in ('synapse32_tpu_peripheral.sv','synapse32_axis_mailbox.sv',
        'tiny3tpu_axis.sv','tiny3tpu_axis_bridge.sv','tiny3tpu_axi.sv','top.v','tpu_core_wrapper.sv')]
    rtl += [ROOT/'systolic_array/rtl'/n for n in ('NxN_systolic_array.v','pe.v')]
    run(['verilator','--cc','--exe','--build','-j','2','-Wno-fatal','-DPRINTF_COND=0','--top-module','rocket_tpu_soc',
         '--Mdir',out/'obj',f'-GBOOT_HEX="{out}/firmware.hex"','-I'+str(uart/'rtl/include'),*rtl,out/'check.cpp'],'build')
    run([out/'obj/Vrocket_tpu_soc'],'run');print((out/'run.log').read_text(),end='')
    print('FP32/FP64 add/sub/mul/div/sqrt: exact finite/zero/inf bits, NaN class checked.')
if __name__=='__main__':main()
