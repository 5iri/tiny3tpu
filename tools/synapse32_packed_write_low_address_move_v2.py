"""Relocate unchanged low write-address registers near their adder consumers."""
import gc
gc.disable()
import argparse,copy,json,re
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_joint_carry_buffer_inline import apply_verified as apply_base
from synapse32_packed_timer_mid_zero_flag import FIELDS

def spec(m):
 cs=m['cells'];ns=m['netnames'];drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};names=[drv[ns[f'memory.main_write_pipe_valid_source_payload_addr[{i}]']['bits'][0]] for i in range(13)];assert len(set(names))==13
 for n in names:
  c=cs[n];assert c['type']=='SLICE_FFX' and c['attributes']['X_ORIG_TYPE']=='FDRE' and c['parameters']=={'INIT':'0'} and c['attributes']['X_FFSYNC'].strip()=='1';assert c['connections']['CK']==[156059] and c['connections']['SR']==[50991] and c['connections']['CE']==[139092];assert not any(k.startswith('CONSTR_') for k in c['attributes'])
 return {n:cs[n] for n in names}
def apply_verified(p,design):
 bp=Path(p['address_move_base']);assert p['passed'] and digest(bp)==p['address_move_base_sha256'];prior=json.loads(bp.read_text());base=apply_base(prior,design);selected=spec(base['modules']['top']);assert p['address_move_cells']==selected
 for k in FIELDS:
  if k!='placements':assert p[k]==prior[k]
 assert set(p['placements'])==set(prior['placements'])|set(selected)
 for n,b in prior['placements'].items():
  if n not in selected:assert p['placements'][n]==b
 assert all(p['placements'][n].endswith(('AFF','BFF','CFF','DFF')) for n in selected);return base

def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';r=json.loads(rp.read_text());assert r['passed'] and Path(r['patch'])==bp
 for d in [prior,r]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 source=Path(prior['checkpoint']).parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);m=base['modules']['top'];cs=m['cells'];selected=spec(m);ref=a.reference.resolve()/'routed.json';placed=json.loads(ref.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for n,c in placed.items() if n not in selected};sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad=set()
 for n,c in cs.items():
  if n in selected:continue
  site=placed[n]['attributes']['NEXTPNR_BEL'].split('/')[0]
  if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE','').startswith(('RAM','SRL')):bad.add(site)
  if c['type']=='SLICE_FFX' and (c['attributes'].get('X_ORIG_TYPE')!='FDRE' or c['attributes'].get('X_FFSYNC','').strip()!='1' or any(c['connections'][p]!=next(iter(selected.values()))['connections'][p] for p in ['CK','SR','CE'])):bad.add(site)
 def xy(b):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',b).groups()))
 drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};uses={c['connections']['Q'][0]:[] for c in selected.values()}
 for n,c in cs.items():
  for p,bs in c['connections'].items():
   if c['port_directions'][p]=='input':
    for b in bs:
     if b in uses:uses[b].append(n)
 patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_write_low_address_register_placement',address_move_base=str(bp),address_move_base_sha256=digest(bp),address_move_cells=selected);evidence={}
 for n,c in selected.items():
  q=c['connections']['Q'][0];sinks=uses[q];assert sinks and all(placed[k]['attributes']['NEXTPNR_BEL'].startswith('SLICE_') for k in sinks);points=[xy(placed[k]['attributes']['NEXTPNR_BEL']) for k in sinks for _ in range(3)]
  for port in ['D','CE']:
   d=drv[c['connections'][port][0]];bel=placed[d]['attributes']['NEXTPNR_BEL']
   if bel.startswith('SLICE_'):points.append(xy(bel))
  free=[site+'/'+l+'FF' for site in sites-bad for l in 'ABCD' if site+'/'+l+'FF' not in occupied and site+'/'+l+'5FF' not in occupied];assert free
  def cost(b):return sum(abs(xy(b)[0]-p[0])+abs(xy(b)[1]-p[1]) for p in points)
  chosen=min(free,key=lambda b:(cost(b),b));patch['placements'][n]=chosen;occupied.add(chosen);evidence[n]=dict(old=placed[n]['attributes']['NEXTPNR_BEL'],new=chosen,q_consumers=sinks,cost_before=cost(placed[n]['attributes']['NEXTPNR_BEL']),cost_after=cost(chosen))
 out.mkdir();patch['placement_evidence']=dict(criterion='Threefold weight to Q consumers, unit weight to D and CE source cells, among free full-FF BELs with exactly compatible synchronous FDRE controls; exclude every carry, mux, RAM and SRL slice to avoid shared X-input conflicts; no clock or logic change.',moves=evidence);patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,ref,source,Path(__file__),Path(__file__).with_name('synapse32_packed_joint_carry_buffer_inline.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,registers=len(selected),moved=sum(v['old']!=v['new'] for v in evidence.values()),logic_changed=False,added_state=0,added_latency_cycles=0,placements={n:v['new'] for n,v in evidence.items()})))
if __name__=='__main__':main()
