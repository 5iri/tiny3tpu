#!/usr/bin/env python3
"""Validate command framing, geometry guards, sticky buttons, and backpressure."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,default=ROOT/'build/mmio')
    out=p.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=True)
    files=[ROOT/'src/kc705_hdmi_mmio.sv',Path(__file__).with_name('tb_mmio.sv')]
    subprocess.run(['iverilog','-I'+str(ROOT/'assets'),'-g2012','-s','tb_mmio','-o',str(out/'sim'),*map(str,files)],check=True)
    result=subprocess.run(['vvp',str(out/'sim')],check=True,capture_output=True,text=True,timeout=30)
    (out/'simulation.log').write_text(result.stdout+result.stderr)
    assert 'MMIO_PASS' in result.stdout
    report=dict(passed=True,checks=['invalid/partial/unaligned requests','ordered complete vertex uploads',
                'coordinate bounds','busy-write rejection','response backpressure','single side effects','sticky button W1C'],
                sha256={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [*files,ROOT/'assets/mesh_config.vh',Path(__file__)]})
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(result.stdout.strip())


if __name__=='__main__':main()
