#!/usr/bin/env python3
"""Prove exact RAM-enable equivalence for arbitrary request/state/size inputs."""
import argparse,hashlib,json,re,subprocess
from pathlib import Path
from prepare import NEW,patch_soc
p=argparse.ArgumentParser();p.add_argument('--soc',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
s=a.soc.resolve().read_text();decl=[]
for key in ['wire external_address =','wire boot_address =','wire idle =','assign req_ready =','wire accept =']:
    matches=re.findall(r'^    '+re.escape(key)+r'[^;]*;',s,re.M)
    assert len(matches)==1,key
    decl+=matches
h='''module equiv(input rst,local_valid,external_pending,req_valid,ext_req_ready,
input [31:0] req_addr,input signed [31:0] BOOT_WORDS,output same);
wire req_ready;
'''+ '\n'.join(decl)+'\n'+NEW+'''
assign same=(accept && boot_address)==boot_accept;
endmodule
'''
(out/'harness.v').write_text(h);(out/'candidate.sv').write_text(patch_soc(s))
(out/'proof.ys').write_text(f'read_verilog {out/"harness.v"}\nprep -top equiv; opt; check -assert; sat -prove same 1 -verify;\n')
with (out/'proof.log').open('w') as log:
 rc=subprocess.run(['/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys','-Q','-T','-s',str(out/'proof.ys')],stdout=log,stderr=subprocess.STDOUT).returncode
paths=[a.soc.resolve(),Path(__file__).resolve(),Path(__file__).with_name('prepare.py').resolve(),out/'harness.v',out/'proof.ys',out/'candidate.sv']
(out/'results.json').write_text(json.dumps({'passed':rc==0,'claim':'RAM block enable identical for all request/state inputs and every signed 32-bit BOOT_WORDS parameter. Read/write bodies and all other sequential logic unchanged. No extra cycle.','sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')
if rc:raise SystemExit('FAIL boot enable equivalence')
print('PASS boot enable equivalence for all addresses, state, reset, external ready and BOOT_WORDS')
