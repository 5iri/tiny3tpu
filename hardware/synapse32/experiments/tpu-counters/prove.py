#!/usr/bin/env python3
"""Prove full wrapper state/output equivalence with narrow phase counters."""
import argparse,hashlib,json,subprocess
from pathlib import Path
from prepare import ROOT,HERE,patch
p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--n',type=int,default=4);a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True);n=a.n
original=ROOT/'multi-core/tpu_core_wrapper.sv'
def abstract_array(source):
    start=source.index('    systolic_array #(')
    end=source.index('    always @(*)',start)
    block=source[start:end]
    assert '.a_in(a_in_flat)' in block and '.b_in(b_in_flat)' in block and '.clear(clear)' in block
    source=source[:start]+'    assign c_out_flat = formal_array_result;\n\n'+source[end:]
    anchor='    input  wire                         clk,'
    assert source.count(anchor)==1
    return source.replace(anchor,'    input wire [N*N*CW-1:0] formal_array_result,\n'+anchor)
(out/'gold.sv').write_text(abstract_array(original.read_text()).replace('module tpu_core_wrapper','module gold'))
(out/'gate.sv').write_text(abstract_array(patch(original.read_text())).replace('module tpu_core_wrapper','module gate'))
w=max(1,(n-1).bit_length())
h=f'''module equiv(input [{n*n*32-1}:0] formal_array_result,input clk,rst,start,load_en,load_sel,c_rd_en,input [{w-1}:0] load_row,load_col,c_rd_row,c_rd_col,input signed [7:0] load_data,output same);
wire gb,gd,cb,cd;wire signed [31:0] gr,cr;
gold #(.N({n})) gold(.formal_array_result(formal_array_result),.clk(clk),.rst(rst),.start(start),.busy(gb),.done(gd),.load_en(load_en),.load_sel(load_sel),.load_row(load_row),.load_col(load_col),.load_data(load_data),.c_rd_en(c_rd_en),.c_rd_row(c_rd_row),.c_rd_col(c_rd_col),.c_rd_data(gr));
gate #(.N({n})) gate(.formal_array_result(formal_array_result),.clk(clk),.rst(rst),.start(start),.busy(cb),.done(cd),.load_en(load_en),.load_sel(load_sel),.load_row(load_row),.load_col(load_col),.load_data(load_data),.c_rd_en(c_rd_en),.c_rd_row(c_rd_row),.c_rd_col(c_rd_col),.c_rd_data(cr));
'''
checks=['gb==cb','gd==cd','gr==cr']
for sig in ['state','clear','t_count','flush_count']: checks.append(f'gold.{sig}==gate.{sig}')
checks += [f'gold.t_count < {2*n-1}',f'gold.flush_count < {2*n}']
for i in range(n):
 for sig in ['a_in','b_in']:checks.append(f'gold.{sig}[{i}]==gate.{sig}[{i}]')
 for j in range(n):
  for sig in ['a_spm','b_spm','c_spm']:checks.append(f'gold.{sig}[{i}][{j}]==gate.{sig}[{i}][{j}]')
h+='assign same='+' && '.join('('+c+')' for c in checks)+';\nendmodule\n';(out/'harness.sv').write_text(h)
rtl=[out/'gold.sv',out/'gate.sv',ROOT/'systolic_array/rtl/NxN_systolic_array.v',ROOT/'systolic_array/rtl/pe.v',out/'harness.sv']
s='read_slang --top equiv '+' '.join(map(str,rtl))+'\nprep -top equiv; flatten; memory_map; opt; async2sync; opt; check -assert; sat -seq 3 -tempinduct -maxsteps 12 -set-init-zero -prove same 1 -verify;\n';(out/'proof.ys').write_text(s)
with (out/'proof.log').open('w') as log:
 rc=subprocess.run(['/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys','-Q','-T','-m','slang','-s',str(out/'proof.ys')],stdout=log,stderr=subprocess.STDOUT).returncode
paths=[Path(__file__),HERE/'prepare.py',original,*rtl,out/'proof.ys']
(out/'results.json').write_text(json.dumps({'passed':rc==0,'n':n,'claim':'Wrapper state/output and all array inputs identical for shared arbitrary array results; array RTL unchanged. Compositional proof avoids unchanged multipliers.','sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')
if rc:raise SystemExit('FAIL TPU counter proof: '+str(out/'proof.log'))
print('PASS full TPU wrapper state/output equivalence, N=',n)
