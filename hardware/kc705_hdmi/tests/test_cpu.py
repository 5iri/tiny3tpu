#!/usr/bin/env python3
"""Real RV32 firmware -> two real TPU cores -> MMIO raster -> HDMI bus."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import subprocess
try:
    import numpy as np
except ImportError:
    print('SKIP: NumPy and JAX are required for the CPU/HDMI regression')
    raise SystemExit(77)
from test import ROOT, REPO, SCENE_ASSETS, run, palette, ycc, decoded_rgb
from reference import rasterize


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--firmware',type=Path)
    parser.add_argument('--prepare',action='store_true',help='Generate and compile fresh JAX firmware first')
    parser.add_argument('--full-rotation',action='store_true',help='Run all 256 angles plus the wrap to phase zero')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    firmware=args.firmware.resolve() if args.firmware else out/'firmware'
    if args.prepare:
        try:import jax
        except ImportError:
            print('SKIP: JAX is required to prepare firmware')
            raise SystemExit(77)
        subprocess.run([sys.executable,str(ROOT/'cpu/prepare.py'),'--out',str(firmware)],check=True)
    elif not args.firmware:
        parser.error('--firmware or --prepare is required')
    manifest=json.loads((firmware/'build-manifest.json').read_text())
    for name,value in manifest['firmware_sha256'].items():
        assert hashlib.sha256((firmware/name).read_bytes()).hexdigest()==value,name
    for name,value in manifest['workload_sha256'].items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==value,name
    vertices=manifest['vertices'];triangles=manifest['triangles']
    coordinates=np.load(firmware/'jax-coordinates.npy')
    fixture_phases=256 if args.full_rotation else 12
    (out/'expected-raw.hex').write_text(''.join(f'{int(v)&0xffffffff:08x}\n' for v in coordinates[:fixture_phases].reshape(-1)))
    images={}
    with (out/'expected-vertices.hex').open('w') as vfile,(out/'expected-pixels.hex').open('w') as pfile:
        for phase,q in enumerate(coordinates[:fixture_phases]):
            if phase<12:
                pixels=rasterize(q.tolist(),cpu=True);images[phase]=pixels
                pfile.write(''.join(f'{p:x}\n' for p in pixels))
            for x,y,z in q:
                packed=(320+(int(x)//64))|((280-(int(y)//64))<<10)|((128+(int(z)//128))<<20)
                vfile.write(f'{packed:07x}\n')
    uart=REPO.parent/'synapse32'
    sources=[*(ROOT/'src'/name for name in ('kc705_hdmi_cpu_system.sv','kc705_hdmi_mmio.sv',
        'kc705_hdmi_cpu_scene.sv','kc705_hdmi_display.sv','kc705_hdmi_palette.sv',
        'kc705_hdmi_renderer.sv','kc705_hdmi_ram.sv','kc705_hdmi_framebuffer.sv')),
        REPO/'hardware/kc705_vexriscv/vexriscv_tpu_soc.sv',REPO/'third_party/vexriscv/VexRiscv_Lite.v',
        uart/'rtl/core_modules/uart.v',SCENE_ASSETS/'src/scene.sv',
        *(REPO/'multi-core'/name for name in ('tiny3tpu_direct_peripheral.sv','tiny3tpu_axi.sv','top.v','tpu_core_wrapper.sv')),
        REPO/'systolic_array/rtl/NxN_systolic_array.v',REPO/'systolic_array/rtl/pe.v',Path(__file__).with_name('tb_cpu.sv')]
    paths=[*sources,Path(__file__),Path(__file__).with_name('test.py'),ROOT/'tools/reference.py',
           ROOT/'assets/mesh_config.vh',ROOT/'tools/mesh_assets.py', ROOT/'assets/mesh.json', ROOT/'assets/faces.hex', SCENE_ASSETS/'tools/assets.py',SCENE_ASSETS/'src/font.vh',uart/'rtl/include/memory_map.vh',
           *(SCENE_ASSETS/'assets'/name for name in ('mesh.json','vertices.hex','rotations.hex','faces.hex')),
           firmware/'firmware.hex',firmware/'build-manifest.json']
    hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    run(['verilator','-I'+str(ROOT/'assets'),'--binary','--timing','--top-module','tb_cpu','-Wno-fatal',
         '-I'+str(SCENE_ASSETS/'src'),'-I'+str(uart/'rtl/include'),
         f'-GBOOT_HEX="{firmware}/firmware.hex"','--Mdir',str(out/'obj'),'-o',str(out/'simulate-cpu'),
         *(['-GPHASES=257'] if args.full_rotation else []),
         '-j','4',*(str(p) for p in sources)],out/'compile.log',SCENE_ASSETS)
    log=run([str(out/'simulate-cpu'),'+OUT_DIR='+str(out)],out/'simulation.log',SCENE_ASSETS)
    assert 'CPU_HDMI_PASS' in log
    publications=[(int(p),int(c)) for p,c in re.findall(r'PUBLISH phase=(\d+) cycle=(\d+)',log)]
    assert [p for p,c in publications]==[p%256 for p in range(257 if args.full_rotation else 9)]
    raw=(out/'hdmi-stream.bin').read_bytes();assert len(raw)%4==0
    flags=raw[2::4];phases=raw[3::4];samples=len(flags)
    vs_falls=[i for i in range(1,samples) if flags[i-1]&4 and not flags[i]&4]
    assert all(b-a==420000 for a,b in zip(vs_falls,vs_falls[1:]))
    checked_pixels=0;captured=[]
    for vf in vs_falls:
        origin=vf+35*800
        if origin+420000>samples or not flags[origin]&8:continue
        phase=phases[origin];assert phase in images
        rgb=bytearray();bank=flags[origin]&16
        for y in range(525):
            row=origin+y*800
            for x in range(800):
                f=flags[row+x]
                assert bool(f&1)==(x<640 and y<480),(phase,x,y,'DE')
                assert bool(f&2)==(not 656<=x<752)
                assert bool(f&4)==(not 490<=y<492)
                if x<640 and y<480:
                    assert flags[row+x]&16==bank and phases[row+x]==phase,'Torn frame'
            if y>=480:continue
            for x in range(0,640,2):
                a=ycc(palette(x,y,images[phase][y*640+x],0,0,True))
                b=ycc(palette(x+1,y,images[phase][y*640+x+1],0,0,True))
                cb,cr=(a[1]+b[1]+1)//2,(a[2]+b[2]+1)//2
                pos=(row+x)*4;even=raw[pos]|raw[pos+1]<<8;odd=raw[pos+4]|raw[pos+5]<<8
                assert even==cb<<8|a[0] and odd==cr<<8|b[0],(phase,x,y,'YCC bus')
                rgb.extend(decoded_rgb(even&255,even>>8,odd>>8))
                rgb.extend(decoded_rgb(odd&255,even>>8,odd>>8));checked_pixels+=2
        captured.append(phase)
        if phase in (0,4,7):
            (out/f'jax-hdmi-phase{phase:03d}.ppm').write_bytes(b'P6\n640 480\n255\n'+rgb)
            try:
                from PIL import Image
                Image.frombytes('RGB',(640,480),bytes(rgb)).save(out/f'jax-hdmi-phase{phase:03d}.png')
            except ImportError:pass
    assert set(range(8))<=set(captured),captured
    for name,value in hashes.items():assert hashlib.sha256(Path(name).read_bytes()).hexdigest()==value,name
    intervals=[b[1]-a[1] for a,b in zip(publications,publications[1:])]
    assert all(n==840000 for n in intervals), 'Missed 30 Hz animation deadline'
    submissions=int(re.search(r'CPU_HDMI_PASS submissions=(\d+)',log).group(1))
    report=dict(passed=True,scope='Actual JAX-generated RV32 firmware, dual 4x4 TPU RTL, MMIO rasterizer and HDMI parallel bus; no physical monitor or analog timing measurement',
                clock_hz=25200000,vertices=vertices,triangles=triangles,render_resolution=[640,480],cores=2,array=[4,4],
                submitted_phases=submissions,jax_raw_coordinates_verified_in_firmware=manifest['jax_verify_phases']*vertices*3,
                raw_tpu_results_checked=int(re.search(r'raw_checks=(\d+)',log).group(1)),
                projected_vertices_checked=submissions*vertices,raster_pixels_checked=sum(p<12 for p,c in publications)*307200,
                hdmi_pixels_checked=checked_pixels,publication_intervals_cycles=intervals,
                simulated_frame_rates=[25200000/n for n in intervals],captured_phases=captured,sha256=hashes)
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='sha256'},indent=2))


if __name__=='__main__':main()
