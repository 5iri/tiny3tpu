#!/usr/bin/env python3
"""Replicate reset only for clustered combinational loads, preserving the verified layout."""
import argparse,copy,hashlib,json,os,re,subprocess
from pathlib import Path
from synapse32_packed_equivalence import verify_packed_logic as verify_original
from synapse32_ddr_decode_equivalence import verify_packed_logic, CONE, TARGET
from synapse32_reset_copies_equivalence import collapse_reset_copy
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--groups',type=int,default=4);p.add_argument('--extra-moves',type=Path,required=True);a=p.parse_args();assert 1<=a.groups<=8
root=Path(__file__).resolve().parents[1];h=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
source=root/'build-ddr-pre-fixup-parallel8/pre-fixup.json';sm=source.with_name('manifest.json');s=json.loads(sm.read_text());assert s['passed'] and s['final_checkpoint_exact'] and h(source)==s['pre_fixup_sha256']
parent=Path(s['parent']);r=json.loads(parent.read_text());checkpoint=Path(s['original_checkpoint']);layout=root/'build-ddr-local-legal-ddr-mid-final/placed.json';lm=layout.with_name('manifest.json');l=json.loads(lm.read_text());assert l['passed'] and l['legal_placement_verified'] and h(layout)==l['placed_sha256']
ce=root/'build-ddr-route-local-reset-copy-seed2/manifest.json';cr=json.loads(ce.read_text());assert cr['parent']==str(parent) and cr['clock_targets_restored'] and cr['inputs_unchanged'];xdc=Path(cr['command'][cr['command'].index('--xdc')+1])
for d in [s,r,l,cr]:
 for n,v in d['sha256'].items():assert h(n)==v,n
old=json.loads(checkpoint.read_text());placed=json.loads(layout.read_text());assert verify_original(old,placed)
gold=json.loads(source.read_text());gate=copy.deepcopy(gold);m=gate['modules']['top'];cells=m['cells'];before=old['modules']['top']['cells'];changes={}
for n,c in cells.items():
 at=placed['modules']['top']['cells'][n]['attributes']['NEXTPNR_BEL'];c['attributes']['NEXTPNR_BEL']=at
 if at!=before[n]['attributes']['NEXTPNR_BEL']:changes[n]=[before[n]['attributes']['NEXTPNR_BEL'],at]
# Compose the three-level DDR predicate into the existing final LUT.
old_target=copy.deepcopy(cells[TARGET])
internal={cells[n]['connections']['O6'][0] for n in CONE}
leaves=sorted({bs[0] for n in CONE for pin,bs in cells[n]['connections'].items() if cells[n]['port_directions'][pin]=='input'}-internal)
assert len(leaves)==5
init=0
for assignment in range(32):
    values={bit:(assignment>>i)&1 for i,bit in enumerate(leaves)}
    for n in CONE:
        cell=cells[n];size=int(cell['attributes']['X_ORIG_TYPE'][3:])
        ports={cell['attributes']['X_ORIG_PORT_'+pin]:bs[0] for pin,bs in cell['connections'].items()}
        index=sum(values[ports['I'+str(i)]]<<i for i in range(size))
        values[ports['O']]=(int(cell['parameters']['INIT'],2)>>index)&1
    init|=values[cells[TARGET]['connections']['O6'][0]]<<assignment
cell=cells[TARGET];output=cell['connections']['O6']
cell['parameters']['INIT']=format(init,'032b');cell['attributes']['X_ORIG_TYPE']='LUT5'
for key in list(cell['attributes']):
    if key.startswith('X_ORIG_PORT_'):del cell['attributes'][key]
cell['connections']={'O6':output};cell['port_directions']={'O6':'output'};cell['attributes']['X_ORIG_PORT_O6']='O'
for i,bit in enumerate(leaves):
    pin='A'+str(i+1);cell['connections'][pin]=[bit];cell['port_directions'][pin]='input';cell['attributes']['X_ORIG_PORT_'+pin]='I'+str(i)
