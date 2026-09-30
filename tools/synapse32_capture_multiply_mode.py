#!/usr/bin/env python3
"""Capture multiplier signedness on the existing instruction register edge."""
import argparse,copy,hashlib,json,subprocess
from pathlib import Path
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();parent=a.parent.resolve();out=a.out.resolve();assert not out.exists()
source=parent/'board/soc.json';gold=json.loads(source.read_text());m=gold['modules']['kc705_synapse32_top'];cells=m['cells'];ids=m['netnames']['soc.cpu.ex_unit_inst0.alu_inst.instr_id']['bits'];assert len(ids)==7
registers=[]
for bit in ids:
 matches=[(n,c) for n,c in cells.items() if c['connections'].get('Q')==[bit] and c['port_directions'].get('Q')=='output'];assert len(matches)==1;registers.append(matches[0])
base=registers[0][1];clock=base['connections']['C'];enable=base['connections']['CE'];reset=base['connections'].get('PRE',base['connections'].get('CLR'));reset_word=0
for i,(n,c) in enumerate(registers):
 assert c['type'] in ['FDPE','FDCE'] and c['parameters']=={'INIT':'x'}
 assert c['connections']['C']==clock and c['connections']['CE']==enable and c['connections'].get('PRE',c['connections'].get('CLR'))==reset
 reset_word|=(c['type']=='FDPE')<<i
assert reset_word==11
outputs={}
for n,c in cells.items():
 for port,bits in c['connections'].items():
  if c['port_directions'][port]=='output':
   for b in bits:outputs.setdefault(b,[]).append((n,c))
def evaluate(bit,values,visited):
 if bit in values:return values[bit]
 if bit in ['0','1']:return int(bit)
 matches=outputs.get(bit,[]);assert len(matches)==1;name,c=matches[0];visited.add(name)
 if c['type']=='INV':return 1-evaluate(c['connections']['I'][0],values,visited)
 assert c['type'].startswith('LUT');width=int(c['type'][3:]);assert c['connections']['O']==[bit]
 index=sum(evaluate(c['connections'][f'I{i}'][0],values,visited)<<i for i in range(width));return (int(c['parameters']['INIT'],2)>>index)&1
specs=[('a',32554,7788,[49,50]),('b',32555,3484,[49])];cone_checks=[]
for label,root,raw,codes in specs:
 visited=set()
 for word in range(128):
  for sign in [0,1]:
   values={b:(word>>i)&1 for i,b in enumerate(ids)};values[raw]=sign
   assert evaluate(root,values,visited)==int(sign and word in codes)
 cone_checks.append(dict(label=label,root=root,raw=raw,codes=codes,cells=sorted(visited),exhaustive_cases=256))
out.mkdir();proof=out/'predicate-proof';proof.mkdir();yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v'
v=proof/'proof.v';lines=['module proof(input clk,rst,ce,input [6:0] d, input sa,sb, output same);','wire [6:0] q; wire fa,fb,da,db;']
for i,(_,c) in enumerate(registers):
 rp='PRE' if c['type']=='FDPE' else 'CLR';lines.append(f"{c['type']} #(.INIT(1'bx)) r{i}(.C(clk),.CE(ce),.{rp}(rst),.D(d[{i}]),.Q(q[{i}]));")
for label,root,raw,codes in specs:
 mask=sum(1<<code for code in codes)
 lines.extend([f"wire l{label}; LUT6 #(.INIT(64'h{mask:016x})) lut_{label}({','.join(f'.I{i}(d[{i}])' for i in range(6))},.O(l{label}));",f"LUT2 #(.INIT(4'b0010)) hi_{label}(.I0(l{label}),.I1(d[6]),.O(d{label}));",f"FDCE #(.INIT(1'bx)) f_{label}(.C(clk),.CE(ce),.CLR(rst),.D(d{label}),.Q(f{label}));"])
