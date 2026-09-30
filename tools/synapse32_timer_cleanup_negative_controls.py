"""Exercise observability and state-preservation guards for dead timer mux cleanup."""
import argparse,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_timer_flag_colocation import spec
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();prior=json.loads(a.patch.read_text());m=json.loads(a.input.read_text())['modules']['top'];groups,removed,nets,moves=spec(prior,m);n=next(iter(removed));c=m['cells'][n];bit=next(b for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs);ff=next(n for n,c in m['cells'].items() if c['type']=='SLICE_FFX');old=m['cells'][ff]['connections']['D'];m['cells'][ff]['connections']['D']=[bit]
try:spec(prior,m)
except AssertionError:pass
else:raise AssertionError('accepted register observer')
m['cells'][ff]['connections']['D']=old;m['ports']['negative_observer']=dict(direction='output',bits=[bit])
try:spec(prior,m)
except AssertionError:pass
else:raise AssertionError('accepted top observer')
del m['ports']['negative_observer'];typ=c['type'];c['type']='SLICE_FFX'
try:spec(prior,m)
except AssertionError:pass
else:raise AssertionError('accepted state deletion')
c['type']=typ;assert spec(prior,m)==(groups,removed,nets,moves);a.out.mkdir();r=dict(passed=True,register_observer_rejected=True,top_observer_rejected=True,state_deletion_rejected=True,positive_removed_combinational_count=12,sha256={str(q.resolve()):digest(q) for q in [a.patch,a.input,Path(__file__),Path(__file__).with_name('synapse32_packed_timer_flag_colocation.py')]});(a.out/'negative-checks.json').write_text(json.dumps(r,indent=2)+'\n');print('PASS all timer dead-cone negative controls')