extra=a.extra_moves.resolve();moves=json.loads(extra.read_text());assert 1<=len(moves)<=8
for name,bel in moves.items():
    cell=cells[name];at=cell['attributes'];assert cell['type']=='SLICE_LUTX'
    assert 'CONSTR_PARENT' not in at
    if at.get('CONSTR_CHILDREN'):
        children=at['CONSTR_CHILDREN'].split(';');assert len(children)==1
        child=cells[children[0]];ca=child['attributes']
        assert child['type']=='SLICE_FFX' and ca['CONSTR_PARENT']==name
        assert int(ca['CONSTR_X'],2)==int(ca['CONSTR_Y'],2)==0 and int(ca['CONSTR_Z'],2)==2
        assert int(ca['CONSTR_ABS_Z'],2)==0
        assert child['attributes']['NEXTPNR_BEL']==at['NEXTPNR_BEL'].replace('6LUT','FF')
        child_bel=bel.replace('6LUT','FF');assert child_bel!=bel
        changes[children[0]]=[before[children[0]]['attributes']['NEXTPNR_BEL'],child_bel]
        ca['NEXTPNR_BEL']=child_bel
    assert re.fullmatch(r'SLICE_X\d+Y\d+/[ABCD]6LUT',bel)
    changes[name]=[before[name]['attributes']['NEXTPNR_BEL'],bel];at['NEXTPNR_BEL']=bel
driver=cells['memory.FDPE_3'];reset=driver['connections']['Q'][0];assert driver['parameters']['INIT']=='1' and driver['attributes']['X_ORIG_TYPE']=='FDPE'
def xy(site):
 match=re.match(r'SLICE_X(\d+)Y(\d+)/',site);assert match,site
 return tuple(map(int,match.groups()))
loads=[];sites={}
for n,c in cells.items():
 bel=c['attributes']['NEXTPNR_BEL']
 if bel.startswith('SLICE_'):sites.setdefault(bel.split('/')[0],[]).append(c)
 if c['type'] not in ('SLICE_LUTX','F7MUX','F8MUX'):continue
 for pin,bits in c['connections'].items():
  if c['port_directions'][pin]=='input' and reset in bits:loads.append((n,pin,xy(bel)))
assert len(loads)>=100
# Deterministic farthest-point initialization, then geometric k-means.
points=[v[2] for v in loads];distance=lambda a,b:(a[0]-b[0])**2+(a[1]-b[1])**2
centers=[min(points)]
while len(centers)<a.groups:centers.append(max(points,key=lambda p:(min(distance(p,c) for c in centers),p)))
for _ in range(20):
 groups=[[x for x in loads if min(range(a.groups),key=lambda i:distance(x[2],centers[i]))==k] for k in range(a.groups)]
 new=[(sum(x[2][0] for x in g)/len(g),sum(x[2][1] for x in g)/len(g)) for g in groups];assert all(groups)
 if new==centers:break
 centers=new
# Use existing real slice sites with no FF, RAM or carry occupants, so the new
# asynchronous FF gets its own slice control set. Original legality still runs.
free=[site for site,cs in sites.items() if all(c['type'] in ('SLICE_LUTX','F7MUX','F8MUX') and c['attributes'].get('X_ORIG_TYPE') in ('LUT1','LUT2','LUT3','LUT4','LUT5','LUT6','LUT6_2','MUXF7','MUXF8') for c in cs)]
used_bits={b for c in cells.values() for bs in c['connections'].values() for b in bs if isinstance(b,int)}|{b for v in m['netnames'].values() for b in v['bits'] if isinstance(b,int)}|{b for v in m.get('ports',{}).values() for b in v['bits'] if isinstance(b,int)}
bit=max(used_bits);replicas=[]
for k,g in enumerate(groups):
 site=min(free,key=lambda s:(distance(xy(s+'/AFF'),centers[k]),s));free.remove(site);bel=site+'/AFF';bit+=1;assert bit not in used_bits
 name=f'memory.reset_logic_cluster{k}';assert name not in cells and name not in m['netnames']
 clone=copy.deepcopy(driver);clone['connections']['Q']=[bit];clone['attributes']['NEXTPNR_BEL']=bel;cells[name]=clone;m['netnames'][name]={'hide_name':0,'bits':[bit],'attributes':{}}
 sinks=[]
 for n,pin,pos in g:
  cells[n]['connections'][pin]=[bit if b==reset else b for b in cells[n]['connections'][pin]];sinks.append([n,pin])
 replicas.append(dict(driver='memory.FDPE_3',copy=name,loads=sinks));changes[name]=[None,bel]
