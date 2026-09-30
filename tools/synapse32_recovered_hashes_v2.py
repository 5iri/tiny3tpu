#!/usr/bin/env python3
"""Extend validated recovery with exact replays of required legacy backends."""
import json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_recovered_hashes import RecoveredHashes as PrimaryRecovery
from synapse32_rebuilt_legacy_replay import REFERENCES
class RecoveredHashes(PrimaryRecovery):
    def __init__(self,path,legacy):
        super().__init__(path);self.legacy=[];seen=set()
        for p in legacy:
            p=Path(p).resolve();r=json.loads(p.read_text());assert r['passed'] and r['kind']=='rebuilt_legacy_exact_replay' and not r['full_soc_timing_accepted'];backend=r['backend'];assert backend in REFERENCES and backend not in seen;seen.add(backend)
            assert all(r[k] for k in ['inputs_unchanged','routed_json_exact','timing_graph_exact','native_fmax_exact'])
            assert r['recovery']['control']==str(self.path) and r['recovery']['control_sha256']==digest(self.path)
            for key in ['sha256','output_sha256']:
                for n,h in r[key].items():assert digest(n)==h,n
            ref=Path(REFERENCES[backend]).resolve();assert r['recovery_reference']==str(ref/'manifest.json');old=json.loads((ref/'manifest.json').read_text());expected={str(Path(n).resolve()):h for key in ['sha256','output_sha256'] for n,h in old.get(key,{}).items()}
            tool=(Path('/tmp')/('tiny3tpu-nextpnr-'+backend)/'nextpnr-xilinx').resolve();allowed={str(tool),str(tool.with_name('build-manifest.json'))};assert {row['path'] for row in r['historical_substitutions']}==allowed
            for row in r['historical_substitutions']:
                assert row['path'] in allowed and row['expected']==expected[row['path']] and digest(row['path'])==row['actual'];assert row['path'] not in self.rows;self.rows[row['path']]=row
            assert digest(p.parent/'guidance-timing-graph.tsv')==digest(ref/'guidance-timing-graph.tsv');assert json.loads((p.parent/'routed.json').read_text())==json.loads((ref/'routed.json').read_text());self.legacy.append(dict(path=str(p),sha256=digest(p)))
        assert seen==set(REFERENCES)
    def metadata(self):
        r=super().metadata();r['legacy_replays']=self.legacy;return r
