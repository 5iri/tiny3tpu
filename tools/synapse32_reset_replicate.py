#!/usr/bin/env python3
"""Replicate the existing final reset stage using baseline placement load groups."""
import argparse,copy,hashlib,json,re,shutil
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--board',type=Path,required=True);p.add_argument('--placement',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
a=p.parse_args();base=a.board.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
gold=json.loads((base/'soc.json').read_text());design=copy.deepcopy(gold);m=design['modules']['kc705_synapse32_top'];r=next(iter(json.loads(a.placement.read_text())['modules'].values()))
name='memory.FDPE_3';driver=m['cells'][name];assert driver['type']=='FDPE' and driver['parameters']['INIT']=='1'
reset=driver['connections']['Q'][0];assert m['netnames']['rst']['bits']==[reset]
nextbit=1+max(b for c in m['cells'].values() for bs in c['connections'].values() for b in bs if isinstance(b,int))
groups={}
for n,c in m['cells'].items():
 for port,bits in c['connections'].items():
  if reset not in bits or c['port_directions'][port]!='input':continue
  bel=r['cells'].get(n,{}).get('attributes',{}).get('NEXTPNR_BEL','')
  xy=re.search(r'SLICE_X(\d+)Y(\d+)',bel)
  group=f'x{int(xy[1])//32}_y{int(xy[2])//50}' if xy else 'shared'
  groups.setdefault(group,[]).append((n,port))
copybits=[];copynames=[]
for i,(group,loads) in enumerate(sorted(groups.items())):
 bit=nextbit+i;copybits.append(bit);newname='reset_copy_'+group;copynames.append(newname)
 clone=copy.deepcopy(driver);clone['connections']['Q']=[bit];clone['attributes']['hdlname']=newname
 clone['attributes']['keep']='1'
 m['cells'][newname]=clone
 m['netnames'][newname]={'hide_name':0,'bits':[bit],'attributes':{}}
 for n,port in loads:m['cells'][n]['connections'][port]=[bit if b==reset else b for b in m['cells'][n]['connections'][port]]
# Collapse the equivalent copies and require exact equality to the entire original design.
collapsed=copy.deepcopy(design);cm=collapsed['modules']['kc705_synapse32_top']
for n in copynames:del cm['cells'][n];del cm['netnames'][n]
for c in cm['cells'].values():
 for port,bits in c['connections'].items():
  if c['port_directions'][port]=='input':c['connections'][port]=[reset if b in copybits else b for b in bits]
assert collapsed==gold
for n in copynames:
 c=copy.deepcopy(m['cells'][n]);c['connections']['Q']=driver['connections']['Q'];c['attributes']=driver['attributes'];assert c==driver
(out/'soc.json').write_text(json.dumps(design))
for n in ['firmware.hex','kc705.xdc','synth.ys']:shutil.copyfile(base/n,out/n)
inputs=[base/'soc.json',a.placement.resolve(),base/'firmware.hex',base/'kc705.xdc',Path(__file__).resolve()]
record={'structural_equivalence_passed':True,'claim':'All final reset-stage copies have identical primitive type, INIT and C/CE/D/PRE connections. Collapsing their output nets yields exact original design. No reset stage added; no other netlist changes.',
 'limitation':'Digital structural equivalence, not analog metastability, reset recovery/removal or DDR hardware signoff.', 'groups':{g:len(v) for g,v in groups.items()},'sha256':{str(n):hashlib.sha256(n.read_bytes()).hexdigest() for n in inputs},'netlist_sha256':hashlib.sha256((out/'soc.json').read_bytes()).hexdigest()}
(out/'replication.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'copies':len(groups),'loads':sum(map(len,groups.values())),'maximum_group_loads':max(map(len,groups.values())),'structural_equivalence_passed':True}))
