#!/usr/bin/env python3
"""Validate a bounded DDR placement edit through the original placer and fixup."""
import argparse,copy,hashlib,json,os,re,subprocess
from pathlib import Path
from synapse32_packed_equivalence import verify_packed_logic
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--pre-fixup',type=Path,required=True);p.add_argument('--clock-evidence',type=Path,required=True)
p.add_argument('--out',type=Path,required=True);p.add_argument('--macro-site');p.add_argument('--reset-site')
a=p.parse_args();digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
source=a.pre_fixup.resolve();sm=source.with_name('manifest.json');s=json.loads(sm.read_text())
assert s['passed'] and s['final_checkpoint_exact'] and s['inputs_unchanged'] and digest(source)==s['pre_fixup_sha256']
for n,h in s['sha256'].items():assert digest(n)==h,n
parent=Path(s['parent']);r=json.loads(parent.read_text());original_checkpoint=Path(s['original_checkpoint'])
assert digest(original_checkpoint)==s['sha256'][str(original_checkpoint)]
ce=a.clock_evidence.resolve();cr=json.loads(ce.read_text());assert cr['parent']==str(parent) and cr['clock_targets_restored'] and cr['inputs_unchanged']
xdc=Path(cr['command'][cr['command'].index('--xdc')+1]);assert digest(xdc)==cr['sha256'][str(xdc)]
gold=json.loads(source.read_text());gate=copy.deepcopy(gold);cells=gate['modules']['top']['cells'];changes={}
final_cells=json.loads(original_checkpoint.read_text())['modules']['top']['cells']
for n,c in cells.items():c['attributes']['NEXTPNR_BEL']=final_cells[n]['attributes']['NEXTPNR_BEL']
root='$auto$alumacc.cc:512:replace_alu$54593.genblk1.slice[0].genblk1.carry4'
if a.macro_site:
 match=re.fullmatch(r'SLICE_X(\d+)Y(\d+)',a.macro_site);assert match and int(match[1])%2==0,'Keep the original carry macro slice half'
 moved=[root]+cells[root]['attributes']['CONSTR_CHILDREN'].split(';')
 for name in moved:
  at=cells[name]['attributes'];old=at['NEXTPNR_BEL'];assert old.startswith('SLICE_X124Y9/')
  new=a.macro_site+'/'+old.split('/')[1];at['NEXTPNR_BEL']=new;changes[name]=[old,new]
if a.reset_site:
 assert re.fullmatch(r'SLICE_X\d+Y\d+/[ABCD]6LUT',a.reset_site)
 name='$abc$220657$auto$blifparse.cc:557:parse_blif$236909';at=cells[name]['attributes'];changes[name]=[at['NEXTPNR_BEL'],a.reset_site];at['NEXTPNR_BEL']=a.reset_site
bels=[c['attributes']['NEXTPNR_BEL'] for c in cells.values()];assert len(bels)==len(set(bels)),'Occupied destination'
for c in cells.values():c['attributes']['BEL_STRENGTH']=format(5,'032b')
for m in gate['modules'].values():
 m['settings']['placer']='sa';m['settings']['placer1/startTemp']='0.000000'
 for n in m['netnames'].values():n.get('attributes',{}).pop('ROUTING',None)
# Audit: only physical placement, binding strength, placement settings and
# pre-existing route annotations change. Logic/parameters/constraints stay exact.
check=copy.deepcopy(gate)
for mn,m in check['modules'].items():
 m['settings']=gold['modules'][mn]['settings']
 for n,c in m['cells'].items():c['attributes']=gold['modules'][mn]['cells'][n]['attributes']
 for n,net in m['netnames'].items():net['attributes']=gold['modules'][mn]['netnames'][n]['attributes']
assert check==gold
out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);inp=out/'input.json';inp.write_text(json.dumps(gate,separators=(',',':'))+'\n')
cmd=list(r['command'])
for flag,v in [('--json',inp),('--xdc',xdc),('--write',out/'placed.json'),('--report',out/'report.json'),('--log',out/'place.log')]:cmd[cmd.index(flag)+1]=str(v)
cmd+=['--no-pack','--no-route','--placer','sa','--starttemp','0']
assert not any(x in cmd for x in ['--force','--timing-allow-fail','--ignore-loops','--fasm'])
sha=dict(r['sha256']);sha.update({str(q):digest(q) for q in [parent,source,sm,original_checkpoint,ce,xdc,inp,Path(__file__).resolve(),Path(__file__).with_name('synapse32_packed_equivalence.py').resolve()]})
record={'parent':str(parent),'original_checkpoint':str(original_checkpoint),'command':cmd,'sha256':sha,'scope':'Only recorded DDR macro/reset-LUT locations change. Original SA legality and pin legalization run without bypass. Pre-fixup logic, parameters and macro constraints remain exact.','requested_placement_changes':changes,'input_logic_exact':True,'initial_placement':'Original post-fixup cell locations applied to exact pre-fixup logic before bounded edits'}
(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
with (out/'console.log').open('w') as f:rc=subprocess.run(cmd,env={k:v for k,v in os.environ.items() if not k.startswith('NEXTPNR_')},stdout=f,stderr=subprocess.STDOUT).returncode
record['exit_code']=rc;record['inputs_unchanged']=all(digest(n)==h for n,h in sha.items())
if rc==0:
 new=json.loads((out/'placed.json').read_text());old=json.loads(original_checkpoint.read_text())
 before=old['modules']['top']['cells'];after=new['modules']['top']['cells']
 actual={n:[before[n]['attributes']['NEXTPNR_BEL'],c['attributes']['NEXTPNR_BEL']] for n,c in after.items() if before[n]['attributes']['NEXTPNR_BEL']!=c['attributes']['NEXTPNR_BEL']}
 record['placement_changes']=actual;record['requested_placement_exact']=actual==changes
 record['packed_logic_unchanged']=verify_packed_logic(old,new)
 record.update(shared_cells=len(set(before)&set(after)),checkpoint_cells=len(after),routed_cells=len(before),placed_sha256=digest(out/'placed.json'))
 record['legal_placement_verified']=record['requested_placement_exact'] and record['packed_logic_unchanged']
record['passed']=rc==0 and record['inputs_unchanged'] and record.get('legal_placement_verified',False)
(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
print({k:v for k,v in record.items() if k not in ['sha256','command','requested_placement_changes','placement_changes']})
if not record['passed']:raise SystemExit('Local placement rejected')
