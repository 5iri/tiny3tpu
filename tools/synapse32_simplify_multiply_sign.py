#!/usr/bin/env python3
"""Factor actual CPU multiply sign cones into one shared prefix and two LUT4s."""
import argparse,copy,hashlib,json
from pathlib import Path
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();parent=a.parent.resolve();out=a.out.resolve();assert not out.exists();source=parent/'board/soc.json';gold=json.loads(source.read_text());m=gold['modules']['kc705_synapse32_top'];cells=m['cells'];ids=m['netnames']['soc.cpu.ex_unit_inst0.alu_inst.instr_id']['bits'];assert len(ids)==7
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
 assert c['type'].startswith('LUT');width=int(c['type'][3:]);assert c['connections']['O']==[bit];idx=sum(evaluate(c['connections'][f'I{i}'][0],values,visited)<<i for i in range(width));return (int(c['parameters']['INIT'],2)>>idx)&1
specs=[('a',32554,7788,[49,50],0x6000),('b',32555,3484,[49],0x2000)];checks=[]
for label,root,raw,codes,mask in specs:
 visited=set()
 for word in range(128):
  for sign in [0,1]:
   values={b:(word>>i)&1 for i,b in enumerate(ids)};values[raw]=sign;old=evaluate(root,values,visited);prefix=int((word>>2)==12);idx=(word&3)|(sign<<2)|(prefix<<3)
   assert old==((mask>>idx)&1)==int(sign and word in codes)
 checks.append(dict(label=label,root=root,raw=raw,codes=codes,mask=mask,cells={n:cells[n] for n in sorted(visited)},cases=256))
allbits=[b for c in cells.values() for bs in c['connections'].values() for b in bs if isinstance(b,int)]+[b for n in m['netnames'].values() for b in n['bits'] if isinstance(b,int)]+[b for n in m['ports'].values() for b in n['bits'] if isinstance(b,int)];fresh=max(allbits)+1
actual=copy.deepcopy(gold);ac=actual['modules']['kc705_synapse32_top']['cells'];name='$tiny3tpu$mul_signed_prefix';assert name not in ac
added=dict(hide_name=0,type='LUT5',parameters={'INIT':format(1<<12,'032b')},attributes={'keep':'1'},port_directions={**{f'I{i}':'input' for i in range(5)},'O':'output'},connections={**{f'I{i}':[ids[i+2]] for i in range(5)},'O':[fresh]});ac[name]=added;changes=[]
for label,root,raw,codes,mask in specs:
 target,old=outputs[root][0];new=copy.deepcopy(old);new['type']='LUT4';new['parameters']={'INIT':format(mask,'016b')};new['connections']={'I0':[ids[0]],'I1':[ids[1]],'I2':[raw],'I3':[fresh],'O':[root]};new['port_directions']={k:('output' if k=='O' else 'input') for k in new['connections']};ac[target]=new;changes.append(dict(target=target,original=old,candidate=new))
restored=copy.deepcopy(actual);rc=restored['modules']['kc705_synapse32_top']['cells'];del rc[name]
for r in changes:rc[r['target']]=r['original']
assert restored==gold
out.mkdir();proof=out/'predicate-proof';proof.mkdir();record=dict(passed=True,claim='Exhaustive actual old LUT/INV cone evaluation for every instruction word and operand sign. Shared instruction prefix plus two LUT4 truth tables produce identical multiply signs for all 512 cases. Pure combinational factoring: no state, reset, enable or latency changes.',checks=checks,added_latency_cycles=0,sha256={str(q):digest(q) for q in [source,Path(__file__).resolve()]});(proof/'results.json').write_text(json.dumps(record,indent=2)+'\n')
board=out/'board';board.mkdir();(board/'soc.json').write_text(json.dumps(actual,separators=(',',':'))+'\n')
for n in ['kc705.xdc','firmware.hex','synth.ys']:(board/n).write_bytes((parent/'board'/n).read_bytes())
record=dict(passed=True,kind='factored_multiply_sign_luts',parent=str(parent),source=str(source),proof=str(proof/'results.json'),changes=changes,added_cell=name,added_cell_data=added,added_latency_cycles=0,all_other_netlist_content_exact=True,new_rtl_synthesis_run=False,new_workload_simulation_run=False,full_soc_timing_accepted=False,checked_manifests=[dict(path=str(q),sha256=digest(q)) for q in [parent/'iteration-integrity.json',parent/'mapping.json',proof/'results.json']],sha256={str(q):digest(q) for q in [source,Path(__file__).resolve()]},output_sha256={str(q):digest(q) for q in board.iterdir()});(out/'mapping.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS all 512 original sign-cone cases; one shared LUT5 plus two LUT4s, no extra register')
