#!/usr/bin/env python3
"""Compare CPU, automatic placement and TPU using the complete VexRiscv RTL.

Every variant verifies all output bits against independently executed native C.
This measures compute in simulation. UART numbers are wire lower bounds; use
the physical viewer's roundtrip_ms/acquisition_fps for measured end-to-end speed.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources(uart_source):
    paths=[]
    for directory in ('tools/program','src','include','multi-core','systolic_array/rtl',
                      'hardware/kc705_vexriscv','hardware/math','third_party/vexriscv'):
        paths.extend(p for p in (ROOT/directory).rglob('*')
                     if p.suffix in ('.py','.c','.h','.sv','.v'))
    paths += [ROOT/'tests/test_stablehlo_soc.py',ROOT/'tests/test_stablehlo_compiler.py',
              ROOT/'hardware/synapse32/start.S',ROOT/'hardware/synapse32/bringup.ld']
    result={str(p.relative_to(ROOT)):sha(p) for p in sorted(paths)}
    for path in sorted(uart_source.rglob('*')):
        if path.suffix in ('.v','.vh'):result[str(path.resolve())]=sha(path)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifact',type=Path,required=True)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--tpu-transport',choices=('mailbox','direct'),default='mailbox')
    parser.add_argument('--optimization',choices=('Os','O2','O3'),default='O2')
    parser.add_argument('--cordic',action='store_true')
    parser.add_argument('--no-fusion',action='store_true')
    parser.add_argument('--compare-generic',action='store_true',
                        help='Also profile forced TPU placement without fixed-shape kernels')
    parser.add_argument('--steps',type=int,default=1)
    parser.add_argument('--baud',type=int,default=921600)
    parser.add_argument('--synapse32-dir',type=Path,default=ROOT.parent/'synapse32')
    args=parser.parse_args()
    if args.steps<1 or args.baud<1:parser.error('steps and baud must be positive')
    for path in (args.artifact,args.input):
        if not path.is_file():parser.error(f'Missing fixture: {path}')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    uart_source=args.synapse32_dir.resolve()/'rtl'
    if not (uart_source/'core_modules/uart.v').is_file():parser.error('Missing Synapse32 UART RTL')
    initial=sources(uart_source)
    records={};expected_hash=None
    policies = ('cpu','auto','tpu','tpu-generic') if args.compare_generic else ('cpu','auto','tpu')
    for policy in policies:
        case=out/policy
        command=[sys.executable,ROOT/'tests/test_stablehlo_soc.py','--profile','--no-affine',
                 '--artifact',args.artifact.resolve(),'--input',args.input.resolve(),
                 '--out',case,'--gemm-policy','tpu' if policy=='tpu-generic' else policy,'--optimization',args.optimization,
                 '--tpu-transport',args.tpu_transport,'--steps',str(args.steps),
                 '--synapse32-dir',args.synapse32_dir.resolve()]
        if args.cordic:command.append('--cordic')
        if args.no_fusion:command.append('--no-fusion')
        if policy=='tpu-generic':command.append('--no-specialize-matmuls')
        with (out/(policy+'.log')).open('w') as log:
            result=subprocess.run(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError(f'{policy} failed; see {out/(policy+".log")}')
        if sources(uart_source)!=initial:raise RuntimeError('Source changed during profiling; rerun for a consistent comparison')
        reference=sha(case/'fixture.h')
        if expected_hash is not None and expected_hash!=reference:
            raise RuntimeError('Placement variants changed the input or native reference bits')
        expected_hash=reference
        record=json.loads((case/'profile.json').read_text())
        record['compute_ms']=record['total_cycles']*1000/record['clock_hz']
        record['firmware_sha256']=sha(case/'firmware.elf')
        record['firmware_size']= (case/'size.log').read_text().strip()
        record['command']=list(map(str,command))
        records[policy]=record
        print(f"{policy}: {record['compute_ms']:.5f} ms, {record['backend_calls']} TPU calls, "
              f"{record['verified_words']} exact output words",flush=True)
    words=records['auto']['verified_words']
    response_bytes=28+words*4
    report=dict(schema='tiny3tpu-end-to-end-profile-v1',scope=__doc__.strip(),
                toolchain={tool:subprocess.check_output([tool,'--version'],text=True).splitlines()[0]
                           for tool in ('riscv64-unknown-elf-gcc','verilator')},
                artifact_sha256=sha(args.artifact),input_sha256=sha(args.input),
                reference_sha256=expected_hash,source_sha256=initial,variants=records,
                best_compute_policy=min(records,key=lambda p:records[p]['total_cycles']),
                uart=dict(baud=args.baud,format='8N1; IFQ1/IFR1 float32',request_bytes=16,
                          response_bytes=response_bytes,
                          wire_min_ms=(16+response_bytes)*10/args.baud*1000),
                auto_speedup_vs_forced_tpu=records['tpu']['total_cycles']/records['auto']['total_cycles'])
    (out/'comparison.json').write_text(json.dumps(report,indent=2)+'\n')
    print(out/'comparison.json')


if __name__=='__main__':main()
