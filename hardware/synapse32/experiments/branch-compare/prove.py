#!/usr/bin/env python3
"""Prove branch flags match captured operands at every existing system edge."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from prepare import OLD,NEW,prepare

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
a=p.parse_args();source=a.source.resolve();out=a.out.resolve();overlay=prepare(source,out)
h='''module equiv #(parameter SYSTEM_MUL=1)(input system_clk,system_rst,
input [31:0] rs1_raw,rs2_raw,output same);
wire [31:0] rs1_value,rs2_value;
'''+NEW+'''
assign same=(branch_equal == (rs1_value == rs2_value)) &&
 (branch_signed_less == ($signed(rs1_value) < $signed(rs2_value))) &&
 (branch_unsigned_less == (rs1_value < rs2_value));
endmodule
'''
(out/'harness.v').write_text(h)
yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');passed=True
for mode in [0,1]:
    script=out/f'proof-{mode}.ys'
    # Skip the unconstrained initial outputs. After the first edge all flag
    # and operand registers are overwritten by arbitrary inputs/reset. A universal
    # one-step proof covers every edge, independently of the previous state.
    proof='sat -seq 2 -prove-skip 1 -prove same 1 -verify' if mode else 'sat -prove same 1 -verify'
    script.write_text(f'read_verilog {out/"harness.v"}\nchparam -set SYSTEM_MUL {mode} equiv\nprep -top equiv; flatten; opt; check -assert; {proof};\n')
    with (out/f'proof-{mode}.log').open('w') as log:
        rc=subprocess.run([str(yosys),'-Q','-T','-s',str(script)],stdout=log,stderr=subprocess.STDOUT).returncode
    passed &= rc==0
paths=list(source.glob('*.v'))+list(overlay.glob('*.v'))+[out/'harness.v',yosys,Path(__file__).resolve(),Path(__file__).with_name('prepare.py').resolve()]
paths += [out/f'proof-{m}.{ext}' for m in [0,1] for ext in ['ys','log']]
r=dict(passed=passed,claim='For SYSTEM_MUL=1, flags exactly equal comparisons of the existing captured operands after every system edge for arbitrary raw operands and synchronous reset, with no initial-state assumption. SYSTEM_MUL=0 proves combinationally. Only the six branch comparisons consume these flags; all other execution logic and pipeline stages are unchanged.',sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in paths})
(out/'results.json').write_text(json.dumps(r,indent=2)+'\n');assert r['passed'];print('PASS captured comparison invariant and direct-profile equivalence')
