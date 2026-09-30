"""Exhaustively check logical LUT permutations; do not waive failed exact comparison."""
import copy,itertools,json,re
from pathlib import Path
from synapse32_pinmap_control_audit import functional_cells
from synapse32_apply_bram_timing import digest
root=Path(__file__).resolve().parents[1];r=root/'build-grade2-incremental-write-address-move-v5';p=root/'build-grade2-pre-fixup-routing-control/routed.json';q=r/'routed.json'
a=functional_cells(json.loads(p.read_text()))[0]['top'];b=functional_cells(json.loads(q.read_text()))[0]['top']
def equivalent(x,y):
 if x==y:return True
 if x['type']!='SLICE_LUTX' or y['type']!='SLICE_LUTX':return False
 kind=x['attributes']['X_ORIG_TYPE']
 if not re.fullmatch('LUT[1-6]',kind):return False
 if any(x[k]!=y.get(k) for k in x if k not in ['connections','parameters']):return False
 if set(x['parameters'])!={'INIT'} or set(y['parameters'])!={'INIT'}:return False
 n=int(kind[-1]);pins={f'I{i}' for i in range(n)}
 if set(x['connections'])!=pins|{'O'} or set(y['connections'])!=pins|{'O'}:return False
 if x['connections']['O']!=y['connections']['O']:return False
 def signal(c,k):
  v=c['connections'][k];assert len(v)==1;return repr(v[0])
 vx={signal(x,k) for k in pins};vy={signal(y,k) for k in pins}
 if vx!=vy:return False
 variables=sorted(vx)
 for bits in itertools.product([0,1],repeat=len(variables)):
  env=dict(zip(variables,bits))
  def evaluate(c):
   idx=sum(env[signal(c,f'I{i}')]<<i for i in range(n));return (int(c['parameters']['INIT'],2)>>idx)&1
  if evaluate(x)!=evaluate(y):return False
 return True
assert set(a)==set(b);changed=[n for n in a if a[n]!=b[n]];bad=[n for n in changed if not equivalent(a[n],b[n])]
negative=[]
for n in changed:
 mutant=copy.deepcopy(b[n]);v=mutant['parameters']['INIT'];mutant['parameters']['INIT']=''.join('1' if bit=='0' else '0' for bit in v);negative.append(not equivalent(a[n],mutant))
m=json.loads((r/'manifest.json').read_text());checks=['inputs_unchanged','placements_exact','retained_routes_exact','ground_additions_only','normalized_ties_restored'];passed=not bad and bool(changed) and all(negative) and m['exit_code']==0 and all(m[k] for k in checks)
record=dict(passed=passed,exact_logical_comparison_passed=False,changed_lut_count=len(changed),non_equivalent_cells=bad,exhaustive_local_boolean_equivalence=not bad,complement_negative_controls=len(negative),negative_controls_passed=all(negative),scope='Exhaustive truth tables for each changed LUT with identical signals and output, and exact equality for every other cell. No new workload simulation or physical timing signoff.',full_soc_timing_accepted=False,sha256={str(f):digest(f) for f in [p,q,r/'manifest.json',Path(__file__).resolve()]})
out=r/'lut-permutation-audit.json';assert not out.exists();out.write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record));assert passed
