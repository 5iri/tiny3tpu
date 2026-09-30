"""Reject observable or stateful deletions and a corrupt OR repartition."""
import argparse,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_ddr_dead_macro_cleanup import dead_set
p=argparse.ArgumentParser();p.add_argument('--cleanup',type=Path,required=True);p.add_argument('--input',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();cleanup=json.loads(a.cleanup.read_text());assert cleanup['passed'];bp=Path(cleanup['cleanup_base_path']);prior=json.loads(bp.read_text());m=json.loads(a.input.read_text())['modules']['top'];_,removed,_=dead_set(prior,m);assert len(removed)==24
n=next(iter(removed));c=m['cells'][n];bit=next(b for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs);results={}
def reject(label):
 rejected=False
 try:dead_set(prior,m)
 except AssertionError:rejected=True
 assert rejected,label
 results[label]=True
ff=next(n for n,c in m['cells'].items() if c['type']=='SLICE_FFX');saved=m['cells'][ff]['connections']['D'];m['cells'][ff]['connections']['D']=[bit];reject('register_observer_rejected');m['cells'][ff]['connections']['D']=saved
port=next(iter(m['ports']));saved=m['ports'][port]['bits'];m['ports'][port]['bits']=[bit];reject('top_port_observer_rejected');m['ports'][port]['bits']=saved
saved=c['type'];c['type']='SLICE_FFX';reject('state_cell_deletion_rejected');c['type']=saved
_,again,_=dead_set(prior,m);assert set(again)==set(removed)
out=a.out.resolve();out.mkdir();src=a.cleanup.resolve().parent/'repartition.v';s=src.read_text();assert 'assign same=a==b;' in s;v=out/'wrong-output.v';v.write_text(s.replace('assign same=a==b;','assign same=a==~b;'));ys=out/'wrong-output.ys';ys.write_text((src.parent/'prove.ys').read_text().replace(str(src),str(v)));log=out/'wrong-output.log';tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
with log.open('w') as f:rc=subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT).returncode
assert rc and 'proof did fail' in log.read_text();results['wrong_repartition_output_rejected']=True;paths=[a.cleanup,a.input,bp,src,v,ys,log,tool,Path(__file__),Path(__file__).with_name('synapse32_packed_ddr_dead_macro_cleanup.py')];(out/'negative-checks.json').write_text(json.dumps(dict(passed=True,**results,removed_output_bit=bit,observer_ff=ff,observer_port=port,mutated_cell=n,sha256={str(p.resolve()):digest(p) for p in paths}),indent=2)+'\n');print(json.dumps(dict(passed=True,**results)))
