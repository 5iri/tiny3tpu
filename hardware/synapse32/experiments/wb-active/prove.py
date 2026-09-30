#!/usr/bin/env python3
"""Prove target-active registers match original Wishbone cycle/strobe gating."""
import argparse, hashlib, json, subprocess
from pathlib import Path
from prepare import HERE, ROOT, NEW, patch_top
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--out',type=Path,required=True)
out=parser.parse_args().out.resolve();out.mkdir(parents=True,exist_ok=True)
bridge=ROOT/'hardware/synapse32/litedram_wishbone_bridge.sv'
top=ROOT/'hardware/synapse32/kc705_synapse32_top.sv'
(out/'top_candidate.sv').write_text(patch_top(top.read_text()))
harness='''module decode_equiv(input clk,rst,req_valid,req_write,resp_ready,wb_ack,wb_err,
input [31:0] req_addr,req_wdata,wb_dat_r,input [3:0] req_wstrb,output same);
wire req_ready,resp_valid,resp_error,wb_cyc,wb_stb,wb_we;
wire [31:0] resp_rdata,wb_dat_w;
wire [29:0] wb_adr;
wire [3:0] wb_sel;
litedram_wishbone_bridge dut(.*);
'''+NEW+'''
assign same=(ctrl_active==(wb_cyc && wb_adr[29:14]==16'hf000)) &&
            (dram_active==(wb_cyc && wb_adr[29:28]==2'b01)) && (wb_stb==wb_cyc);
endmodule
'''
(out/'harness.sv').write_text(harness)
script=f'read_verilog -sv {bridge} {out/"harness.sv"}\nprep -top decode_equiv; flatten; opt; check -assert; sat -seq 3 -tempinduct -maxsteps 12 -set-init-zero -prove same 1 -verify;\n'
(out/'proof.ys').write_text(script)
with (out/'proof.log').open('w') as log:
 rc=subprocess.run(['/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys','-Q','-T','-s',str(out/'proof.ys')],stdout=log,stderr=subprocess.STDOUT).returncode
paths=[Path(__file__),HERE/'prepare.py',bridge,top,out/'top_candidate.sv',out/'harness.sv',out/'proof.ys']
(out/'results.json').write_text(json.dumps({'passed':rc==0,'claim':'Both active enables match original cycle/strobe and decode every cycle under arbitrary request, response, ACK, ERR and reset inputs; no latency change.','sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')
if rc: raise SystemExit('Decode proof failed: '+str(out/'proof.log'))
print('PASS temporal induction: both Wishbone active enables, all cycles, arbitrary bus/reset')
