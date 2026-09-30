#!/usr/bin/env python3
import hashlib,json,subprocess,argparse
from pathlib import Path
from prepare import NEW,patch_soc
p=argparse.ArgumentParser();p.add_argument('--soc',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
s=a.soc.resolve().read_text()
# Use the actual generated integration's relevant declarations in the miter.
need=['wire external_address =','wire uart_address =','wire idle =','assign req_ready =','wire accept =']
lines=[]
for key in need:
 matches=[line for line in s.splitlines() if key in line]
 assert len(matches)==1,key
 lines+=matches
h='module equiv(input rst,local_valid,external_pending,req_valid,ext_req_ready,req_write,input [31:0] req_addr,input [3:0] req_wstrb,output same);\nwire req_ready;\n'+'\n'.join(lines)+'\n'+NEW+'''
assign same=((accept && uart_address && req_write && req_wstrb==15)==(uart_accept && req_write && req_wstrb==15)) &&
 ((accept && uart_address && !req_write)==(uart_accept && !req_write));
endmodule
'''
(out/'harness.v').write_text(h);(out/'candidate.sv').write_text(patch_soc(s))
script=f'read_verilog {out/"harness.v"}\nprep -top equiv; opt; check -assert; sat -prove same 1 -verify;\n'
(out/'proof.ys').write_text(script)
with (out/'proof.log').open('w') as log:
 rc=subprocess.run(['/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys','-Q','-T','-s',str(out/'proof.ys')],stdout=log,stderr=subprocess.STDOUT).returncode
paths=[a.soc.resolve(),Path(__file__),Path(__file__).with_name('prepare.py'),out/'harness.v',out/'proof.ys',out/'candidate.sv']
(out/'results.json').write_text(json.dumps({'passed':rc==0,'sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')
if rc:raise SystemExit('FAIL UART acceptance equivalence')
print('PASS combinational UART acceptance equivalence: all addresses, reset, idle and external ready states')
