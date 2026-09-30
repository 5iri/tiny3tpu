#!/usr/bin/env python3
"""Prove UART state, output and FIFO payload equivalence across the reset-gating boundary."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from prepare import gate_reference,patch_uart,patch_soc
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
source=a.source.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
for name,patch in [('uart.v',patch_uart),('synapse32_dram_soc.sv',patch_soc)]:
    (out/('parent-'+name)).write_bytes((source/name).read_bytes())
    (out/name).write_text(patch((source/name).read_text()))
(out/'reference-uart.v').write_text(gate_reference((source/'uart.v').read_text()))
# Combinational event wires intentionally differ while rst is asserted.
# Do not use these as equivalence cutpoints; all state and outputs remain compared.
exclude=['rx_fifo_pop_request','rx_fifo_clear_request','tx_fifo_pushed','tx_fifo_cleared','rx_fifo_pushed','rx_fifo_popped','rx_fifo_cleared','thre_irq_clear']
(out/'blacklist.txt').write_text('\n'.join(exclude)+'\n')
root=Path(__file__).resolve().parents[4];inc=root.parent/'synapse32/rtl/include';yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
body=f'''read_verilog -I{inc} {out/'reference-uart.v'}
rename uart gold
read_verilog -I{inc} {out/'uart.v'}
rename uart gate
proc
memory_map
async2sync
opt
equiv_make -blacklist {out/'blacklist.txt'} gold gate equiv
hierarchy -top equiv
opt_clean
equiv_simple
equiv_induct -seq 8
equiv_status -assert
'''
(out/'equivalence.ys').write_text(body)
with (out/'equivalence.log').open('w') as log: rc=subprocess.run([str(yosys),'-Q','-T','-s',str(out/'equivalence.ys')],stdout=log,stderr=subprocess.STDOUT).returncode
paths=[source/'uart.v',source/'synapse32_dram_soc.sv',inc/'memory_map.vh',yosys,Path(__file__).resolve(),Path(__file__).with_name('prepare.py').resolve()]+list(out.iterdir())
r=dict(passed=rc==0,claim='All UART registers, FIFO payload memory and observable outputs are sequentially equivalent to the exact reset-gated parent integration for arbitrary bus/RX/reset inputs. Only combinational event wires that intentionally differ during reset are excluded as cutpoints. SoC transformation only removes rst from the two UART input enables; reset itself, response behavior, clocks and all other SoC bytes are preserved.',sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in paths})
(out/'results.json').write_text(json.dumps(r,indent=2)+'\n');assert r['passed'];print('PASS full UART state, FIFO payload and output equivalence across reset gating')
