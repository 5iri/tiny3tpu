"""Move one combinational TPU multiplier to an unused nearby DSP BEL; change no logic."""
import gc
gc.disable()
import argparse,copy,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_recovered_hashes import RecoveredHashes
p=argparse.ArgumentParser();p.add_argument('--recovery',type=Path,required=True);p.add_argument('--patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--trace',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();recovery=RecoveredHashes(a.recovery);patch=json.loads(a.patch.read_text());rp=a.reference/'manifest.json';record=json.loads(rp.read_text());trace=json.loads(a.trace.read_text());assert patch['passed'] and record['passed'];assert Path(record['patch']).resolve()==a.patch.resolve()
for d in [patch,record,trace]:
 for k in ['sha256','output_sha256']:
  for n,h in d.get(k,{}).items():recovery.check(n,h)
source=a.reference/'routed.json';cs=json.loads(source.read_text())['modules']['top']['cells'];names={v['cell'] for r in trace['paths'] for v in r['path'] if cs[v['cell']]['type']=='DSP48E1_DSP48E1'};assert len(names)==1;root=names.pop();c=cs[root];assert '\\GEN_BIG_CORES[1].u_core.\\u_systolic_array.\\ROW[1].COL[2].PE.' in root
assert c['attributes']['NEXTPNR_BEL']=='DSP48_X2Y48/DSP48E1';assert not c['attributes'].get('CONSTR_PARENT') and not c['attributes'].get('CONSTR_CHILDREN');assert c['parameters']['A_INPUT']==c['parameters']['B_INPUT']=='DIRECT';assert all(int(c['parameters'][k],2)==0 for k in ['AREG','BREG','MREG','PREG'])
effective={n:patch['placements'].get(n,c['attributes']['NEXTPNR_BEL']) for n,c in cs.items()};target='DSP48_X2Y52/DSP48E1';assert target not in effective.values();new=copy.deepcopy(patch);new['placements'][root]=target
for k in patch:
 if k!='placements':assert new[k]==patch[k]
new['tpu_second_dsp_placement_variant']=dict(parent=str(a.patch.resolve()),reference=str(source.resolve()),trace=str(a.trace.resolve()),cell=root,from_bel=effective[root],to_bel=target,reason='Shorten routes between the existing input/output registers and the unregistered TPU multiplier. Original legality must validate the requested free DSP site.',execution_cycles_changed=False)
new['sha256'].update({str(q.resolve()):digest(q) for q in [a.patch,rp,source,a.trace,Path(__file__),a.recovery,Path(__file__).with_name('synapse32_recovered_hashes.py')]});a.out.mkdir();(a.out/'patch.json').write_text(json.dumps(new,separators=(',',':'))+'\n');print(json.dumps(new['tpu_second_dsp_placement_variant']))