assert len({c['attributes']['NEXTPNR_BEL'] for c in cells.values()})==len(cells)
evidence=dict(replicas=replicas,claim='Parallel identical FDPE final stages drive only combinational reset loads; no added reset cycle or altered state equation.')
for c in cells.values():c['attributes']['BEL_STRENGTH']=format(5,'032b')
for mod in gate['modules'].values():
 mod['settings']['placer']='sa';mod['settings']['placer1/startTemp']='0.000000'
 for net in mod['netnames'].values():net.get('attributes',{}).pop('ROUTING',None)
check=collapse_reset_copy(gate,evidence)
check['modules']['top']['cells'][TARGET]=copy.deepcopy(old_target)
for mn,mod in check['modules'].items():
 mod['settings']=gold['modules'][mn]['settings']
 for n,c in mod['cells'].items():c['attributes']=gold['modules'][mn]['cells'][n]['attributes']
 for n,net in mod['netnames'].items():net['attributes']=gold['modules'][mn]['netnames'][n]['attributes']
assert check==gold
out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);inp=out/'input.json';inp.write_text(json.dumps(gate,separators=(',',':'))+'\n')
cmd=r['command'].copy()
for flag,value in [('--json',inp),('--xdc',xdc),('--write',out/'placed.json'),('--report',out/'report.json'),('--log',out/'place.log')]:cmd[cmd.index(flag)+1]=str(value)
cmd+=['--no-pack','--no-route','--placer','sa','--starttemp','0'];assert not any(x in cmd for x in ['--force','--timing-allow-fail','--ignore-loops','--fasm'])
sha=dict(r['sha256']);sha.update({str(q):h(q) for q in [source,sm,parent,checkpoint,layout,lm,ce,xdc,inp,extra,Path(__file__).resolve(),root/'tools/synapse32_reset_copies_equivalence.py',root/'tools/synapse32_reset_copy_equivalence.py',root/'tools/synapse32_packed_equivalence.py',root/'tools/synapse32_ddr_decode_equivalence.py']})
record=dict(parent=str(parent),original_checkpoint=str(checkpoint),command=cmd,sha256=sha,requested_placement_changes=changes,input_logic_exact=True,reset_replication=evidence,ddr_decode_composition=dict(target=TARGET,cone=CONE,exhaustive_assignments=32,cycle_changes=0),scope=__doc__,full_soc_timing_accepted=False)
manifest=out/'manifest.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
print('Checking clusters',[(r['copy'],len(r['loads']),changes[r['copy']][1]) for r in replicas],flush=True)
with (out/'console.log').open('w') as log:rc=subprocess.run(cmd,env={k:v for k,v in os.environ.items() if not k.startswith(('NEXTPNR_','TINY3TPU_'))},stdout=log,stderr=subprocess.STDOUT).returncode
record['exit_code']=rc;record['inputs_unchanged']=all(h(n)==v for n,v in sha.items())
if rc==0:
 new=json.loads((out/'placed.json').read_text());after=new['modules']['top']['cells'];actual={n:[before[n]['attributes']['NEXTPNR_BEL'] if n in before else None,c['attributes']['NEXTPNR_BEL']] for n,c in after.items() if n not in before or before[n]['attributes']['NEXTPNR_BEL']!=c['attributes']['NEXTPNR_BEL']}
 record.update(placement_changes=actual,requested_placement_exact=actual==changes,packed_logic_unchanged=verify_packed_logic(old,collapse_reset_copy(new,evidence)),shared_cells=len(set(before)&set(after)),checkpoint_cells=len(after),routed_cells=len(before),placed_sha256=h(out/'placed.json'))
 record['legal_placement_verified']=record['requested_placement_exact'] and record['packed_logic_unchanged']
record['passed']=rc==0 and record['inputs_unchanged'] and record.get('legal_placement_verified',False);manifest.write_text(json.dumps(record,indent=2)+'\n');assert record['passed'],manifest
print('PASS original placement legality, exact requested locations and collapsed logical equivalence')