lines+=['assign same=((sa & fa)==(sa & ((q==49)||(q==50)))) && ((sb & fb)==(sb & (q==49)));','endmodule']
v.write_text('\n'.join(lines)+'\n');ys=proof/'proof.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof; flatten; opt; async2sync; opt; check -assert; sat -seq 4 -set-at 1 rst 1 -tempinduct -maxsteps 12 -prove same 1 -verify;\n')
with (proof/'proof.log').open('w') as log:subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=90)
actual=copy.deepcopy(gold);am=actual['modules']['kc705_synapse32_top'];ac=am['cells'];allbits=[b for c in cells.values() for bs in c['connections'].values() for b in bs if isinstance(b,int)]+[b for n in m['netnames'].values() for b in n['bits'] if isinstance(b,int)]+[b for n in m['ports'].values() for b in n['bits'] if isinstance(b,int)];fresh=max(allbits)+1;added={};changed={}
def add(name,typ,params,connections):
 global fresh
 assert name not in ac
 cell=dict(hide_name=0,type=typ,parameters=params,attributes={'keep':'1'},port_directions={k:('output' if k in ['O','Q'] else 'input') for k in connections},connections=connections);ac[name]=cell;added[name]=cell
for label,root,raw,codes in specs:
 low,d,q,neg=range(fresh,fresh+4);fresh+=4;mask=sum(1<<code for code in codes);prefix='$tiny3tpu$mul_mode_'+label
 add(prefix+'_low','LUT6',{'INIT':format(mask,'064b')},{**{f'I{i}':registers[i][1]['connections']['D'] for i in range(6)},'O':[low]})
 add(prefix+'_high','LUT2',{'INIT':'0010'},{'I0':[low],'I1':registers[6][1]['connections']['D'],'O':[d]})
 add(prefix+'_q','FDCE',{'INIT':'x'},{'C':clock,'CE':enable,'CLR':reset,'D':[d],'Q':[q]})
 add(prefix+'_sign','LUT2',{'INIT':'1000'},{'I0':[raw],'I1':[q],'O':[neg]})
 for name,c in cells.items():
  if c['type']!='DSP48E1':continue
  for port in ['A','B']:
   old=c['connections'][port]
   if root in old:
    assert all(i>=16 for i,b in enumerate(old) if b==root)
    changed.setdefault(name,copy.deepcopy(c));ac[name]['connections'][port]=[neg if b==root else b for b in ac[name]['connections'][port]]
 assert sum(root in c['connections'].get('A',[])+c['connections'].get('B',[]) for c in cells.values() if c['type']=='DSP48E1')==2
restored=copy.deepcopy(actual);rc=restored['modules']['kc705_synapse32_top']['cells']
for n,c in changed.items():rc[n]=c
for n in added:del rc[n]
assert restored==gold
board=out/'board';board.mkdir();(board/'soc.json').write_text(json.dumps(actual,separators=(',',':'))+'\n')
for n in ['kc705.xdc','firmware.hex','synth.ys']:(board/n).write_bytes((parent/'board'/n).read_bytes())
proofrecord=dict(passed=True,claim='Actual old LUT cones checked exhaustively for all instruction words and signs; actual FDPE/FDCE reset pattern and new LUT6/LUT2/FDCE model proved by temporal induction after initial reset. Async2sync provides digital clock-edge reset semantics, not analog reset signoff. No extra instruction or result cycle.',reset_word=reset_word,cone_checks=cone_checks,added_latency_cycles=0,sha256={str(q):digest(q) for q in [source,lib,yosys,Path(__file__).resolve(),v,ys,proof/'proof.log']})
(proof/'results.json').write_text(json.dumps(proofrecord,indent=2)+'\n')
record=dict(passed=True,kind='captured_multiplier_instruction_modes',parent=str(parent),source=str(source),proof=str(proof/'results.json'),instruction_registers=[n for n,c in registers],original_cells=changed,candidate_cells={n:ac[n] for n in changed},added_cells=added,added_latency_cycles=0,all_other_netlist_content_exact=True,new_rtl_synthesis_run=False,new_workload_simulation_run=False,full_soc_timing_accepted=False,checked_manifests=[dict(path=str(q),sha256=digest(q)) for q in [parent/'iteration-integrity.json',parent/'mapping.json',proof/'results.json']],sha256={str(q):digest(q) for q in [source,Path(__file__).resolve()]},output_sha256={str(q):digest(q) for q in board.iterdir()})
(out/'mapping.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS multiplier instruction-mode capture, 8 cells, no added latency')
