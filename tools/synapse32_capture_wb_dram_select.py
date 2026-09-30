#!/usr/bin/env python3
"""Retiming of one exact Wishbone region predicate on its existing address edge."""
import argparse,copy,hashlib,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(p):
 d=json.loads(p.read_text());assert d['passed']
 for key in ['sha256','output_sha256']:
  for n,h in d.get(key,{}).items():assert digest(n)==h,(p,n)
 return d
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();parent=a.parent.resolve();out=a.out.resolve();assert not out.exists()
prior=check(parent/'iteration-integrity.json');mapping=check(parent/'mapping.json');source=parent/'board/soc.json';gold=json.loads(source.read_text());m=gold['modules']['kc705_synapse32_top'];cells=m['cells'];lo,hi=m['netnames']['wb_adr']['bits'][28:30]
def driver(bit):
 matches=[(n,c) for n,c in cells.items() if c['port_directions'].get('Q')=='output' and c['connections'].get('Q')==[bit]]
 assert len(matches)==1;return matches[0]
ln,lc=driver(lo);hn,hc=driver(hi)
assert lc['type']==hc['type']=='FDRE';assert lc['parameters']==hc['parameters']
assert set(lc['parameters'])=={'INIT'} and lc['parameters']['INIT'] in ['0','x']
assert all(lc['connections'][p]==hc['connections'][p] for p in ['C','CE','R'])
found=[]
for n,c in cells.items():
 if c['type']!='LUT2':continue
 ins=[c['connections']['I0'][0],c['connections']['I1'][0]]
 if set(ins)!={lo,hi}:continue
 init=int(c['parameters']['INIT'],2)
 if all(((init>>i)&1)==(((i>>ins.index(lo))&1) and not ((i>>ins.index(hi))&1)) for i in range(4)):found.append((n,c))
assert len(found)==1;name,old_lut=found[0];old_pred=old_lut['connections']['O'][0]
out.mkdir();proof=out/'predicate-proof';proof.mkdir()
yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v'
init=lc['parameters']['INIT'];bits=old_lut['parameters']['INIT'];pins={f'I{i}':('lo' if old_lut['connections'][f'I{i}']==[lo] else 'hi') for i in range(2)}
text='module proof(input clk,rst,ce,dlo,dhi,output same);\nwire qlo,qhi,gold_pred,predicate_d,actual_pred;\n'
for label in ['lo','hi']:text+=f"FDRE #(.INIT(1'b{init})) g_{label}(.C(clk),.CE(ce),.R(rst),.D(d{label}),.Q(q{label}));\n"
text+=f"LUT2 #(.INIT(4'b{bits})) old_decode(.I0(q{pins['I0']}),.I1(q{pins['I1']}),.O(gold_pred));\n"
text+=f"LUT2 #(.INIT(4'b{bits})) new_decode(.I0(d{pins['I0']}),.I1(d{pins['I1']}),.O(predicate_d));\n"
text+=f"FDRE #(.INIT(1'b{init})) captured(.C(clk),.CE(ce),.R(rst),.D(predicate_d),.Q(actual_pred));\nassign same=gold_pred==actual_pred;\nendmodule\n"
v=proof/'proof.v';v.write_text(text);ys=proof/'proof.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof; flatten; opt; check -assert; sat -seq 3 -set-init-zero -tempinduct -maxsteps 8 -prove same 1 -verify;\n')
with (proof/'proof.log').open('w') as log:subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=60)
pp=[source,lib,yosys,Path(__file__).resolve(),v,ys,proof/'proof.log']
(proof/'results.json').write_text(json.dumps(dict(passed=True,claim='Temporal induction of the actual FDRE/LUT2 pattern from common cleared/reset state, with arbitrary data, common enable and repeated synchronous resets. Initial unknown states before reset are not claimed equivalent. Both address FFs have exactly identical C/CE/R and INIT; the predicate uses that same capture edge. No transaction or CPU latency is added.',address_registers=[ln,hn],lut=name,added_latency_cycles=0,sha256={str(q):digest(q) for q in pp}),indent=2)+'\n')
actual=copy.deepcopy(gold);am=actual['modules']['kc705_synapse32_top'];ac=am['cells'];allbits=[b for c in cells.values() for bs in c['connections'].values() for b in bs if isinstance(b,int)]+[b for n in m['netnames'].values() for b in n['bits'] if isinstance(b,int)]+[b for n in m['ports'].values() for b in n['bits'] if isinstance(b,int)];newbit=max(allbits)+1
new_name='$tiny3tpu$wb_dram_select_q';netname='wb_dram_select_capture_d';assert new_name not in ac and netname not in am['netnames']
for pin,label in pins.items():ac[name]['connections'][pin]=copy.deepcopy((lc if label=='lo' else hc)['connections']['D'])
ac[name]['connections']['O']=[newbit]
ff=copy.deepcopy(lc);ff['connections']['D']=[newbit];ff['connections']['Q']=[old_pred];ff['attributes']['keep']='1';ff['attributes']['hdlname']=new_name;ac[new_name]=ff
am['netnames'][netname]=dict(hide_name=0,bits=[newbit],attributes={})
restored=copy.deepcopy(actual);rm=restored['modules']['kc705_synapse32_top'];rm['cells'][name]=old_lut;del rm['cells'][new_name];del rm['netnames'][netname];assert restored==gold
assert all(set(c['connections'])<=set(c['port_directions']) for c in ac.values())
board=out/'board';board.mkdir();(board/'soc.json').write_text(json.dumps(actual,separators=(',',':'))+'\n')
for n in ['kc705.xdc','firmware.hex','synth.ys']:(board/n).write_bytes((parent/'board'/n).read_bytes())
inputs=[source,parent/'mapping.json',parent/'iteration-integrity.json',proof/'results.json',Path(__file__).resolve()]+[parent/'board'/n for n in ['kc705.xdc','firmware.hex','synth.ys']]
record=dict(passed=True,kind='captured_wb_dram_predicate',parent=str(parent),source=str(source),proof=str(proof/'results.json'),lut=name,original_lut=old_lut,candidate_lut=ac[name],added_cell=new_name,added_cell_data=ff,added_net=netname,added_net_data=am['netnames'][netname],address_registers=[ln,hn],all_other_netlist_content_exact=True,added_latency_cycles=0,firmware_identical=True,constraints_identical=True,
 scope='One existing LUT2 moves before an added predicate FDRE on the exact existing address-capture edge. Every existing consumer stays on its original net. All other cells/connections/parameters are byte-exact by structural reconstruction. Derived from real parent synthesis, with primitive induction instead of a fresh RTL simulation. Copied synth.ys is provenance only; do not rerun its parent paths.',checked_manifests=[dict(path=str(q),sha256=digest(q)) for q in [parent/'mapping.json',parent/'iteration-integrity.json',proof/'results.json']],sha256={str(q):digest(q) for q in inputs},output_sha256={str(q):digest(q) for q in board.iterdir()},full_soc_timing_accepted=False)
(out/'mapping.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS captured Wishbone DRAM select; one FF, same capture edge, exact remaining netlist')
