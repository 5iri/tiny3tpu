#!/usr/bin/env python3
"""Verify production inference firmware through the actual CPU/UART/TPU/CORDIC RTL."""
import argparse,json,subprocess
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--board',type=Path,default=ROOT/'build-classifier/board');p.add_argument('--out',type=Path,default=ROOT/'build-classifier/uart-rtl');a=p.parse_args();board=a.board.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 scores=np.load(ROOT/'build-classifier/expected.npy')
 rows=[np.concatenate((row,np.array([np.argmax(row)],np.float32))).view(np.uint32) for row in scores]
 (out/'expected.h').write_text('static const uint32_t expected[20][11]={'+','.join('{'+','.join(str(int(v))+'U' for v in row)+'}' for row in rows)+'};\n')
 (out/'check.cpp').write_text(r'''
#include "Vvexriscv_tpu_soc.h"
#include <cstdint>
#include <iostream>
#include <vector>
#include "expected.h"
static void append(std::vector<uint8_t>& v,uint32_t x){for(unsigned i=0;i<4;i++)v.push_back(x>>(i*8));}
static uint32_t word(const std::vector<uint8_t>& v,unsigned i){return v[i]|uint32_t(v[i+1])<<8|uint32_t(v[i+2])<<16|uint32_t(v[i+3])<<24;}
int main(int argc,char **argv){
 Verilated::commandArgs(argc,argv);Vvexriscv_tpu_soc d;
 d.ext_req_ready=0;d.ext_resp_valid=0;d.ext_resp_rdata=0;d.ext_resp_error=0;
 const unsigned baud=109;unsigned send_start=~0U,frame=0;int rx_bit=-1;unsigned rx_byte=0,sample=0;
 size_t response=size_t(-1);std::vector<uint8_t> request,received;
 auto prepare=[&](){request={'I','F','Q','1'};append(request,123+frame);append(request,frame%20);append(request,1);};prepare();
 for(unsigned cycle=0;cycle<80000000;cycle++){
  d.clk=0;d.rst=cycle<20;d.ready_to_run=cycle>=20;d.uart_rx=1;
  if(cycle>=send_start){unsigned bit=(cycle-send_start)/baud,i=bit/10,within=bit%10;
   if(i<request.size())d.uart_rx=within==0?0:within==9?1:(request[i]>>(within-1))&1;
  }
  d.eval();d.clk=1;d.eval();
  if(d.fault||d.ext_req_valid||d.exit_valid){std::cerr<<"fault/exit "<<d.exit_code<<"\n";return 1;}
  if(rx_bit<0&&!d.uart_tx){rx_bit=0;rx_byte=0;sample=cycle+baud+baud/2;}
  else if(rx_bit>=0&&cycle>=sample){
   if(rx_bit<8){rx_byte|=unsigned(d.uart_tx)<<rx_bit++;sample+=baud;}
   else {if(!d.uart_tx)return 2;received.push_back(rx_byte);rx_bit=-1;
    if(send_start==~0U&&rx_byte=='\n'){send_start=cycle+2*baud;received.clear();}
    if(response==size_t(-1)&&received.size()>=4&&word(received,received.size()-4)==0x31524649U)response=received.size()-4;
   }
  }
  unsigned mode=frame%20,count=11;
  if(response!=size_t(-1)&&received.size()>=response+28+count*4){
   if(word(received,response+4)!=123+frame||word(received,response+8)||word(received,response+16)!=1||word(received,response+20)!=count)return 3;
   uint32_t checksum=0;
   for(unsigned i=0;i<count;i++){uint32_t got=word(received,response+28+i*4);if(got!=expected[mode][i]){std::cerr<<"mismatch frame="<<frame<<" word="<<i<<"\n";return 4;}checksum^=got;}
   if(checksum!=word(received,response+24))return 5;
   std::cout<<"PASS frame="<<frame<<" mode="<<mode<<" words="<<count<<" cycles="<<word(received,response+12)<<"\n"<<std::flush;
   if(++frame==6)return 0;
   received.clear();response=size_t(-1);prepare();send_start=cycle+2*baud;
  }
 }
 std::cerr<<"timeout bytes="<<received.size()<<"\n";return 6;
}
''')
 uart=ROOT.parent/'synapse32';rtl=[ROOT/'hardware/kc705_vexriscv/vexriscv_tpu_soc.sv',ROOT/'third_party/vexriscv/VexRiscv_Lite.v',uart/'rtl/core_modules/uart.v']
 rtl += [ROOT/'hardware/math'/n for n in ('tiny3tpu_cordic_exp.sv','tiny3tpu_cordic_mmio.sv')]
 rtl += [ROOT/'multi-core'/n for n in ('synapse32_tpu_peripheral.sv','synapse32_axis_mailbox.sv','tiny3tpu_axis.sv','tiny3tpu_axis_bridge.sv','tiny3tpu_axi.sv','top.v','tpu_core_wrapper.sv')]
 rtl += [ROOT/'systolic_array/rtl'/n for n in ('NxN_systolic_array.v','pe.v')]
 def run(cmd,name):
  with (out/(name+'.log')).open('w') as log:r=subprocess.run(list(map(str,cmd)),stdout=log,stderr=subprocess.STDOUT)
  if r.returncode:raise RuntimeError((out/(name+'.log')).read_text()[-6000:])
 run(['verilator','--cc','--exe','--build','-j','2','-Wno-fatal','--top-module','vexriscv_tpu_soc','--Mdir',out/'obj',f'-GBOOT_HEX="{board}/firmware.hex"','-GENABLE_CORDIC=1','-I'+str(uart/'rtl/include'),*rtl,out/'check.cpp'],'build')
 run([out/'obj/Vvexriscv_tpu_soc'],'run');print((out/'run.log').read_text())
 (out/'report.json').write_text(json.dumps({'passed':True,'requests':6,'scope':'Trained classifier firmware, UART, VexRiscv and TPU RTL; first six MNIST test examples; not physical timing'},indent=2)+'\n')
if __name__=='__main__':main()
