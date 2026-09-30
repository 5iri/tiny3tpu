#!/usr/bin/env python3
"""Route fixed logic with an explicit HeAP timing weight in netlist settings."""
import argparse,copy,hashlib,json,os,subprocess
from pathlib import Path
from synapse32_timing_report import summarize
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
p.add_argument('--weight',type=int,required=True);p.add_argument('--seed',type=int,default=4)
a=p.parse_args()
if not 1<=a.weight<=100: p.error('weight must be in [1,100]')
digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
parent=a.parent.resolve();r=json.loads(parent.read_text())
for name,sha in r['sha256'].items():
    if digest(name)!=sha:raise SystemExit('Stale source: '+name)
out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
cmd=list(r['command']);source=Path(cmd[cmd.index('--json')+1])
gold=json.loads(source.read_text());gate=copy.deepcopy(gold)
top=next(n for n,m in gate['modules'].items() if m.get('attributes',{}).get('top') in [1,'00000000000000000000000000000001'])
settings=gate['modules'][top].setdefault('settings',{})
assert 'placerHeap/timingWeight' not in settings
settings['placerHeap/timingWeight']=a.weight
netlist=out/'soc.json';netlist.write_text(json.dumps(gate,separators=(',',':'))+'\n')
check=json.loads(netlist.read_text());del check['modules'][top]['settings']['placerHeap/timingWeight']
if 'settings' not in gold['modules'][top]:del check['modules'][top]['settings']
assert check==gold, 'Only the placement setting may change'
for flag,value in [('--json',netlist),('--seed',a.seed),('--write',out/'routed.json'),('--report',out/'report.json'),('--log',out/'route.log')]:cmd[cmd.index(flag)+1]=str(value)
assert cmd[cmd.index('--freq')+1]=='100'
assert not any(f in cmd for f in ['--force','--timing-allow-fail','--ignore-loops','--fasm'])
sha=dict(r['sha256']);sha[str(netlist)]=digest(netlist);sha[str(Path(__file__).resolve())]=digest(__file__)
record={'parent':str(parent),'parent_sha256':digest(parent),'command':cmd,'sha256':sha,'weight':a.weight,'seed':a.seed,'logic_exactly_equal':True,'scope':'Only placerHeap/timingWeight setting changed; all logic, firmware, clocks and constraints identical.'}
(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
env={k:v for k,v in os.environ.items() if not k.startswith('NEXTPNR_')}
with (out/'console.log').open('w') as log:rc=subprocess.run(cmd,env=env,stdout=log,stderr=subprocess.STDOUT).returncode
record['inputs_unchanged']=all(digest(n)==s for n,s in sha.items())
record['timing']=summarize((out/'route.log').read_text(),exit_code=rc)
if (out/'routed.json').exists():
    routed=json.loads((out/'routed.json').read_text())
    record['recorded_placer_settings']={n:m.get('settings',{}).get('placerHeap/timingWeight') for n,m in routed['modules'].items()}
(out/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps({'clocks':{k:v['mhz'] for k,v in record['timing']['final_clocks'].items()},'inputs_unchanged':record['inputs_unchanged'],'accepted':record['timing']['accepted']}))
