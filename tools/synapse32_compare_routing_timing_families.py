"""Compare source routing tables without inferring provenance from equality."""
from pathlib import Path
import hashlib,json
base=Path('/tmp/tiny3tpu-nextpnr-current/xilinx/external/prjxray-db')
records=[];hashes={}
for tile in ['INT_L','INT_R']:
 kp=base/'kintex7'/f'tile_type_{tile}.json';k=json.loads(kp.read_text())
 hashes[str(kp)]=hashlib.sha256(kp.read_bytes()).hexdigest()
 for fam in ['artix7','zynq7','spartan7','virtex7']:
  p=base/fam/kp.name
  if not p.exists():continue
  d=json.loads(p.read_text());common=set(k['pips'])&set(d['pips']);present=[n for n in common if k['pips'][n].get('src_to_dst',{}).get('delay') is not None and d['pips'][n].get('src_to_dst',{}).get('delay') is not None]
  records.append(dict(tile=tile,comparison_family=fam,common_pips=len(common),both_have_delay=len(present),equal_delay_arrays=sum(k['pips'][n]['src_to_dst']['delay']==d['pips'][n]['src_to_dst']['delay'] for n in present),equal_complete_direction_models=sum(k['pips'][n].get('src_to_dst')==d['pips'][n].get('src_to_dst') for n in common)))
  hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
r=dict(comparisons=records,scope='Source-file equality only. Does not prove copying direction, characterization device, speed grade or physical validity.',provenance_validated=False,full_soc_timing_accepted=False,sha256=hashes)
out=Path(__file__).resolve().parents[1]/'build-grade2-routing-timing-provenance';out.mkdir(exist_ok=False);(out/'comparison.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(records,indent=2))
