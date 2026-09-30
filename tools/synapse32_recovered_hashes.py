#!/usr/bin/env python3
"""Validate narrowly declared historical tool replacements after an exact replay."""
import json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_rebuilt_toolchain_replay import ALLOWED

class RecoveredHashes:
    def __init__(self,path):
        self.path=Path(path).resolve();self.record=json.loads(self.path.read_text());r=self.record
        assert r['kind']=='rebuilt_toolchain_exact_replay' and r['passed'] and not r['full_soc_timing_accepted']
        assert all(r[k] for k in ['inputs_unchanged','routed_json_exact','timing_graph_exact','native_fmax_exact'])
        for key in ['sha256','output_sha256']:
            for n,h in r[key].items():assert digest(n)==h,n
        old=json.loads(Path(r['recovery_reference']).read_text());cp=json.loads(Path(old['checkpoint']).read_text());expected={str(Path(n).resolve()):h for d in [old,cp] for key in ['sha256','output_sha256'] for n,h in d.get(key,{}).items()}
        self.rows={}
        for row in r['historical_substitutions']:
            name=row['path'];assert name in ALLOWED and expected[name]==row['expected'] and digest(name)==row['actual']
            assert name not in self.rows;self.rows[name]=row
        ref=Path(r['recovery_reference']).parent;out=self.path.parent
        assert digest(out/'guidance-timing-graph.tsv')==digest(ref/'guidance-timing-graph.tsv')
        assert json.loads((out/'routed.json').read_text())==json.loads((ref/'routed.json').read_text())
    def check(self,path,expected):
        actual=digest(path)
        if actual!=expected:
            row=self.rows.get(str(Path(path).resolve()));assert row is not None and row['expected']==expected and row['actual']==actual,('unvalidated historical difference',path)
        return actual
    def metadata(self):
        return dict(control=str(self.path),control_sha256=digest(self.path),historical_substitutions=list(self.rows.values()),historical_manifests_modified=False)
