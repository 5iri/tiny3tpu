#!/usr/bin/env python3
"""Prove full UART equivalence for the disjoint readback expression."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from prepare import patch
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();source=a.source.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
(out/'parent-uart.v').write_bytes(source.read_bytes());(out/'uart.v').write_text(patch(source.read_text()))
root=Path(__file__).resolve().parents[4];inc=root.parent/'synapse32/rtl/include';yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
(out/'proof.ys').write_text(f'''read_verilog -I{inc} {source}
rename uart gold
read_verilog -I{inc} {out/'uart.v'}
rename uart gate
proc
memory_map
async2sync
opt
equiv_make gold gate equiv
hierarchy -top equiv
opt_clean
equiv_simple
equiv_induct -seq 8
equiv_status -assert
''')
with (out/'proof.log').open('w') as log:rc=subprocess.run([str(yosys),'-Q','-T','-s',str(out/'proof.ys')],stdout=log,stderr=subprocess.STDOUT).returncode
paths=[source,inc/'memory_map.vh',yosys,Path(__file__).resolve(),Path(__file__).with_name('prepare.py').resolve()]+list(out.iterdir())
r=dict(passed=rc==0,claim='Full UART sequential equivalence, including all state, FIFO payload and read/serial/interrupt outputs. Only the readback combinational expression changes; arbitrary enables, addresses, reset and RX covered.',sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in paths})
(out/'results.json').write_text(json.dumps(r,indent=2)+'\n');assert r['passed'];print('PASS full UART equivalence with parallel readback')
