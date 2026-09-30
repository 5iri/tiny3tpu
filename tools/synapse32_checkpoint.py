#!/usr/bin/env python3
"""Reproduce and verify the pre-routing placement of a recorded full route."""
import argparse,hashlib,json,os,subprocess
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
parent=a.parent.resolve();r=json.loads(parent.read_text());digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert r['timing']['completed'] and r['inputs_unchanged']
for n,s in r['sha256'].items():assert digest(n)==s,n
out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);cmd=list(r['command'])
for flag,v in [('--write',out/'placed.json'),('--report',out/'report.json'),('--log',out/'place.log')]:cmd[cmd.index(flag)+1]=str(v)
cmd+=['--no-route'];sha=dict(r['sha256']);sha[str(Path(__file__).resolve())]=digest(__file__);sha[str(parent)]=digest(parent)
record={'parent':str(parent),'command':cmd,'sha256':sha,'scope':'Recreate the exact parent placement, stopping before routing.'}
(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
with (out/'console.log').open('w') as log:rc=subprocess.run(cmd,env={k:v for k,v in os.environ.items() if not k.startswith('NEXTPNR_')},stdout=log,stderr=subprocess.STDOUT).returncode
record['exit_code']=rc;record['inputs_unchanged']=all(digest(n)==s for n,s in sha.items())
if rc==0:
    old=json.loads(Path(r['command'][r['command'].index('--write')+1]).read_text())['modules']['top']['cells']
    new=json.loads((out/'placed.json').read_text())['modules']['top']['cells']
    shared=set(old)&set(new);changes={n:[old[n]['attributes'].get('NEXTPNR_BEL'),new[n]['attributes'].get('NEXTPNR_BEL')] for n in shared if old[n]['attributes'].get('NEXTPNR_BEL')!=new[n]['attributes'].get('NEXTPNR_BEL')}
    record.update({'shared_cells':len(shared),'checkpoint_cells':len(new),'routed_cells':len(old),'placement_changes':changes,'placed_sha256':digest(out/'placed.json')})
(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
print({k:v for k,v in record.items() if k not in ['sha256','command','placement_changes']});print('placement changes',len(record.get('placement_changes',{})))
if rc or not record['inputs_unchanged'] or record['placement_changes'] or record['shared_cells']<.95*record['checkpoint_cells']:raise SystemExit('Checkpoint does not reproduce the original placement')
