#!/usr/bin/env python3
"""Verify production firmware packets and throughput through CPU/UART/TPU RTL."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from sidequests.showcase.build_support import load_expected_modes, native_reference
from tools.program import CompileOptions, KC705, KC705_DIRECT


def simulate(board, out, cases, manifest, transport=None):
    """Check complete raw/compact packets; all arithmetic executes in the SoC."""
    out.mkdir(parents=True, exist_ok=True)
    manifest_transport = manifest.get('tpu_transport', 'mailbox')
    transport = transport or manifest_transport
    if 'tpu_transport' in manifest and transport != manifest_transport:
        raise ValueError('Requested RTL transport disagrees with firmware build manifest')
    expected = [np.ascontiguousarray(case['expected'], dtype=np.float32).ravel().view(np.uint32) for case in cases]
    maximum = max(map(len, expected))
    array = lambda rows: '{' + ','.join('{' + ','.join(str(int(v)) + 'U' for v in row) + '}' for row in rows) + '}'
    (out / 'expected.h').write_text(
        f'static const uint32_t expected[{len(cases)}][{maximum}]=' + array(expected) + ';\n' +
        f'static const uint32_t requests[{len(cases)}][5]=' + array(
            [(case['request_mode'], case.get('repeats', 1), len(row),
              case['expected_calls'], case.get('status', 0) & 0xffffffff) for case, row in zip(cases, expected)]) + ';\n' +
        f'static const unsigned frame_count={len(cases)};\n')
    (out / 'check.cpp').write_text(r'''
#include "Vvexriscv_tpu_soc.h"
#include <cstdint>
#include <cstring>
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
 auto prepare=[&](){request={'I','F','Q','1'};append(request,123+frame);append(request,requests[frame][0]);append(request,requests[frame][1]);};prepare();
 for(unsigned cycle=0;cycle<150000000;cycle++){
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
  if(response==size_t(-1)||received.size()<response+28)continue;
  unsigned mode=requests[frame][0]&0x7fffffffU,count=requests[frame][2];
  uint32_t encoded_count=word(received,response+20);bool compact=(encoded_count>>31)!=0;
  if(word(received,response+4)!=123+frame||word(received,response+8)!=requests[frame][4]||word(received,response+16)!=requests[frame][3]||(encoded_count&0x7fffffffU)!=count){std::cerr<<"header mismatch frame="<<frame<<"\n";return 3;}
  bool requested_compact=(requests[frame][0]>>31)!=0;
  if(compact&&(!requested_compact||mode!=3||count<4||(count-1)%3))return 7;
  if(requested_compact&&mode==3&&!compact){std::cerr<<"fixture should use compact encoding\n";return 8;}
  unsigned bytes=28+(compact?16+2*(count-1):count*4);
  if(received.size()<response+bytes)continue;
  uint32_t checksum=0;
  for(unsigned i=0;i<count;i++){
   uint32_t got;
   if(!compact||i==0)got=word(received,response+28+i*4);
   else {
    unsigned axis=(i-1)%3,offset_pos=response+44+2*(i-1);
    int32_t base=(int32_t)word(received,response+32+4*axis);
    uint32_t offset=received[offset_pos]|uint32_t(received[offset_pos+1])<<8;
    int64_t integer=int64_t(base)+offset;if(integer<INT32_MIN||integer>INT32_MAX)return 9;
    float decoded=(float)integer;std::memcpy(&got,&decoded,4);
   }
   if(got!=expected[frame][i]){std::cerr<<"mismatch frame="<<frame<<" word="<<i<<" got="<<got<<" expected="<<expected[frame][i]<<"\n";return 4;}checksum^=got;
  }
  if(checksum!=word(received,response+24))return 5;
  std::cout<<"{\"frame\":"<<frame<<",\"mode\":"<<mode<<",\"repeats\":"<<requests[frame][1]<<",\"words\":"<<count<<",\"backend_calls\":"<<word(received,response+16)<<",\"compute_cycles\":"<<word(received,response+12)<<",\"roundtrip_cycles\":"<<cycle-send_start<<",\"response_bytes\":"<<bytes<<",\"compact\":"<<(compact?"true":"false")<<"}\n"<<std::flush;
  if(++frame==frame_count)return 0;
  received.clear();response=size_t(-1);prepare();send_start=cycle+2*baud;
 }
 std::cerr<<"timeout bytes="<<received.size()<<"\n";return 6;
}
''')
    uart = ROOT.parent / 'synapse32'
    rtl = [ROOT / 'hardware/kc705_vexriscv/vexriscv_tpu_soc.sv', ROOT / 'third_party/vexriscv/VexRiscv_Lite.v', uart / 'rtl/core_modules/uart.v']
    rtl += [ROOT / 'hardware/math' / name for name in ('tiny3tpu_cordic_exp.sv', 'tiny3tpu_cordic_mmio.sv')]
    rtl += [ROOT / 'multi-core' / name for name in ('synapse32_tpu_peripheral.sv', 'synapse32_axis_mailbox.sv', 'tiny3tpu_axis.sv', 'tiny3tpu_axis_bridge.sv', 'tiny3tpu_axi.sv', 'top.v', 'tpu_core_wrapper.sv', 'tiny3tpu_direct_peripheral.sv')]
    rtl += [ROOT / 'systolic_array/rtl' / name for name in ('NxN_systolic_array.v', 'pe.v')]
    def run(command, name):
        with (out / (name + '.log')).open('w') as log:
            result = subprocess.run(list(map(str, command)), stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError((out / (name + '.log')).read_text()[-6000:])
    run(['verilator', '--cc', '--exe', '--build', '-j', '2', '-Wno-fatal', '--top-module', 'vexriscv_tpu_soc', '--Mdir', out / 'obj',
         f'-GBOOT_HEX="{board}/firmware.hex"', '-GENABLE_CORDIC=1', f'-GDIRECT_TPU={int(transport == "direct")}',
         '-I' + str(uart / 'rtl/include'), *rtl, out / 'check.cpp'], 'build')
    run([out / 'obj/Vvexriscv_tpu_soc'], 'run')
    rows = [json.loads(line) for line in (out / 'run.log').read_text().splitlines() if line.startswith('{')]
    if len(rows) != len(cases):
        raise ValueError('UART simulator did not report every request')
    report = {'passed': True, 'requests': len(cases), 'clock_hz': 100000000, 'uart_cycles_per_bit': 109,
              'tpu_transport': transport, 'gemm_policy': manifest.get('gemm_policy', 'legacy-tpu'),
              'checks': rows, 'scope': 'Actual firmware, CPU, UART, TPU and CORDIC RTL; exact output words and backend counts. Includes UART round trip; no physical board or host-render timing.'}
    (out / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print((out / 'run.log').read_text(), end='')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--board', type=Path, default=ROOT / 'build-showcase/board')
    parser.add_argument('--out', type=Path, default=ROOT / 'build-showcase/uart-rtl')
    parser.add_argument('--tpu-transport', choices=('mailbox', 'direct'), help='Defaults to firmware manifest transport')
    args = parser.parse_args(); board = args.board.resolve()
    counts, manifest = load_expected_modes(board, {0: 2, 1: 6, 2: 6, 3: 1})
    artifacts = Path(manifest.get('artifact_dir', ROOT / 'build-showcase'))
    modes = {row['mode']: row for row in manifest.get('modes', [])}
    rows = []
    for mode, name in enumerate(('quantized_mlp', 'attention_block', 'attention_block')):
        path = board / modes[mode]['expected_file'] if mode in modes else artifacts / name / 'expected-native.npy'
        rows.append(np.load(path).ravel())
    cases = [{'request_mode': mode, 'expected': rows[mode], 'expected_calls': counts[mode]} for mode in (0, 1, 2, 0, 1, 2)]
    options = CompileOptions(target=KC705_DIRECT if manifest.get('tpu_transport') == 'direct' else KC705,
                             math_mode='freestanding', allow_approximation=True,
                             specialize_matmuls=manifest.get('specialize_matmuls',True),
                             gemm_policy=manifest.get('gemm_policy', 'tpu'))
    angle = np.zeros(1, np.float32)
    for request_mode in (3, 0x80000003) if 'compact-coordinates-v1' in manifest.get('capabilities', []) else (3,):
        outputs, calls, _ = native_reference(artifacts / 'banana/program.mlirbc', options, angle)
        if calls != counts[3]:
            raise ValueError('Banana native reference count differs from firmware manifest')
        cases.append({'request_mode': request_mode, 'expected': outputs[0], 'expected_calls': calls})
        angle = np.array([outputs[0].ravel()[0]], np.float32)
    cases += [{'request_mode': 0, 'repeats': 3, 'expected': rows[0], 'expected_calls': 3 * counts[0]},
              {'request_mode': 99, 'expected': np.empty(0, np.float32), 'expected_calls': 0, 'status': -1}]
    simulate(board, args.out.resolve(), cases, manifest, args.tpu_transport)


if __name__ == '__main__':
    main()
