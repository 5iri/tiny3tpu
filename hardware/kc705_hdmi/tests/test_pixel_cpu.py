#!/usr/bin/env python3
"""Compiled JAX on RV32 + real TPU -> CPU RGB565 -> HDMI, without a rasterizer."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
try:
    import numpy as np
    import jax
except ImportError:
    print('SKIP: NumPy and JAX are required for the CPU/framebuffer regression')
    raise SystemExit(77)
from test import ROOT, REPO, run
from test_pixels import verify


def raster(coordinates):
    frame = [0x0841]*(160*120)
    for i in range(8):
        j=(i&4)|((i+1)&3)
        x,y=80+int(int(coordinates[i,0])/64),60+int(int(coordinates[i,1])/64)
        tx,ty=80+int(int(coordinates[j,0])/64),60+int(int(coordinates[j,1])/64)
        dx,sx=abs(tx-x),1 if x<tx else -1
        dy,sy=-abs(ty-y),1 if y<ty else -1
        error=dx+dy
        while True:
            if 0<=x<160 and 0<=y<120:frame[y*160+x]=0xffe0 if i<4 else 0x07ff
            if (x,y)==(tx,ty):break
            twice=2*error
            if twice>=dy:error+=dy;x+=sx
            if twice<=dx:error+=dx;y+=sy
    return frame


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    fw=out/'firmware'
    subprocess.run([sys.executable,str(ROOT/'cpu/prepare_pixels.py'),'--out',str(fw)],check=True)
    manifest=json.loads((fw/'build-manifest.json').read_text())
    uart=REPO.parent/'synapse32'
    sources=[ROOT/'src/kc705_hdmi_pixel_system.sv',ROOT/'src/kc705_hdmi_pixels.sv',
             REPO/'hardware/kc705_vexriscv/vexriscv_tpu_soc.sv',REPO/'third_party/vexriscv/VexRiscv_Lite.v',
             uart/'rtl/core_modules/uart.v',
             *(REPO/'multi-core'/n for n in ('tiny3tpu_direct_peripheral.sv','tiny3tpu_axi.sv','top.v','tpu_core_wrapper.sv')),
             REPO/'systolic_array/rtl/NxN_systolic_array.v',REPO/'systolic_array/rtl/pe.v',
             Path(__file__).with_name('tb_pixel_cpu.sv')]
    files=[*sources,Path(__file__),Path(__file__).with_name('test_pixels.py'),fw/'firmware.hex',fw/'build-manifest.json']
    hashes={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    run(['verilator','--binary','--timing','-Wno-fatal','--top-module','tb_pixel_cpu',
         '-I'+str(uart/'rtl/include'),f'-GBOOT_HEX="{fw}/firmware.hex"',
         '--Mdir',str(out/'obj'),'-o',str(out/'sim'),'-j','4',*map(str,sources)],out/'compile.log',REPO)
    log=run([str(out/'sim'),'+OUT_DIR='+str(out)],out/'simulation.log',REPO)
    match=re.search(r'PIXEL_CPU_PASS core0=(\d+) core1=(\d+) writes=(\d+) submits=(\d+)',log)
    assert match,log[-2000:]
    coordinates=np.load(fw/'coordinates.npy')
    report=verify(out,lambda tag:raster(coordinates[tag]))
    assert set(range(4))<=set(report['captured_tags']),report
    for f,digest in hashes.items():assert hashlib.sha256(Path(f).read_bytes()).hexdigest()==digest,f
    report.update(passed=True,scope='Actual RV32 firmware, dual TPU, CPU-written RGB565 and digital HDMI RTL. No physical board, DDR3, MJX or training claim.',
                  rtl_counts=dict(zip(('core0_launches','core1_launches','pixel_word_writes','submitted_frames'),map(int,match.groups()))),
                  memory=manifest['memory'],sha256=hashes)
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='sha256'},indent=2))


if __name__=='__main__':main()
