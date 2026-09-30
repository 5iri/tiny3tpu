#!/usr/bin/env python3
"""Replicate the existing final reset FF with identical state equations, separating sink classes."""
import argparse,copy,hashlib,json,subprocess
from collections import Counter
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--board',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
board=a.board.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
hashfile=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
original=json.loads((board/'soc.json').read_text());candidate=copy.deepcopy(original)
m=candidate['modules']['kc705_synapse32_top'];oldbit=m['netnames']['rst']['bits'][0]
drivers=[n for n,c in m['cells'].items() if any(c['port_directions'][p]=='output' and oldbit in b for p,b in c['connections'].items())]
assert drivers==['memory.FDPE_3'];name=drivers[0];driver=m['cells'][name]
assert driver['type']=='FDPE' and driver['parameters']=={'INIT':'1'}
assert driver['connections']['CE']==['1'] and driver['connections']['Q']==[oldbit]
assert oldbit not in sum([b for p,b in driver['connections'].items() if p!='Q'],[])
used_bits={b for c in m['cells'].values() for bs in c['connections'].values() for b in bs if isinstance(b,int)}
used_bits.update(b for collection in ('ports','netnames') for obj in m[collection].values() for b in obj['bits'] if isinstance(b,int))
maxbit=max(used_bits)
clones={};changes=[];groups=Counter()
for group in ('asynchronous','synchronous'):
 newname=name+'_'+group;assert newname not in m['cells']
 maxbit+=1;assert maxbit not in used_bits;clones[group]=(newname,maxbit)
 c=copy.deepcopy(driver);c['connections']['Q']=[maxbit];c['attributes']['hdlname']='memory FDPE_3_'+group;c['attributes']['keep']='1'
 m['cells'][newname]=c;m['netnames']['rst_'+group]={'hide_name':0,'bits':[maxbit],'attributes':{'keep':'1'}}
for n,c in m['cells'].items():
 for pin,bits in c['connections'].items():
  if c['port_directions'][pin]!='input' or oldbit not in bits:continue
  group='asynchronous' if c['type'] in ('FDCE','FDPE') and pin in ('CLR','PRE') else 'synchronous' if (c['type'] in ('FDRE','FDSE') and pin in ('R','S')) or (c['type']=='DSP48E1' and pin.startswith('RST')) else 'logic'
  groups[group]+=bits.count(oldbit)
  if group=='logic':continue
  changes.append(dict(cell=n,port=pin,before=bits.copy(),after=[clones[group][1] if b==oldbit else b for b in bits],group=group))
  c['connections'][pin]=changes[-1]['after']
# Reverse all edits and demand exact full-design identity, including unrelated modules.
restored=copy.deepcopy(candidate);rm=restored['modules']['kc705_synapse32_top']
for edit in changes:rm['cells'][edit['cell']]['connections'][edit['port']]=edit['before']
for group,(newname,newbit) in clones.items():
 c=copy.deepcopy(rm['cells'].pop(newname));c['connections']['Q']=[oldbit];c['attributes']=copy.deepcopy(driver['attributes']);assert c==driver
 del rm['netnames']['rst_'+group]
assert restored==original
(out/'soc.json').write_text(json.dumps(candidate)+'\n')
for f in ('firmware.hex','kc705.xdc','synth.ys'):(out/f).write_bytes((board/f).read_bytes())
# Use the actual shipped primitive model, preserving INIT and async PRE semantics.
yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=Path('/Users/siriboi/.apio/packages/oss-cad-suite/share/yosys/xilinx/cells_sim.v')
(out/'proof.v').write_text('''module test(input clk,pre,d,output same);
wire a,b,c;
FDPE #(.INIT(1'b1)) original(.C(clk),.CE(1'b1),.D(d),.PRE(pre),.Q(a));
FDPE #(.INIT(1'b1)) sync_copy(.C(clk),.CE(1'b1),.D(d),.PRE(pre),.Q(b));
FDPE #(.INIT(1'b1)) async_copy(.C(clk),.CE(1'b1),.D(d),.PRE(pre),.Q(c));
assign same=(a==b)&&(a==c);
endmodule
''')
(out/'proof.ys').write_text(f'read_verilog {lib} {out/"proof.v"}\nhierarchy -top test; proc; flatten; async2sync; opt; check -assert; sat -seq 2 -tempinduct -prove same 1 -verify;\n')
with (out/'proof.log').open('w') as log:rc=subprocess.run([str(yosys),'-Q','-T','-s',str(out/'proof.ys')],stdout=log,stderr=subprocess.STDOUT).returncode
paths=[board/f for f in ('soc.json','firmware.hex','kc705.xdc','synth.ys')]+[yosys,lib,Path(__file__).resolve()]
record=dict(passed=rc==0,scope='Post-synthesis physical fanout optimization. Two final-stage reset FF replicas have exactly the original INIT, D, CE, clock and asynchronous PRE. No extra reset stage or cycle. Only sink connections listed here change; reversing all changes restores the entire original design exactly. Digital equivalence does not validate physical reset recovery/removal or metastability behavior.',parent_board=str(board),original_driver=name,clones=clones,sink_counts=groups,changes=changes,full_design_reverse_exact=True,new_bits_unique_in_all_original_ports_cells_and_netnames=True,sha256={str(q):hashfile(q) for q in paths},output_sha256={str(q):hashfile(q) for q in out.iterdir() if q.is_file()},full_soc_timing_accepted=False)
(out/'replica-manifest.json').write_text(json.dumps(record,indent=2)+'\n');assert record['passed'];print('PASS reset replica primitive proof and exact full-design reverse check;',dict(groups))
