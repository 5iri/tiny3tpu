#!/usr/bin/env python3
"""Build the pinned Rocket RV64GC + tiny3tpu no-DDR KC705 image.

The firmware ELF must already be linked at 0x80000000 for RV64GC/lp64d.
This builds a candidate, checks route reports, and never programs the board.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from kc705_open_build import validate_route_log


def rocket_sources():
    names=('freechips.rocketchip.system.LitexConfig_linux_1_1.v',
           'freechips.rocketchip.system.LitexConfig_linux_1_1.behav_srams.v',
           'plusarg_reader.v','AsyncResetReg.v','EICG_wrapper.v')
    root=ROOT/'third_party/rocket'
    manifest=json.loads((root/'source-manifest.json').read_text())
    for name,item in manifest['files'].items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('Rocket source mismatch: '+name)
    return [root/n for n in names]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--firmware-elf',type=Path,required=True)
    p.add_argument('--build-dir',type=Path,required=True)
    p.add_argument('--stage',choices=('generate','synth','route'),default='route')
    p.add_argument('--synapse32-dir',type=Path,default=ROOT.parent/'synapse32')
    p.add_argument('--yosys',type=Path,default=Path.home()/'.apio/packages/oss-cad-suite/bin/yosys')
    p.add_argument('--nextpnr',type=Path,default=ROOT/'build-banana/nextpnr-preg-grade2/nextpnr-xilinx')
    p.add_argument('--chipdb',type=Path,default=Path('/tmp/kc705db/src/nextpnr-xilinx/xilinx/xc7k325tffg900-2.bin'))
    p.add_argument('--seed',type=int,default=4)
    p.add_argument('--clock-mhz',type=int,choices=(25,50,100),default=25)
    p.add_argument('--no-lutram',action='store_true',help='Use registers for small memories while retaining block RAM')
    a=p.parse_args();out=a.build_dir.resolve();out.mkdir(parents=True,exist_ok=True)
    def run(cmd,name):
        (out/(name+'-command.json')).write_text(json.dumps(list(map(str,cmd)),indent=2)+'\n')
        with (out/(name+'.log')).open('w') as log:
            result=subprocess.run(list(map(str,cmd)),stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:raise RuntimeError((out/(name+'.log')).read_text()[-6000:])
    # Reuse only the board pin/IO constraints generator, not its CPU or firmware.
    run([ROOT/'.venv-ddr-compat/bin/python',ROOT/'tools/kc705_open_build.py','generate',
         '--cpu','vexriscv-lite','--no-ddr','--synapse32-dir',a.synapse32_dir,'--build-dir',out],'constraints')
    elf=a.firmware_elf.resolve()
    header=elf.read_bytes()[:20]
    if header[:5]!=b'\x7fELF\x02' or header[18:20]!=b'\xf3\x00':
        raise ValueError('Expected a 64-bit RISC-V ELF')
    run(['riscv64-unknown-elf-objcopy','-O','verilog','--verilog-data-width=4',
         '--change-addresses=-0x80000000',elf,out/'firmware.hex'],'image')
    sources=rocket_sources()
    sources += [ROOT/'hardware/kc705_rocket'/n for n in (
        'axi64_to_wb32.sv','rocket_wb.sv','rocket_tpu_soc.sv','kc705_rocket_noddr_top.sv')]
    sources += [a.synapse32_dir.resolve()/'rtl/core_modules/uart.v']
    sources += [ROOT/'multi-core'/n for n in ('synapse32_tpu_peripheral.sv','synapse32_axis_mailbox.sv',
        'tiny3tpu_axis.sv','tiny3tpu_axis_bridge.sv','tiny3tpu_axi.sv','top.v','tpu_core_wrapper.sv')]
    sources += [ROOT/'systolic_array/rtl'/n for n in ('NxN_systolic_array.v','pe.v')]
    (out/'boot_path.vh').write_text('`define ROCKET_BOOT_HEX "'+str(out/'firmware.hex')+'"\n'+
        '`define ROCKET_CLOCK_DIVIDE '+str(1000//a.clock_mhz)+'\n')
    clocks=[('clk_sys',a.clock_mhz),('clk_sys_unbuf',a.clock_mhz),('clk200',200)]
    (out/'clocks.py').write_text(f'for name, mhz in {clocks!r}:\n    ctx.addClock(name,mhz)\n')
    (out/'rocket-inputs.json').write_text(json.dumps({
        'cpu':'Rocket RV64GC, linux_1_1, FP32/FP64, bare metal',
        'clock_hz':a.clock_mhz*1000000,'firmware_sha256':hashlib.sha256(elf.read_bytes()).hexdigest(),
        'lutram':not a.no_lutram,
        'sources':{str(s):hashlib.sha256(s.read_bytes()).hexdigest() for s in sources}},indent=2)+'\n')
    top='kc705_rocket_noddr_top'
    (out/'synth.ys').write_text('\n'.join([
        'read_verilog -sv -I'+str(a.synapse32_dir.resolve()/'rtl/include')+' '+str(out/'boot_path.vh')+' '+' '.join(map(str,sources)),
        'read_verilog -lib +/xilinx/cells_sim.v +/xilinx/cells_xtra.v',
        'hierarchy -check -top '+top,
        'synth_xilinx -family xc7 -flatten -nowidelut -top '+top+' -run begin:map_dsp',
        # The qualified router models combinational DSPs and the TPU PREG MAC,
        # but not Rocket's AREG-only multiplier packing. Keep CPU pipeline
        # registers in fabric; this preserves RTL cycle latency and enables
        # ordinary FF timing checks instead of suppressing unsupported arcs.
        'scratchpad -set xilinx_dsp.multonly 1',
        'synth_xilinx -family xc7 -top '+top+' -run map_dsp:coarse',
        'scratchpad -unset xilinx_dsp.multonly',
        # Select every supporting cell, excluding only the CPU DSP instances.
        # Optimized accumulator FF names do not retain the accelerator prefix.
        'xilinx_dsp -family xc7 t:DSP48E1 c:*cpu* %i %n',
        'select -clear',
        'synth_xilinx -family xc7 -nowidelut '+('-nolutram ' if a.no_lutram else '')+'-top '+top+' -run coarse: -json '+str(out/'soc.json'),
        'check -assert','stat'])+'\n')
    if a.stage=='generate':return
    run([a.yosys,'-Q','-T','-s',out/'synth.ys'],'synth')
    if a.stage=='synth':return
    run([a.nextpnr,'--chipdb',a.chipdb,'--xdc',out/'kc705.xdc','--freq',str(a.clock_mhz),
         '--pre-pack',out/'clocks.py','--seed',str(a.seed),'--json',out/'soc.json',
         '--write',out/'soc_routed.json','--fasm',out/'soc.fasm'],'route')
    validate_route_log((out/'route.log').read_text())
    print('Rocket route passed report checks; physical validation is still required.')


if __name__=='__main__':main()
