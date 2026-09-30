"""Reject corruptions of the packed same-edge refresher flag contract."""
import argparse,copy,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_refresher_flag import FLAG,validate
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--parent-input',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();patch=json.loads(a.patch.read_text());bp=Path(patch['refresher_base_path']);assert digest(bp)==patch['refresher_base_sha256'];prior=json.loads(bp.read_text());base=json.loads(a.parent_input.read_text());base['modules']['top']['cells'].update(copy.deepcopy(patch['refresher_source_cells']));root=next(n for n in patch['replacements'] if n.endswith('$217672'));tests={}
for name in ['wrong_init','wrong_set','wrong_ce','wrong_d','wrong_next_table','existing_next_bit']:
 bad=copy.deepcopy(patch)
 if name=='wrong_init':bad['added_cells'][FLAG]['parameters']['INIT']='0'
 if name=='wrong_set':bad['added_cells'][FLAG]['connections']['SR']=[50992]
 if name=='wrong_ce':bad['added_cells'][FLAG]['connections']['CE']=[137083]
 if name=='wrong_d':bad['added_cells'][FLAG]['connections']['D']=[55756]
 if name=='wrong_next_table':bad['replacements'][root]['parameters']['INIT']='0'*64
 if name=='existing_next_bit':bad['refresher_next_bit']=54724
 try:validate(bad,prior,base)
 except AssertionError:tests[name]=True
 else:raise AssertionError('accepted '+name)
validate(patch,prior,base);a.out.mkdir();result=dict(passed=True,corruptions_rejected=tests,positive_packed_contract_passed=True,scope='Actual implementation guard controls; original primitive induction and its CE/reset/INIT negative SAT controls retained separately.',sha256={str(q.resolve()):digest(q) for q in [a.patch,a.parent_input,bp,Path(__file__),Path(__file__).with_name('synapse32_packed_refresher_flag.py')]});(a.out/'negative-checks.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(tests))
