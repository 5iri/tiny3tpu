#!/usr/bin/env python3
"""Change only the HeAP placement timing weight in an isolated board netlist."""
import argparse,copy,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--board',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--weight',type=int,required=True);a=p.parse_args();assert 1<=a.weight<=100
board=a.board.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
h=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
x=json.loads((board/'soc.json').read_text());y=copy.deepcopy(x);top='kc705_synapse32_top';settings=y['modules'][top].setdefault('settings',{});assert 'placerHeap/timingWeight' not in settings;settings['placerHeap/timingWeight']=a.weight
restored=copy.deepcopy(y);del restored['modules'][top]['settings']['placerHeap/timingWeight']
if 'settings' not in x['modules'][top]:del restored['modules'][top]['settings']
assert restored==x
(out/'soc.json').write_text(json.dumps(y)+'\n')
for f in ['firmware.hex','kc705.xdc','synth.ys']:(out/f).write_bytes((board/f).read_bytes())
inputs=[board/f for f in ['soc.json','firmware.hex','kc705.xdc','synth.ys']]+[Path(__file__).resolve(),Path('/tmp/tiny3tpu-nextpnr-current/common/placer_heap.cc')]
for f in ['replica-manifest.json']:
 if (board/f).exists():
  r=json.loads((board/f).read_text());assert r['passed']
  for k in ['sha256','output_sha256']:
   for name,v in r[k].items():assert h(name)==v,name
  inputs.append(board/f)
r=dict(passed=True,weight=a.weight,logic_firmware_constraints_exact=True,scope='Only placerHeap/timingWeight changes; no clock or timing-model changes.',sha256={str(q):h(q) for q in inputs},output_sha256={str(q):h(q) for q in out.iterdir()},full_soc_timing_accepted=False)
(out/'weight-manifest.json').write_text(json.dumps(r,indent=2)+'\n');print('PASS exact design identity; placement weight',a.weight)
