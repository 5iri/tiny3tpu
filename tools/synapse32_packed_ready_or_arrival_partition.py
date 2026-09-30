"""Repartition the retained ready-side OR8 as OR3 feeding OR6, without added latency."""
import argparse,copy,gc,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_write_address_read_or_partition import apply_verified as apply_base
from synapse32_packed_ddr_last_capture_encoding import attributes
from synapse32_packed_counter_encoding import logical,evaluate,emit
from synapse32_packed_selector_patch_v4 import packed
gc.disable()
FIELDS=['passed','checkpoint','original_cells','replacements','added_cells','added_netnames','placements','added_latency_cycles','removed_cells','removed_netnames']
LATE=[139467,139456,139459,139460,139461]
def spec(m):
 cs=m['cells'];root=next(n for n in cs if '$233944.' in n and n.endswith('.mux8'));early='$tiny3tpu$ddr_capture_or_233944_early';old={early:cs[early],root:cs[root]};w,p,t=logical(cs[early]);rw,rp,rt=logical(cs[root]);assert (w,rw,t,rt)==(6,3,(1<<64)-2,254) and rp['I0']==p['O'];cuts=sorted({b for c in old.values() for k,b in logical(c)[1].items() if k!='O'}-{p['O']});assert len(cuts)==8 and set(LATE)<=set(cuts)
 new={early:attributes(packed([b for b in cuts if b not in LATE],p['O'],254),cs[early]),root:attributes(packed([p['O'],*LATE],rp['O'],(1<<64)-2),cs[root])}
 for word in range(256):
  v={b:(word>>i)&1 for i,b in enumerate(cuts)};a=dict(v);b=dict(v)
  for c in old.values():a[logical(c)[1]['O']]=evaluate(c,a)
  for c in new.values():b[logical(c)[1]['O']]=evaluate(c,b)
  assert a[rp['O']]==b[rp['O']]==int(word!=0)
 return dict(root=root,early=early,old=old,new=new,cuts=cuts,output=rp['O'])
def miter(s):
 return emit(s['old'],s['cuts'],[s['output']],'gold')+'\n'+emit(s['new'],s['cuts'],[s['output']],'candidate')+'\nmodule proof(input [7:0] x,output same);wire a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n'
def validate(patch,prior,base):
 s=spec(base['modules']['top']);expected={k:copy.deepcopy(prior[k]) for k in FIELDS}
 for n,c in s['new'].items():expected['added_cells' if n in prior['added_cells'] else 'replacements'][n]=c
 assert all(patch[k]==expected[k] for k in FIELDS) and patch['added_latency_cycles']==0
 proof=patch['partition_proof'];assert Path(proof['miter']).read_text()==miter(s)
 for n,h in proof['sha256'].items():assert digest(n)==h,n
 assert 'SUCCESS!' in Path(proof['log']).read_text()
 base['modules']['top']['cells'].update(copy.deepcopy(s['new']));return base

def apply_verified(patch,design):
 assert patch['passed'];bp=Path(patch['partition_base']);assert digest(bp)==patch['partition_base_sha256'];prior=json.loads(bp.read_text());return validate(patch,prior,apply_base(prior,design))
def main():
 p=argparse.ArgumentParser()
 for k in ['base-patch','reference','out']:p.add_argument('--'+k,type=Path,required=True)
 a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';record=json.loads(rp.read_text());assert record['passed'] and Path(record['patch'])==bp
 for d in [prior,record]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 source=Path(prior['checkpoint']).parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);s=spec(base['modules']['top']);patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_ready_or_arrival_partition',partition_base=str(bp),partition_base_sha256=digest(bp))
 for n,c in s['new'].items():patch['added_cells' if n in prior['added_cells'] else 'replacements'][n]=c
 ref=a.reference.resolve()/'routed.json';placed=json.loads(ref.read_text())['modules']['top']['cells'];bel=placed[s['root']]['attributes']['NEXTPNR_BEL'];assert bel.endswith('6LUT') and not any(c['attributes']['NEXTPNR_BEL']==bel[:-4]+'5LUT' for c in placed.values())
 out.mkdir();tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';v=out/'miter.v';v.write_text(miter(s));ys=out/'prove.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1\n');log=out/'prove.log'
 with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
 patch['partition_proof']=dict(miter=str(v),log=str(log),sha256={str(q.resolve()):digest(q) for q in [v,ys,log,tool,lib]});validate(patch,prior,base)
 patch['sha256']=dict(prior['sha256']);patch['sha256'].update(patch['partition_proof']['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,ref,source,Path(__file__),Path(__file__).with_name('synapse32_packed_write_address_read_or_partition.py'),Path(__file__).with_name('synapse32_packed_ddr_last_capture_encoding.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,exhaustive_cases=256,actual_primitive_sat=True,changed_luts=2,added_cells=0,added_latency_cycles=0,late=LATE)))
if __name__=='__main__':main()
