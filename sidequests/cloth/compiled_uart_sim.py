#!/usr/bin/env python3
"""Verify the actual compiled Rocket firmware's CLQ3/CLR3 UART protocol in RTL."""
import argparse,ctypes,hashlib,json,subprocess,sys
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools'))
from kc705_rocket_build import rocket_sources


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--board',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();board=a.board.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    def run(cmd,name):
        with (out/(name+'.log')).open('w') as log:r=subprocess.run(list(map(str,cmd)),stdout=log,stderr=subprocess.STDOUT)
        if r.returncode:raise RuntimeError((out/(name+'.log')).read_text()[-5000:])
    run(['cc','-shared','-fPIC','-O2','-ffp-contract=off','-I'+str(ROOT/'include'),'-I'+str(board),
         ROOT/'sidequests/cloth/program_check.c','-o',out/'reference.so'],'reference')
    lib=ctypes.CDLL(str(out/'reference.so'));lib.program_advance_float.argtypes=[ctypes.c_void_p,ctypes.c_uint32]
    lib.program_advance_float.restype=ctypes.c_int
    initial=np.load(ROOT/'build-cloth/stablehlo/input.npy');state=initial.copy()
    camera=json.loads((ROOT/'build-cloth/camera.json').read_text());rows=[]
    for steps,reset in [(1,True),(2,False),(0,True)]:
        if reset:state=initial.copy()
        assert lib.program_advance_float(state.ctypes.data,steps)==0
        v=state[:28,:3]*np.float32(8)
        v=np.trunc(v+np.where(v<0,np.float32(-.5),np.float32(.5))).astype(np.int32)
        coords=v@np.array(camera['weights'],np.int32)+np.array(camera['bias'],np.int32)
        rows.append(np.concatenate([coords.ravel().view(np.uint32),state.ravel().view(np.uint32)]))
    clock_hz=json.loads((board/'rocket-inputs.json').read_text())['clock_hz']
    (out/'expected.h').write_text(f'static const unsigned UART_BIT_CYCLES={(clock_hz+460800)//921600};\n'+
        'static const uint32_t expected[3][264]={'+','.join('{'+','.join(str(int(v))+'U' for v in row)+'}' for row in rows)+'};\n')
    (out/'check.cpp').write_text(r'''
#include "Vrocket_tpu_soc.h"
#include <cstdint>
#include <iostream>
#include <vector>
#include "expected.h"
static void append(std::vector<uint8_t>& v,uint32_t x){for(unsigned i=0;i<4;i++)v.push_back(x>>(i*8));}
static uint32_t word(const std::vector<uint8_t>& v,unsigned i){return v[i]|uint32_t(v[i+1])<<8|uint32_t(v[i+2])<<16|uint32_t(v[i+3])<<24;}
int main(int argc,char **argv){
 Verilated::commandArgs(argc,argv);Vrocket_tpu_soc d;
 d.ext_req_ready=0;d.ext_resp_valid=0;d.ext_resp_rdata=0;d.ext_resp_error=0;
 const unsigned baud=UART_BIT_CYCLES;unsigned send_start=~0U,frame=0;int rx_bit=-1;unsigned rx_byte=0,sample=0;
 size_t response=size_t(-1);std::vector<uint8_t> request,received;
 auto prepare=[&](){request={'C','L','Q','3'};append(request,123+frame);append(request,512|(frame==0?257:frame==1?2:256));};
 prepare();
 for(unsigned cycle=0;cycle<10000000;cycle++){
  d.clk=0;d.rst=cycle<20;d.ready_to_run=cycle>=20;d.uart_rx=1;
  if(cycle>=send_start){unsigned bit=(cycle-send_start)/baud,i=bit/10,within=bit%10;
   if(i<request.size())d.uart_rx=within==0?0:within==9?1:(request[i]>>(within-1))&1;
  }
  d.eval();d.clk=1;d.eval();
  if(d.fault||d.ext_req_valid||d.exit_valid){std::cerr<<"fault/exit "<<d.exit_code<<"\n";return 1;}
  if(rx_bit<0&&!d.uart_tx){rx_bit=0;rx_byte=0;sample=cycle+baud+baud/2;}
  else if(rx_bit>=0&&cycle>=sample){
   if(rx_bit<8){rx_byte|=unsigned(d.uart_tx)<<rx_bit++;sample+=baud;}
   else {
    if(!d.uart_tx){std::cerr<<"UART framing error\n";return 2;}
    received.push_back(rx_byte);rx_bit=-1;
    if(send_start==~0U&&rx_byte=='\n'){send_start=cycle+2*baud;received.clear();}
    if(response==size_t(-1)&&received.size()>=4&&word(received,received.size()-4)==0x33524c43U)response=received.size()-4;
   }
  }
  if(response!=size_t(-1)&&received.size()>=response+36+264*4){
   if(word(received,response+4)!=123+frame||word(received,response+8)||word(received,response+16)!=28||
      word(received,response+28)!=(frame==0?1:frame==1?3:0)||word(received,response+32)!=0)return 3;
   uint32_t checksum=0;
   for(unsigned i=0;i<264;i++){uint32_t got=word(received,response+36+i*4);if(got!=expected[frame][i]){
    std::cerr<<"mismatch frame="<<frame<<" word="<<i<<"\n";return 4;}if(i<84)checksum^=got;}
   if(checksum!=word(received,response+20))return 5;
   std::cout<<"PASS frame="<<frame<<" state_words=180 coordinate_words=84 physics_cycles="<<word(received,response+24)
            <<" transform_cycles="<<word(received,response+12)<<"\n"<<std::flush;
   if(++frame==3)return 0;
   received.clear();response=size_t(-1);prepare();send_start=cycle+2*baud;
  }
 }
 std::cerr<<"timeout bytes="<<received.size()<<"\n";return 6;
}
''')
    uart=ROOT.parent/'synapse32'
    rtl=rocket_sources()+[ROOT/'hardware/kc705_rocket'/n for n in ('rocket_tpu_soc.sv','rocket_wb.sv','axi64_to_wb32.sv')]+[uart/'rtl/core_modules/uart.v']
    rtl += [ROOT/'multi-core'/n for n in ('synapse32_tpu_peripheral.sv','synapse32_axis_mailbox.sv','tiny3tpu_axis.sv','tiny3tpu_axis_bridge.sv','tiny3tpu_axi.sv','top.v','tpu_core_wrapper.sv')]
    rtl += [ROOT/'systolic_array/rtl'/n for n in ('NxN_systolic_array.v','pe.v')]
    run(['verilator','--cc','--exe','--build','-j','2','-Wno-fatal','-DPRINTF_COND=0','--top-module','rocket_tpu_soc',
         '--Mdir',out/'obj',f'-GBOOT_HEX="{board}/firmware.hex"','-I'+str(uart/'rtl/include'),*rtl,out/'check.cpp'],'build')
    run([out/'obj/Vrocket_tpu_soc'],'run')
    print((out/'run.log').read_text(),end='')
    report={'passed':True,'frames':3,'state_words_per_frame':180,'coordinate_words_per_frame':84,
            'firmware_sha256':hashlib.sha256((board/'firmware.elf').read_bytes()).hexdigest(),
            'scope':'Actual production Rocket firmware, full UART/CPU/TPU RTL; no physical timing claim'}
    (board/'uart-rtl-check.json').write_text(json.dumps(report,indent=2)+'\n')
if __name__=='__main__':main()
