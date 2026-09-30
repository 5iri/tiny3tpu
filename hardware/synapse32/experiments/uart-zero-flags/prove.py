#!/usr/bin/env python3
"""Prove full UART equivalence and exact zero-flag update identities."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from prepare import patch

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
a=p.parse_args();source=a.source.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
(out/'uart.v').write_text(patch(source.read_text()))
root=Path(__file__).resolve().parents[4]
include=root.parent/'synapse32/rtl/include';defines=include/'memory_map.vh'
(out/'identities.v').write_text('''module identities(input [15:0] count,divisor,output same);
wire [15:0] decremented=count-1'b1;
wire [15:0] half={1'b0,divisor[15:1]};
assign same=((decremented==0)==(count==1)) && ((half==0)==(divisor[15:1]==0));
endmodule
''')
scripts={
 'identities':f'read_verilog {out/"identities.v"}\nprep -top identities; opt; check -assert; sat -prove same 1 -verify;\n',
 'equivalence':f'''read_verilog -I{include} {source}
rename uart gold
read_verilog -I{include} {out/'uart.v'}
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
'''}
yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');passed=True
for name,body in scripts.items():
    script=out/(name+'.ys');script.write_text(body)
    with (out/(name+'.log')).open('w') as log:
        rc=subprocess.run([str(yosys),'-Q','-T','-s',str(script)],stdout=log,stderr=subprocess.STDOUT).returncode
    passed &= rc==0
paths=[source,out/'uart.v',out/'identities.v',defines,yosys,Path(__file__).resolve(),Path(__file__).with_name('prepare.py').resolve()]
paths += [out/(name+suffix) for name in scripts for suffix in ['.ys','.log']]
r=dict(passed=passed,claim='Whole UART module sequential equivalence, including counters, FIFO state, serial output, reads and interrupts, with arbitrary bus/RX inputs and reset. Mirrored zero flags update on the original counter edges; decrement/half-divisor identities cover all 16-bit values. No baud period or acceptance cycle changes.',sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in paths})
(out/'results.json').write_text(json.dumps(r,indent=2)+'\n');assert r['passed'];print('PASS whole UART equivalence and zero-flag update identities')
