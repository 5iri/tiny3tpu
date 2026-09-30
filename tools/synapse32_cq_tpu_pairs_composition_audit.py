"""Bind the routed candidate to all three proved combinational transformations."""
import json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_pinmap_control_audit import functional_cells
root=Path(__file__).resolve().parents[1];route=root/'build-grade2-incremental-cq-tpu-output-pairs';mp=route/'manifest.json';m=json.loads(mp.read_text());assert m['passed'];source=Path(m['source']);d=json.loads(source.read_text());cs=d['modules']['top']['cells'];files=[mp,source,route/'routed.json',Path(__file__).resolve()]
for path in [root/'build-grade2-readvalid-arrival-swap-proof/proof.json',root/'build-grade2-reset-shared-cone-proof/proof.json',root/'build-grade2-reset-shared-primitive-proof/proof.json',root/'build-grade2-ready-control-cone-proof/proof.json',root/'build-grade2-ready-control-primitive-proof/proof.json']:
 proof=json.loads(path.read_text());assert proof['passed']
 for p,h in proof['sha256'].items():assert digest(p)==h
 files.append(path)
 if 'old' in proof:
  for n,c in proof['old'].items():assert cs[n]==c
  for n,c in proof.get('new',proof.get('new_root',{})).items():cs[n]=c
assert functional_cells(d)[0]==functional_cells(json.loads((route/'routed.json').read_text()))[0]
r=dict(passed=True,comparison_reference='Source checkpoint plus proved two-cell OR cut swap and proved shared reset/enable LUT4 and ready-control LUT5 replacements; every other logical cell identical.',proofs_composed=3,added_cycles=0,added_cells=0,removed_cells=0,full_soc_timing_accepted=False,sha256={str(p):digest(p) for p in files});out=route/'composition-audit.json';assert not out.exists();out.write_text(json.dumps(r,indent=2)+'\n');print('PASS exact routed logic equals composition of all three proved transformations')
