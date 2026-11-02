#!/usr/bin/env python3
"""Verify production Ethernet firmware in the real CPU/TPU/packet-buffer RTL.

By default measurements stop at the UDP stream boundary. --with-mac includes
two actual LiteEth MAC/ARP/IPv4/UDP nodes connected over digital GMII, with
independent 100/125 MHz clocks. Neither mode models analog PHY or host OS latency.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sidequests.showcase.build_support import load_expected_modes, native_reference
from sidequests.showcase.udp_transport import encode_chunk
from tools.program import CompileOptions, KC705, KC705_DIRECT


def check_inference(payload, case):
    if len(payload) < 28 or payload[:4] != b'IFR1':
        raise ValueError('Missing inference header')
    sequence, status, cycles, calls, encoded, checksum = struct.unpack_from('<IiIIII', payload, 4)
    compact, count = bool(encoded >> 31), encoded & 0x7fffffff
    if sequence != case['sequence'] or status != case.get('status', 0) or calls != case['calls']:
        raise ValueError('Inference sequence/status/backend count mismatch')
    if count != np.asarray(case['expected']).size:
        raise ValueError('Inference output word count mismatch')
    if compact:
        if len(payload) != 44 + 2*(count-1) or not case.get('compact'):
            raise ValueError('Incorrect compact packet length or mode')
        base = np.frombuffer(payload[32:44], dtype='<i4').astype(np.int64)
        offset = np.frombuffer(payload[44:], dtype='<u2').astype(np.int64).reshape(-1, 3)
        integer = (base + offset).ravel()
        if (integer < -2147483648).any() or (integer > 2147483647).any():
            raise ValueError('Compact coordinate overflow')
        decoded = np.concatenate((np.frombuffer(payload[28:32], dtype='<f4'), integer.astype(np.float32)))
        np.testing.assert_array_equal(decoded[1:].astype(np.float64), integer)
    else:
        if len(payload) != 28 + 4*count:
            raise ValueError('Incorrect raw packet length')
        decoded = np.frombuffer(payload[28:], dtype='<f4')
    bits = decoded.view(np.uint32)
    np.testing.assert_array_equal(bits, np.asarray(case['expected'], dtype=np.float32).ravel().view(np.uint32))
    if (int(np.bitwise_xor.reduce(bits)) if count else 0) != checksum:
        raise ValueError('Checksum mismatch')
    return dict(compute_cycles=cycles, verified_words=count, backend_calls=calls, compact=compact)


def make_cases(board, demo, *, banana_only=False, banana_frames=3, banana_format='raw'):
    if demo == 'cloth':
        manifest = json.loads((board/'application-manifest.json').read_text())
        for name, digest in manifest['sha256'].items():
            if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
                raise ValueError('Cloth manifest mismatch: '+name)
        artifacts = ROOT/'build-cloth/stablehlo'
        initial = np.load(artifacts/'input.npy')
        expected = np.load(board/'physics-first-step-expected.npy')
        camera = json.loads((ROOT/'build-cloth/camera.json').read_text())
        quantized = expected.reshape(30, 6)[:28, :3]*np.float32(8)
        quantized = np.trunc(quantized+np.where(quantized<0, np.float32(-.5), np.float32(.5))).astype(np.int32)
        coordinates = quantized @ np.array(camera['weights'], dtype=np.int32) + np.array(camera['bias'], dtype=np.int32)
        app = [dict(kind='cloth',name='cloth-step-and-snapshot',sequence=100,
                    request=b'CLQ3'+struct.pack('<II',100,1|256|512),expected=expected,
                    coordinates=coordinates,calls=manifest['physics_backend_calls_first_step'])]
    else:
        counts, manifest = load_expected_modes(board, {i:1 for i in range(20)} if demo=='classifier' else {0:2,1:6,2:6,3:1})
        app=[]
        def add(mode, values, calls, **extra):
            seq=100+len(app)
            app.append(dict(kind='inference',name=f'mode-{mode}',sequence=seq,
                            request=b'IFQ1'+struct.pack('<III',seq,mode,1),expected=values,calls=calls,**extra))
        if demo=='classifier':
            for i,row in enumerate(np.load(board/'classifier-expected.npy')):
                add(i,np.concatenate((row,[np.argmax(row)])),counts[i])
            add(20,[],0,status=-1)
        else:
            records={r['mode']:r for r in manifest['modes']}
            if not banana_only:
                for mode in (0,1,2):add(mode,np.load(board/records[mode]['expected_file']),counts[mode])
            options=CompileOptions(target=KC705_DIRECT if manifest['tpu_transport']=='direct' else KC705,
                                   math_mode='freestanding',allow_approximation=True,gemm_policy=manifest['gemm_policy'])
            angle=np.zeros(1,np.float32)
            if banana_only:
                formats=('raw','compact') if banana_format=='both' else (banana_format,)
                modes=[(3 if encoding=='raw' else 0x80000003,encoding,frame+1)
                       for frame in range(banana_frames) for encoding in formats]
            else:modes=[(0x80000003,None,None),(3,None,None)]
            for mode,encoding,frame in modes:
                output,calls,_=native_reference(Path(manifest['artifact_dir'])/'banana/program.mlirbc',options,angle)
                add(mode,output[0],calls,compact=bool(mode>>31))
                if banana_only:
                    words=output[0].size
                    if words<4 or (words-1)%3:
                        raise ValueError('Banana output must contain an angle followed by XYZ coordinates')
                    app[-1].update(name=f'banana-{encoding}-{frame:03d}',requested_format=encoding,
                                   sample_in_format=frame,banana_step=len(app),vertices=(words-1)//3)
                angle=np.array([output[0].ravel()[0]],np.float32)
            if not banana_only:add(99,[],0,status=-1)
    if manifest.get('io_transport')!='udp':raise ValueError('Build firmware with --io-transport udp first')
    cases=[dict(kind='hello',name='startup-handshake',transaction=0,request=b'EHQ1')]
    for size in (16,1268):
        request=b'ECQ1'+bytes(i%256 for i in range(size-4))
        cases.append(dict(kind='echo',name=f'echo-{size}',transaction=1,request=request))
    for i,case in enumerate(app):
        case['transaction']=i+2;cases.append(case)
        # A duplicate must replay the same response without advancing any state.
        cases.append(dict(kind='duplicate',name=case['name']+'-duplicate',
                          transaction=case['transaction'],request=case['request'],duplicate_of=len(cases)-1))
    cases.append(dict(kind='hello',name='reconnect-handshake',transaction=0,request=b'EHQ1',last=len(app)+1))
    cases.append(dict(kind='duplicate',name='replay-after-handshake',transaction=app[-1]['transaction'],
                      request=app[-1]['request'],duplicate_of=3+2*(len(app)-1)))
    return cases,manifest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--board',type=Path,required=True)
    p.add_argument('--demo',choices=('showcase','classifier','cloth'),default='showcase')
    p.add_argument('--banana-only',action='store_true',help='Replace showcase workloads with consecutive banana state updates and duplicate replay checks')
    p.add_argument('--banana-frames',type=int,default=3,help='State updates per requested format in --banana-only mode (default: 3)')
    p.add_argument('--banana-format',choices=('raw','compact','both'),default='raw',
                   help='Banana reply format; both alternates raw and compact on consecutive states')
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--synapse32-dir',type=Path,default=ROOT.parent/'synapse32')
    p.add_argument('--with-mac',action='store_true',help='Run both real LiteEth nodes over GMII around the production CPU')
    p.add_argument('--ethernet-python',type=Path,default=ROOT/'.venv-ddr-compat/bin/python',
                   help='Python environment with the pinned LiteEth/LiteX/Migen generator dependencies')
    a=p.parse_args()
    if a.banana_only and a.demo!='showcase':p.error('--banana-only requires --demo showcase')
    if a.banana_frames<1:p.error('--banana-frames must be positive')
    if not a.banana_only and (a.banana_frames!=3 or a.banana_format!='raw'):
        p.error('--banana-frames and --banana-format require --banana-only')
    board=a.board.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    cases,manifest=make_cases(board,a.demo,banana_only=a.banana_only,
                              banana_frames=a.banana_frames,banana_format=a.banana_format)
    packets=[encode_chunk(c['transaction'],len(c['request']),0,c['request']) for c in cases]
    (out/'requests.h').write_text('static const std::vector<std::vector<uint8_t>> requests={'+
        ','.join('{'+','.join(map(str,b))+'}' for b in packets)+'};\n')
    harness=r'''
#include "Vvexriscv_udp_test_top.h"
#include <cstdint>
#include <iostream>
#include <iomanip>
#include <vector>
#include "requests.h"
static uint32_t word(const std::vector<uint8_t>& v,unsigned i){return v.at(i)|uint32_t(v.at(i+1))<<8|uint32_t(v.at(i+2))<<16|uint32_t(v.at(i+3))<<24;}
int main(int argc,char**argv){
 Verilated::commandArgs(argc,argv);Vvexriscv_udp_test_top d;
 d.clk=0;d.eth_clk=0;
 unsigned frame=0,start=WITH_MAC?20000:2000,position=0,total=0,have=0,datagrams=0;
 unsigned host_octets=0,board_octets=0,host_frames=0,board_frames=0;
 bool previous_host=false,previous_board=false;
 std::vector<uint8_t> packet,response,present;
#if WITH_MAC
 // One-nanosecond resolution preserves the independent 10 ns and 8 ns periods.
 // Sys rising edges occur at 5+10n ns, Ethernet at 4+8n ns.
 for(uint64_t ns=0;ns<1800000000ULL;ns++){
  unsigned cycle=ns/10;d.eth_clk=(ns/4)&1U;d.rst=ns<200;
  if(ns%10==0){
#else
 for(unsigned cycle=0;cycle<180000000;cycle++){
#endif
  d.clk=0;d.rst=cycle<20;d.rx_error=0;
  // Five 32-bit beats per 16 clocks gives a 125 MB/s payload upper bound.
  bool slot=(cycle%16)%3==0 && cycle%16<13;
  d.tx_ready=slot;d.rx_valid=cycle>=start && position<requests[frame].size() && slot;
  d.rx_ip_address=WITH_MAC?0xc0a80132:0xc0a80164;d.rx_src_port=WITH_MAC?9001:9002;d.rx_dst_port=9001;
  d.rx_length=requests[frame].size();d.rx_data=0;
  for(unsigned i=0;i<4 && position+i<requests[frame].size();i++)d.rx_data|=uint32_t(requests[frame][position+i])<<(8*i);
  d.rx_last=position+4>=requests[frame].size();
  d.rx_last_be=d.rx_last ? 1U<<((requests[frame].size()-1)%4):0;
#if WITH_MAC
  }
  d.eval();
  if(ns%8==4&&!d.rst){
   if(d.host_gmii_tx_en){host_octets++;if(!previous_host)host_frames++;}
   if(d.board_gmii_tx_en){board_octets++;if(!previous_board)board_frames++;}
   previous_host=d.host_gmii_tx_en;previous_board=d.board_gmii_tx_en;
  }
  if(ns%10!=5)continue;
#else
  d.eval();
#endif
  bool rx=d.rx_valid&&d.rx_ready,tx=d.tx_valid&&d.tx_ready,last=d.tx_last;
  uint32_t data=d.tx_data;unsigned be=d.tx_last_be,len=d.tx_length;
  if(tx && (d.tx_ip_address!=(WITH_MAC?0xc0a80132:0xc0a80164)||d.tx_src_port!=9001||d.tx_dst_port!=(WITH_MAC?9001:9002)||d.tx_error))return 2;
  d.clk=1;d.eval();if(d.fault||d.exit_valid){std::cerr<<"CPU fault/exit "<<d.exit_code<<"\n";return 3;}
  if(d.board_crc_errors||d.host_crc_errors||d.board_preamble_errors||d.host_preamble_errors){std::cerr<<"Unexpected MAC errors\n";return 10;}
  if(rx)position+=4;
  if(!tx)continue;
  unsigned n=last?(be==1?1:be==2?2:be==4?3:be==8?4:0):4;
  if(!n)return 4;for(unsigned i=0;i<n;i++)packet.push_back(data>>(8*i));
  if(!last)continue;
  if(packet.size()!=len||len<21||len>1420||word(packet,0)!=0x31553354U||word(packet,4)!=word(requests[frame],4))return 5;
  unsigned size=word(packet,8),offset=word(packet,12),bytes=word(packet,16);
  if(bytes+20!=packet.size()||!size||size>4096||offset+bytes>size)return 6;
  if(!total){total=size;response.resize(total);present.assign(total,0);}
  if(size!=total)return 7;
  for(unsigned i=0;i<bytes;i++){
   if(present[offset+i]&&response[offset+i]!=packet[20+i])return 8;
   if(!present[offset+i])have++;
   response[offset+i]=packet[20+i];present[offset+i]=1;
  }
  packet.clear();datagrams++;
  if(have!=total)continue;
  std::cout<<"{\"frame\":"<<frame<<",\"roundtrip_cycles\":"<<cycle-start<<",\"datagrams\":"<<datagrams
           <<",\"host_gmii_octets\":"<<host_octets<<",\"board_gmii_octets\":"<<board_octets
           <<",\"host_gmii_frames\":"<<host_frames<<",\"board_gmii_frames\":"<<board_frames<<",\"response_hex\":\"";
  for(auto b:response)std::cout<<std::hex<<std::setw(2)<<std::setfill('0')<<unsigned(b);
  std::cout<<std::dec<<"\"}\n"<<std::flush;
  if(++frame==requests.size())return 0;
  start=cycle+200;position=0;total=0;have=0;datagrams=0;
  host_octets=board_octets=host_frames=board_frames=0;
 }
 std::cerr<<"Timeout frame="<<frame<<" bytes="<<have<<"\n";return 9;
}
'''
    (out/'check.cpp').write_text(f'#define WITH_MAC {int(a.with_mac)}\n'+harness)
    uart=a.synapse32_dir.resolve()
    rtl=[ROOT/'tests/vexriscv_udp_test_top.sv',ROOT/'hardware/kc705_vexriscv/tiny3tpu_udp_peripheral.sv',
         ROOT/'hardware/kc705_vexriscv/vexriscv_tpu_soc.sv',ROOT/'third_party/vexriscv/VexRiscv_Lite.v',uart/'rtl/core_modules/uart.v']
    rtl += [ROOT/'hardware/math'/n for n in ('tiny3tpu_cordic_exp.sv','tiny3tpu_cordic_mmio.sv')]
    rtl += [ROOT/'multi-core'/n for n in ('synapse32_tpu_peripheral.sv','synapse32_axis_mailbox.sv','tiny3tpu_axis.sv','tiny3tpu_axis_bridge.sv','tiny3tpu_axi.sv','top.v','tpu_core_wrapper.sv','tiny3tpu_direct_peripheral.sv')]
    rtl += [ROOT/'systolic_array/rtl'/n for n in ('NxN_systolic_array.v','pe.v')]
    def run(cmd,name):
        with (out/(name+'.log')).open('w') as log:
            result=subprocess.run(list(map(str,cmd)),stdout=log,stderr=subprocess.STDOUT,cwd=ROOT)
        if result.returncode:raise RuntimeError((out/(name+'.log')).read_text()[-6000:])
    network_manifest=None
    if a.with_mac:
        # Preserve the virtual environment's interpreter symlink: resolving it
        # to the system Python binary would discard its installed packages.
        run([a.ethernet_python.absolute(),ROOT/'hardware/kc705_ethernet/generate.py',
             '--simulation','--out',out/'liteeth'],'generate-network')
        rtl.append(out/'liteeth/kc705_liteeth_udp.v')
        network_manifest=json.loads((out/'liteeth/liteeth-manifest.json').read_text())
    source_paths=rtl+[board/'firmware.elf',board/'firmware.hex',out/'check.cpp',out/'requests.h',Path(__file__).resolve()]
    if a.with_mac:source_paths += [ROOT/'hardware/kc705_ethernet/generate.py',out/'liteeth/liteeth-manifest.json']
    source_hashes={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}
    run(['verilator','--cc','--exe','--build','-j','2','-Wno-fatal','--top-module','vexriscv_udp_test_top','--Mdir',out/'obj',
         f'-GBOOT_HEX="{board}/firmware.hex"',f'-GDIRECT_TPU={int(manifest["tpu_transport"]=="direct")}',
         f'-GWITH_MAC={int(a.with_mac)}',
         '-I'+str(uart/'rtl/include'),*rtl,out/'check.cpp'],'build')
    run([out/'obj/Vvexriscv_udp_test_top'],'run')
    rows=[json.loads(line) for line in (out/'run.log').read_text().splitlines() if line.startswith('{')]
    if len(rows)!=len(cases):raise ValueError('Missing simulation responses')
    for row,case in zip(rows,cases):
        payload=bytes.fromhex(row['response_hex']);kind=case['kind']
        row.update(name=case['name'],kind=kind,roundtrip_us=row['roundtrip_cycles']/100.,
                   request_bytes=len(case['request']),response_bytes=len(payload),
                   udp_request_bytes=len(case['request'])+20,
                   udp_response_bytes=len(payload)+20*row['datagrams'])
        if kind=='echo':
            assert payload==b'ECR1'+case['request'][4:]
        elif kind=='hello':
            assert len(payload)==20 and payload[:4]==b'EHR1'
            version,owner,last,flags=struct.unpack('<4I',payload[4:]);assert version==1
            if 'last' in case:assert owner==1 and last==case['last'] and flags&1
            else:assert owner==0 and flags==0
        elif kind=='duplicate':
            assert row['response_hex']==rows[case['duplicate_of']]['response_hex'],'Duplicate request advanced state or changed reply'
        elif kind=='inference':
            row.update(check_inference(payload,case))
            if 'requested_format' in case:
                row.update({key:case[key] for key in ('requested_format','sample_in_format','banana_step','vertices')})
                row['compact_fallback']=case['requested_format']=='compact' and not row['compact']
        else:
            assert payload[:4]==b'CLR3' and len(payload)==36+84*4+180*4
            seq,status,transform,count,checksum,physics,steps,calls=struct.unpack_from('<8I',payload,4)
            assert seq==case['sequence'] and status==0 and count==28 and steps==1 and calls==case['calls']
            coords=np.frombuffer(payload[36:372],dtype='<i4')
            np.testing.assert_array_equal(coords,case['coordinates'].ravel())
            assert int(np.bitwise_xor.reduce(coords.view(np.uint32)))==checksum
            np.testing.assert_array_equal(np.frombuffer(payload[372:],dtype='<u4'),case['expected'].ravel().view(np.uint32))
            row.update(compute_cycles=physics+transform,verified_words=264,backend_calls=calls)
        if 'compute_cycles' in row:row['outside_compute_us']=(row['roundtrip_cycles']-row['compute_cycles'])/100.
    if a.with_mac:
        # The first request starts with empty ARP tables; subsequent echoes use
        # learned entries. Every command traverses GMII in both directions.
        assert rows[0]['host_gmii_frames']>1 and rows[0]['board_gmii_frames']>1,'ARP exchange missing'
        assert all(r['host_gmii_frames']>=1 and r['board_gmii_frames']>=r['datagrams'] for r in rows)
    if source_hashes!={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}:
        raise ValueError('A source changed during the simulation; rerun to produce consistent evidence')
    report=dict(passed=True,requests=len(rows),clock_hz=100000000,with_mac=a.with_mac,
                banana_only=a.banana_only,banana_frames=a.banana_frames if a.banana_only else None,
                banana_format=a.banana_format if a.banana_only else None,
                scope=('Production CPU/TPU firmware plus two actual LiteEth MAC/ARP/IPv4/UDP nodes over digital GMII; '
                       '100 MHz system and 125 MHz Ethernet clocks simulated at 1 ns resolution; '
                       'excludes analog PHY, cable, OS and Python socket latency' if a.with_mac else
                       'Production CPU/TPU/packet-buffer RTL at the UDP stream boundary; excludes MAC, PHY, ARP and host latency'),
                gmii_clock_hz=125000000 if a.with_mac else None,time_resolution_ns=1 if a.with_mac else 10,
                startup_delay_cycles=20000 if a.with_mac else 2000,
                host_endpoint='five 32-bit beats per 16 system clocks; one outstanding application request',
                network_manifest=network_manifest,
                mac_errors=dict(board_crc=0,host_crc=0,board_preamble=0,host_preamble=0) if a.with_mac else None,
                sha256=source_hashes,
                firmware_sha256=hashlib.sha256((board/'firmware.elf').read_bytes()).hexdigest(),checks=rows)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    for row in rows:print({k:v for k,v in row.items() if k!='response_hex'})


if __name__=='__main__':main()
