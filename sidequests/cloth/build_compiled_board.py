#!/usr/bin/env python3
"""Compile StableHLO live firmware; optionally implement Rocket or patch a compatible retained VexRiscv route."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import numpy as np

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from tools.program import compile_stablehlo,CompileOptions,KC705,KC705_ROCKET,KC705_DIRECT

from sidequests.showcase.build_support import memory_report,native_reference

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--artifact-dir',type=Path,default=ROOT/'build-cloth/stablehlo')
    p.add_argument('--base',type=Path,default=ROOT/'build-cloth/transforms-board')
    p.add_argument('--out',type=Path,default=ROOT/'build-cloth/compiled-board')
    p.add_argument('--compile-only',action='store_true',help='Build ELF/hex and reports without FPGA tools or a retained route')
    p.add_argument('--optimization',choices=('Os','O2','O3'),default='O2')
    p.add_argument('--gemm-policy',choices=('auto','cpu','tpu'),default='auto')
    p.add_argument('--tpu-transport',choices=('mailbox','direct'),default='mailbox')
    p.add_argument('--affine-policy',choices=('auto','force'),default='auto')
    p.add_argument('--no-fusion',action='store_true')
    p.add_argument('--cpu',choices=('vexriscv','rocket'),default='vexriscv')
    p.add_argument('--clock-mhz',type=int,choices=(25,50,100),help='Rocket defaults to 25 MHz; VexRiscv requires 100 MHz')
    p.add_argument('--no-lutram',action='store_true',help='Rocket diagnostic: implement small memories with registers')
    p.add_argument('--implementation-stage',choices=('synth','route'),default='route')
    p.add_argument('--db-root',type=Path,default=ROOT/'build-banana/nextpnr-source/xilinx/external/prjxray-db/kintex7')
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    clock_mhz=a.clock_mhz if a.clock_mhz is not None else (25 if a.cpu=='rocket' else 100)
    if a.cpu=='vexriscv' and clock_mhz!=100:p.error('The retained VexRiscv route requires 100 MHz')
    if a.no_lutram and a.cpu!='rocket':p.error('--no-lutram requires --cpu rocket')
    if a.cpu=='rocket' and a.tpu_transport!='mailbox':p.error('direct TPU requires VexRiscv')
    if a.cpu=='vexriscv' and not a.compile_only:
        if out==a.base.resolve():p.error('--out must differ from --base to preserve the reference firmware and route')
        configuration=a.base/'implementation-configuration.json'
        base_transport=json.loads(configuration.read_text()).get('tpu_transport','mailbox') if configuration.exists() else 'mailbox'
        if base_transport!=a.tpu_transport:
            p.error('Requested transport differs from the retained base; use --compile-only or a fresh matching route. A RAM patch cannot change the hardware ABI')
    (out/'application-manifest.json').unlink(missing_ok=True)
    artifact=a.artifact_dir/'cloth.mlirbc';initial=np.load(a.artifact_dir/'input.npy')
    assert initial.shape==(30,6) and initial.dtype==np.float32
    options=CompileOptions(
        target=KC705_ROCKET if a.cpu=='rocket' else KC705_DIRECT if a.tpu_transport=='direct' else KC705,math_mode='freestanding',allow_approximation=True,
        affine_offload=True,coefficient_tolerance=.0002,affine_policy=a.affine_policy,
        fusion=not a.no_fusion,gemm_policy=a.gemm_policy)
    report=compile_stablehlo(artifact,out/'cloth_program.h',options)
    reference,physics_calls,_=native_reference(artifact,options,initial)
    np.save(out/'physics-first-step-expected.npy',reference[0])
    report['expected_backend_calls_first_step']=physics_calls
    (out/'compile-report.json').write_text(json.dumps(report,indent=2)+'\n')
    camera=json.loads((ROOT/'build-cloth/camera.json').read_text())
    (out/'compiled_scene.h').write_text(
        'static const float initial_state[]={'+','.join(float(v).hex()+'f' for v in initial.ravel())+'};\n'+
        'static const int8_t camera_weights[]={'+','.join(str(v) for row in camera['weights'] for v in row)+'};\n'+
        'static const int32_t camera_bias[]={'+','.join(str(v) for v in camera['bias'])+'};\n')
    def run(command,name):
        with (out/(name+'.log')).open('w') as log:
            r=subprocess.run(list(map(str,command)),stdout=log,stderr=subprocess.STDOUT)
        if r.returncode:raise RuntimeError((out/(name+'.log')).read_text()[-6000:])
    source=ROOT/'sidequests/cloth/compiled_live_firmware.c'
    cpu_flags=(['-march=rv64imafdc_zicsr_zifencei','-mabi=lp64d','-mcmodel=medany'] if a.cpu=='rocket'
               else ['-march=rv32im_zicsr_zifencei','-mabi=ilp32'])
    startup=ROOT/('hardware/kc705_rocket/start.S' if a.cpu=='rocket' else 'hardware/synapse32/start.S')
    run(['riscv64-unknown-elf-gcc',*cpu_flags,'-'+a.optimization,f'-DTINY3TPU_DIRECT_TPU={int(a.tpu_transport=="direct")}',f'-DTINY3TPU_CLOCK_HZ={clock_mhz*1000000}',
         f'-DTINY3TPU_ETHERNET={int('uart'=="udp")}',
         '-ffp-contract=off','-ffreestanding','-fno-builtin','-nostdlib','-msmall-data-limit=0',
         '-ffunction-sections','-fdata-sections','-Wall','-Wextra','-Werror',
         '-I'+str(ROOT/'include'),'-I'+str(out),'-Wl,--no-relax,--gc-sections',
         '-T'+str(ROOT/'hardware/synapse32/bringup.ld'),startup,
         source,ROOT/'src/mmio_backend.c',ROOT/'src/axis_mailbox.c','-lgcc','-o',out/'firmware.elf'],'firmware')
    run(['riscv64-unknown-elf-size',out/'firmware.elf'],'size')
    run(['riscv64-unknown-elf-objcopy','-O','binary',out/'firmware.elf',out/'firmware.bin'],'binary')
    run(['riscv64-unknown-elf-objcopy','-O','verilog','--verilog-data-width=4','--change-addresses=-0x80000000',out/'firmware.elf',out/'firmware.hex'],'image')
    files=[artifact,a.artifact_dir/'input.npy',source,startup,ROOT/'include/tiny3tpu_program_math.h',
           out/'cloth_program.h',out/'compiled_scene.h',out/'firmware.elf',out/'firmware.hex']
    files += sorted((ROOT/'include').glob('tiny3tpu_*transport.h'))
    manifest={'physics':'StableHLO compiled to on-board RISC-V with compiler-selected affine TPU partitions',
        'cpu':a.cpu,'clock_hz':clock_mhz*1000000,'tpu_transport':a.tpu_transport,'io_transport':'uart',
        'compiler_options':{'affine_policy':a.affine_policy,'gemm_policy':a.gemm_policy,'fusion':not a.no_fusion,'optimization':a.optimization},
        'physics_affine_partitions':len(report['partitions']),'placement':report['placement'],
        'physics_backend_calls_first_step':physics_calls,'camera_backend_calls_per_frame':1,
        'count_scope':'Native generated first physics step only; dynamic future-step counts are not assumed',
        'memory':memory_report(out/'firmware.elf'),'implementation':'Firmware only; no bitstream or physical validation',
        'sha256':{str(f.resolve()):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}}
    (out/'application-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    if a.compile_only:
        print((out/'size.log').read_text());return
    if a.cpu=='rocket':
        run([sys.executable,ROOT/'tools/kc705_rocket_build.py','--firmware-elf',out/'firmware.elf',
             '--build-dir',out,'--stage',a.implementation_stage,'--clock-mhz',str(clock_mhz),
             *(['--no-lutram'] if a.no_lutram else [])],'implementation')
        if a.implementation_stage=='synth':
            print((out/'size.log').read_text());return
    else:
        run([sys.executable,ROOT/'tools/kc705_patch_boot_fasm.py','--binary',out/'firmware.bin',
             '--out',out,'--routed-json',a.base/'soc_routed.json','--fasm',a.base/'soc.fasm',
             '--reference-hex',a.base/'firmware.hex','--tilegrid',a.db_root/'xc7k325t/tilegrid.json'],'patch')
        for name in ('soc.json','soc_routed.json','route.log','kc705.xdc','clocks.py','io-profile.json'):
            shutil.copyfile(a.base/name,out/name)
        shutil.copyfile(out/'patched.fasm',out/'soc.fasm')
    run([sys.executable,ROOT/'tools/kc705_export_bitstream.py','--build-dir',out,'--db-root',a.db_root],'export')
    manifest['sha256'][str((out/'soc.bit').resolve())]=hashlib.sha256((out/'soc.bit').read_bytes()).hexdigest()
    manifest['implementation']='Fresh Rocket implementation' if a.cpu=='rocket' else 'Firmware RAM patch of retained base; base RTL is unchanged'
    if a.cpu=='vexriscv':manifest['base_route']=str(a.base.resolve())
    manifest['physical_validation']=False
    (out/'application-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print((out/'size.log').read_text()+(out/'export.log').read_text())
if __name__=='__main__':main()
