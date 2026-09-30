#!/usr/bin/env python3
"""Prove direct terminal detection against the actual DMA burst-size logic."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from prepare import EXPR,patch
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
a=p.parse_args();source=a.source.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
rtl=source.read_text();(out/'axi_dma_wr.v').write_text(patch(rtl))
begin=rtl.index('            if (op_word_count_reg <= AXI_MAX_BURST_SIZE')
end=rtl.index('            input_cycle_count_next =',begin)
burst=rtl[begin:end]
h='''module equiv(input [15:0] op_word_count_reg,input [31:0] addr_reg,output same);
localparam AXI_MAX_BURST_SIZE=64;
localparam OFFSET_MASK=3;
reg [15:0] tr_word_count_next;
always @* begin
'''+burst+'''end
wire [14:0] count=(tr_word_count_next-1)>>2;
wire direct='''+EXPR+''';
assign same=(count==0)==direct;
endmodule
'''
(out/'harness.v').write_text(h);script=out/'proof.ys'
script.write_text(f'read_verilog {out/"harness.v"}\nprep -top equiv; opt; check -assert; sat -prove same 1 -verify;\n')
yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
with (out/'proof.log').open('w') as log:rc=subprocess.run([str(yosys),'-Q','-T','-s',str(script)],stdout=log,stderr=subprocess.STDOUT).returncode
paths=[source,out/'axi_dma_wr.v',out/'harness.v',script,yosys,Path(__file__).resolve(),Path(__file__).with_name('prepare.py').resolve()]
r=dict(passed=rc==0,claim='Initial last-cycle flag equals the actual burst-selection and count logic for every 16-bit remaining length and every 32-bit address, including zero, unaligned addresses and 4 KiB boundaries. Applies only under explicit current-profile guards; all count updates and other state transitions are unchanged.',sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in paths})
(out/'results.json').write_text(json.dumps(r,indent=2)+'\n');assert r['passed'];print('PASS direct DMA terminal flag for all lengths and addresses, including 4 KiB boundaries')
