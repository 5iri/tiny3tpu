#!/usr/bin/env python3
"""Build the standalone KC705 HDMI renderer with openXC7; never program a board.

Route rejection checks and an exact configuration-frame round trip are required
before export. These establish file integrity and modeled internal timing, not
complete HDMI I/O timing or physical display operation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SCENE_ASSETS = ROOT / 'hardware/banana_scene'
sys.path.insert(0, str(ROOT / 'tools'))
from kc705_open_build import validate_route_log
from kc705_export_bitstream import frame_data_word

PART = 'xc7k325tffg900-2'
CLOCK_HZ = 25200000


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + '\n')


def run(out, name, command, cwd=ROOT):
    command = list(map(str, command))
    write_json(out / (name + '-command.json'), {'cwd': str(cwd), 'argv': command})
    with (out / (name + '.log')).open('w') as log:
        result = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(name + ' failed:\n' + (out / (name + '.log')).read_text()[-6000:])


def quote(path):
    return '"' + str(path).replace('\\', '\\\\').replace('"', '\\"') + '"'


def check_encoder_log(out, name):
    # Some prjxray versions print invalid frame addresses yet return success.
    # A roundtrip cannot detect a feature discarded before frame generation.
    log = (out / (name + '.log')).read_text()
    if re.search(r'\b(warning|error|invalid|missing|unknown|unsupported|discarded|failed|traceback)\b',
                 log, re.IGNORECASE):
        raise ValueError(name + ' emitted an unqualified diagnostic:\n' + log)


def export(out, tools, db, sources):
    """Use the existing frame encoders, without fabricating a CPU firmware file."""
    validate_route_log((out / 'route.log').read_text())
    for path, expected in sources.items():
        if digest(path) != expected:
            raise ValueError('Source changed during implementation: ' + path)
    run(out, 'fasm2frames', [tools / 'fasm2frames', '--db-root', db, '--part', PART,
                            out / 'soc.fasm', out / 'soc.frames'])
    check_encoder_log(out, 'fasm2frames')
    run(out, 'frames2bit', [tools / 'xc7frames2bit', '--part_file', db / PART / 'part.yaml',
                          '--part_name', PART, '--frm_file', out / 'soc.frames',
                          '--output_file', out / 'soc.bit'])
    check_encoder_log(out, 'frames2bit')
    run(out, 'bitread', [tools / 'bitread', '--part_file', db / PART / 'part.yaml',
                        '-o', out / 'roundtrip.frames', out / 'soc.bit'])
    check_encoder_log(out, 'bitread')
    expected = {}
    for line in (out / 'soc.frames').read_text().splitlines():
        addr, words = line.split(' ', 1)
        expected[int(addr, 16)] = [int(x, 16) for x in words.split(',')]
    actual, addr, words = {}, None, []
    for line in (out / 'roundtrip.frames').read_text().splitlines():
        if line.startswith('.frame '):
            if addr is not None:
                actual[addr] = words
            addr, words = int(line.split()[1], 16), []
        elif line.strip():
            words.extend(int(x, 16) for x in line.split())
    if addr is not None:
        actual[addr] = words
    if not expected or not set(expected) <= set(actual):
        raise ValueError('Missing exported configuration frames')
    if any(len(w) != 101 for w in actual.values()):
        raise ValueError('Invalid readback frame length')
    for address, data in expected.items():
        if len(data) != 101 or any(frame_data_word(i, word) !=
                frame_data_word(i, actual[address][i]) for i, word in enumerate(data)):
            raise ValueError('Configuration-frame roundtrip mismatch')
    if any(any(frame_data_word(i, word) != 0 for i, word in enumerate(actual[address]))
           for address in set(actual)-set(expected)):
        raise ValueError('Unexpected nonzero configuration frame')
    files = [out / name for name in ('soc.json', 'soc_routed.json', 'soc.fasm', 'soc.frames',
             'soc.bit', 'roundtrip.frames', 'route.log', 'soc.sdf', 'kc705.xdc', 'clocks.py',
             'implementation-manifest.json')]
    files += [db / PART / 'part.yaml', db / PART / 'part.json',
              db / 'xc7k325t/tilegrid.json', Path(__file__).resolve()]
    record = dict(passed=True, target='kc705_hdmi', part=PART,
                  frame_roundtrip_exact_except_generated_ecc=True,
                  ecc_exclusion='word50 bits12:0 only', input_frames=len(expected),
                  complete_physical_timing_proven=False, physical_validation=False,
                  scope='Export integrity only. ADV7511 external setup/hold, board skew and physical monitor operation remain unqualified.',
                  source_sha256=sources, sha256={str(p): digest(p) for p in files})
    write_json(out / 'bitstream-manifest.json', record)
    print('PASS configuration-frame roundtrip:', len(expected), 'frames; image:', out / 'soc.bit')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('synth', 'route', 'bitstream'))
    parser.add_argument('--out', type=Path, default=ROOT / 'build-kc705-hdmi')
    packaged_yosys = Path.home() / '.apio/packages/oss-cad-suite/bin/yosys'
    default_yosys = packaged_yosys if packaged_yosys.is_file() else Path(shutil.which('yosys') or packaged_yosys)
    parser.add_argument('--yosys', type=Path, default=default_yosys)
    parser.add_argument('--nextpnr', type=Path, default=ROOT / 'build-banana/nextpnr-preg-grade2/nextpnr-xilinx')
    parser.add_argument('--chipdb', type=Path, default=ROOT / 'build-kc705-hdmi/chipdb/xc7k325tffg900-2.bin')
    parser.add_argument('--db-root', type=Path, default=ROOT / 'build-banana/nextpnr-source/xilinx/external/prjxray-db/kintex7')
    parser.add_argument('--tools', type=Path, default=Path.home() / '.apio/packages/openxc7/bin')
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--cpu', action='store_true', help='JAX firmware on VexRiscv and two 4x4 TPUs, driving the HDMI MMIO target')
    parser.add_argument('--framebuffer', action='store_true', help='CPU-written RGB565 instead of the mesh rasterizer; requires --cpu')
    parser.add_argument('--firmware', type=Path, help='Directory produced by cpu/prepare.py; required with --cpu')
    parser.add_argument('--synapse32-dir', type=Path, default=ROOT.parent/'synapse32')
    args = parser.parse_args()
    video_720p=False
    clock_hz=CLOCK_HZ
    if args.framebuffer and not args.cpu:parser.error('--framebuffer requires --cpu')
    for name in ('out', 'yosys', 'nextpnr', 'chipdb', 'db_root', 'tools'):
        setattr(args, name, getattr(args, name).resolve())
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    # Every stage starts with fresh synthesis. A failed rebuild must never leave
    # an older success manifest or image looking current in this output folder.
    for name in ('soc.json', 'soc_routed.json', 'soc.fasm', 'soc.sdf',
                 'soc.frames', 'soc.bit', 'roundtrip.frames',
                 'implementation-manifest.json', 'bitstream-manifest.json',
                 'synth.log', 'route.log', 'fasm2frames.log', 'frames2bit.log',
                 'bitread.log'):
        (out / name).unlink(missing_ok=True)
    if args.stage != 'synth' and not args.chipdb.is_file():
        parser.error('Missing Kintex-7 chip database; supply --chipdb')
    sources = sorted((HERE / 'src').glob('*.sv'))
    required = ['kc705_hdmi_top.sv', 'kc705_hdmi_display.sv', 'kc705_hdmi_init.sv']
    if not all((HERE / 'src' / name).is_file() for name in required):
        parser.error('HDMI top/display/init source modules must all be present')
    sources += [SCENE_ASSETS / 'src' / name for name in
                ('buttons.sv', 'scene.sv')]
    sources += [ROOT / 'multi-core/tpu_core_wrapper.sv',
                ROOT / 'systolic_array/rtl/NxN_systolic_array.v', ROOT / 'systolic_array/rtl/pe.v']
    inputs = sources + [SCENE_ASSETS / 'src/font.vh', HERE / 'constraints/kc705.xdc',
                        Path(__file__).resolve(), ROOT / 'tools/kc705_open_build.py',
                        ROOT / 'tools/kc705_export_bitstream.py']
    inputs += [SCENE_ASSETS / 'assets' / name for name in
               ('vertices.hex', 'rotations.hex', 'faces.hex', 'mesh.json')]
    if args.cpu:
        inputs += [HERE/'assets/mesh.json', HERE/'assets/faces.hex', HERE/'tools/mesh_assets.py']
    inputs += [HERE/'assets/mesh_config.vh']
    source_hashes = {str(p): digest(p) for p in inputs}
    boot_header=[]
    include_flags='-Isrc -I../kc705_hdmi/assets '
    if args.cpu:
        if args.firmware is None:parser.error('--cpu requires --firmware')
        firmware=args.firmware.resolve()
        firmware_manifest=json.loads((firmware/'build-manifest.json').read_text())
        for name,expected in firmware_manifest['firmware_sha256'].items():
            if digest(firmware/name)!=expected:raise ValueError('Firmware artifact changed: '+name)
        for name,expected in firmware_manifest['source_sha256'].items():
            path=Path(name) if Path(name).is_absolute() else ROOT/name
            if digest(path)!=expected:raise ValueError('Firmware source changed: '+name)
            inputs.append(path)
        for name,expected in firmware_manifest['workload_sha256'].items():
            if digest(name)!=expected:raise ValueError('JAX workload changed: '+name)
            inputs.append(Path(name))
        ram_bytes=firmware_manifest['memory']['ram_bytes']
        video_720p=args.framebuffer and firmware_manifest.get('display')==[1280,720]
        clock_hz=74250000 if video_720p else CLOCK_HZ
        if (firmware_manifest['cores']!=2 or firmware_manifest['clock_hz']!=clock_hz
            or ram_bytes not in ((262144,1048576,1245184) if args.framebuffer else (262144,))):
            raise ValueError('Firmware/hardware configuration mismatch')
        if args.framebuffer:
            if (firmware_manifest.get('framebuffer_abi')!='PFB1' or
                firmware_manifest.get('display')!=([1280,720] if video_720p else [640,480]) or
                firmware_manifest.get('framebuffer') not in ([[480,270]] if video_720p else [[160,120],[320,240]]) or
                firmware_manifest.get('pixel_format')!='RGB565'):
                raise ValueError('Firmware/framebuffer configuration mismatch')
        elif (firmware_manifest.get('framebuffer_abi') is not None or
              firmware_manifest['vertices']!=len(json.loads((HERE/'assets/mesh.json').read_text())['vertices']) or
              firmware_manifest['triangles']!=len(json.loads((HERE/'assets/mesh.json').read_text())['faces'])):
            raise ValueError('Firmware/mesh configuration mismatch')
        uart=args.synapse32_dir.resolve()
        extra=[uart/'rtl/core_modules/uart.v',ROOT/'third_party/vexriscv/VexRiscv_Lite.v',
               ROOT/'hardware/kc705_vexriscv/vexriscv_tpu_soc.sv',
               *(ROOT/'multi-core'/name for name in ('tiny3tpu_direct_peripheral.sv','tiny3tpu_axi.sv','top.v',
                   'synapse32_tpu_peripheral.sv','synapse32_axis_mailbox.sv','tiny3tpu_axis.sv','tiny3tpu_axis_bridge.sv')),
               ROOT/'hardware/math/tiny3tpu_cordic_exp.sv',ROOT/'hardware/math/tiny3tpu_cordic_mmio.sv']
        sources+=extra
        inputs+=extra+[uart/'rtl/include/memory_map.vh',firmware/'firmware.hex',firmware/'build-manifest.json']
        source_hashes={str(p):digest(p) for p in inputs}
        header=out/'boot_path.vh'
        header.write_text('`define VEXRISCV_BOOT_HEX '+quote(firmware/'firmware.hex')+'\n')
        boot_header=[header]
        include_flags+='-I'+os.path.relpath(uart/'rtl/include',SCENE_ASSETS)+' '
    (out / 'kc705.xdc').write_bytes((HERE / 'constraints/kc705.xdc').read_bytes())
    (out / 'clocks.py').write_text('for name, mhz in '+repr([
        ('clk200', 200.0), ('clk_pixel_unbuf', clock_hz/1e6), ('clk_pixel', clock_hz/1e6)])+
        ':\n    ctx.addClock(name, mhz)\n')
    script = [
        # Yosys keeps quotes embedded in -I options; synthesis runs in SCENE_ASSETS.
        'read_verilog -sv '+include_flags + ' '.join(map(quote, [*boot_header,*sources])),
        'read_verilog -lib +/xilinx/cells_sim.v +/xilinx/cells_xtra.v',
        *(['chparam -set CPU_DRIVEN 1 kc705_hdmi_top'] if args.cpu else []),
        *(['chparam -set CPU_FRAMEBUFFER 1 kc705_hdmi_top'] if args.framebuffer else []),
        *(['chparam -set VIDEO_720P 1 kc705_hdmi_top'] if video_720p else []),
        *([f'chparam -set CPU_BOOT_WORDS {ram_bytes//4} -set FRAME_WIDTH {firmware_manifest["framebuffer"][0]} -set FRAME_HEIGHT {firmware_manifest["framebuffer"][1]} kc705_hdmi_top'] if args.framebuffer else []),
        'hierarchy -check -top kc705_hdmi_top',
        # The current nextpnr cascade repair can move a driver while fixing
        # another pair, leaving an unroutable dedicated RAMB36 cascade. Use
        # Yosys's standard xc7 memory mapping without HAS_CASCADE: larger RAMs
        # use independent BRAMs and fabric muxes, preserving synchronous reads.
        'synth_xilinx -family xc7 -flatten -nowidelut -top kc705_hdmi_top -run begin:map_memory',
        'memory_libmap -logic-cost-rom 0.015625 -lib +/xilinx/lutrams_xc5v.txt '
        '-lib +/xilinx/brams_xc4v.txt -D HAS_SIZE_36 -D HAS_CONFLICT_BUG '
        '-D HAS_MIXWIDTH_SDP -no-auto-huge',
        'techmap -map +/xilinx/lutrams_xc5v_map.v',
        'techmap -map +/xilinx/brams_xc6v_map.v',
        'synth_xilinx -family xc7 -flatten -nowidelut -top kc705_hdmi_top -run map_ffram:',
        'check -assert', 'stat', 'write_json ' + quote(out / 'soc.json')]
    (out / 'synth.ys').write_text('\n'.join(script) + '\n')
    # Original renderer ROM paths are relative to hardware/banana_scene.
    # Its sources/assets are reused unchanged and hashed above.
    run(out, 'synth', [args.yosys, '-Q', '-T', '-s', out / 'synth.ys'], cwd=SCENE_ASSETS)
    netlist = json.loads((out / 'soc.json').read_text())['modules']['kc705_hdmi_top']
    counts = {}
    for cell in netlist['cells'].values():
        counts[cell['type']] = counts.get(cell['type'], 0) + 1
        if cell['type'] == 'RAMB36E1':
            for port in ('A', 'B'):
                if cell['parameters'].get('RAM_EXTENSION_' + port, 'NONE') != 'NONE':
                    raise ValueError('Unexpected dedicated BRAM cascade in synthesis')
    if args.framebuffer:
        # A successful tool exit must not hide removal of the live display.
        for signal in ('h_count','v_count','display_valid'):
            bits=netlist['netnames']['pixel_path.system.display.'+signal]['bits']
            if not any(isinstance(bit,int) for bit in bits):
                raise ValueError('Synthesis removed live framebuffer signal: '+signal)
        display_brams=sum(c['type'] in ('RAMB36E1','RAMB18E1') for n,c in netlist['cells'].items()
                          if 'pixel_path.system.display.bank' in n)
        if display_brams==0:raise ValueError('Synthesis removed framebuffer memory')
    report = dict(target='kc705_hdmi', part=PART, cpu=args.cpu, firmware=args.cpu, ddr=False,
                  tpu_cores=2 if args.cpu else 1, tpu_array=[4,4],
                  framebuffer=args.framebuffer,
                  vertices=0 if args.framebuffer else firmware_manifest['vertices'] if args.cpu else 204,
                  triangles=0 if args.framebuffer else firmware_manifest['triangles'] if args.cpu else 407,
                  animation_hz=None if args.framebuffer else 30 if args.cpu else 60,
                  clock_hz=clock_hz, pixel_clock_hz=clock_hz, raster=[1280,720] if video_720p else [640,480],
                  totals=[1650,750] if video_720p else [800,525], scanout_hz=60,
                  video_mode='720p' if video_720p else 'vga',
                  render_resolution=firmware_manifest['framebuffer'] if args.framebuffer else [640,480],
                  raster_lanes=0 if args.framebuffer else 2,
                  pll=dict(primitive='MMCME2_ADV' if video_720p else 'PLLE2_ADV',
                           input_mhz=200, input_divide=10, feedback_multiply=37.125 if video_720p else 63,
                           output_divide=10 if video_720p else 50, pfd_mhz=20, vco_mhz=742.5 if video_720p else 1260),
                  forwarded_clock_phase='Inverted ODDR; rising capture half-cycle after data launch',
                  adv7511_setup_ns=1.0, adv7511_hold_ns=0.7,
                  hdmi_io_timing_qualified=False, complete_physical_timing_proven=False,
                  physical_validation=False, synthesis_passed=True, cells=counts,
                  dedicated_bram_cascades=False,
                  timing_scope='Modeled internal routes only; external I/O constraints unsupported by this nextpnr backend. No physical HDMI validation.',
                  source_sha256=source_hashes, yosys_sha256=digest(args.yosys))
    if 2*counts.get('RAMB36E1',0)+counts.get('RAMB18E1',0)>890:
        raise ValueError('Synthesis exceeds KC705 block RAM capacity')
    write_json(out / 'implementation-manifest.json', report)
    print('Synthesis passed:', {k: v for k, v in counts.items() if k in ('DSP48E1', 'RAMB36E1', 'RAMB18E1', 'PLLE2_ADV', 'MMCME2_ADV', 'ODDR')})
    if args.stage == 'synth':
        return
    run(out, 'route', [args.nextpnr, '--chipdb', args.chipdb, '--xdc', out / 'kc705.xdc',
                      '--freq', str(clock_hz/1e6), '--pre-pack', out / 'clocks.py', '--seed', args.seed,
                      '--json', out / 'soc.json', '--write', out / 'soc_routed.json',
                      '--fasm', out / 'soc.fasm', '--sdf', out / 'soc.sdf'])
    log = (out / 'route.log').read_text()
    validate_route_log(log)
    if re.search(r'ignoring unsupported XDC|matched nothing|was NOT applied|ignoring virtual clock', log):
        raise ValueError('Route did not apply all supplied constraints')
    report.update(route_guard_passed=True, nextpnr_sha256=digest(args.nextpnr),
                  chipdb_sha256=digest(args.chipdb), seed=args.seed,
                  clocks={name: {'achieved_mhz': float(achieved), 'target_mhz': float(target)}
                          for name, achieved, target in re.findall(
                    r"Max frequency for clock\s+'([^']+)': ([0-9.]+) MHz \(PASS at ([0-9.]+) MHz\)", log)})
    for source, value in source_hashes.items():
        if digest(source) != value:
            raise ValueError('Source changed during implementation: ' + source)
    write_json(out / 'implementation-manifest.json', report)
    print('Route guard passed; external HDMI I/O timing remains unqualified.')
    if args.stage == 'bitstream':
        export(out, args.tools, args.db_root, source_hashes)


if __name__ == '__main__':
    main()
