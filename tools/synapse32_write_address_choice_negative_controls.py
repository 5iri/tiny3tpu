"""Reject observable child deletion and invalid constant provenance for the address-choice patch."""
import argparse,copy,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_write_address_carry_choice import spec
from synapse32_packed_counter_encoding import logical
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();p=json.loads(a.patch.read_text());assert p['passed'];m=json.loads(a.source.read_text())['modules']['top'];s=spec(m);n=next(iter(s[5]));bit=logical(s[5][n])[1]['O'];checks=[]
def reject(label):
 try:spec(m)
 except AssertionError:checks.append(dict(name=label,rejected=True))
 else:raise AssertionError('accepted '+label)
m['ports']['negative_observer']=dict(direction='output',bits=[bit]);reject('top_port_observer');del m['ports']['negative_observer']
m['cells']['negative_ff_observer']=dict(type='SLICE_FFX',attributes={},connections={'D':[bit]},port_directions={'D':'input'});reject('register_observer');del m['cells']['negative_ff_observer']
old=m['cells'][n]['type'];m['cells'][n]['type']='SLICE_FFX';reject('state_deletion');m['cells'][n]['type']=old
n='$PACKER_VCC_DRV';old=m['cells'][n]['type'];m['cells'][n]['type']='PSEUDO_GND';reject('wrong_constant_driver');m['cells'][n]['type']=old
assert spec(m)==s;a.out.write_text(json.dumps(dict(passed=True,checks=checks,sha256={str(q.resolve()):digest(q) for q in [a.patch,a.source,Path(__file__),Path(__file__).with_name('synapse32_packed_write_address_carry_choice.py')]}),indent=2)+'\n');print('PASS address-choice observer, state-deletion and constant-driver negative controls')
