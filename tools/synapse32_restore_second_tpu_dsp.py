"""Retain the proved DDR logic edit while undoing the rejected second DSP placement."""
import argparse,copy,json
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();assert not a.out.exists();patch=json.loads(a.patch.read_text());assert patch['passed']
for n,h in patch['sha256'].items():assert digest(n)==h,n
base=Path(patch['nor_macro_base_path']);prior=json.loads(base.read_text());step=prior['tpu_second_dsp_placement_variant'];n=step['cell'];assert patch['placements'][n]==step['to_bel']=='DSP48_X2Y52/DSP48E1';assert step['from_bel']=='DSP48_X2Y48/DSP48E1';assert step['from_bel'] not in patch['placements'].values();new=copy.deepcopy(patch);new['placements'][n]=step['from_bel']
for k in patch:
 if k!='placements':assert patch[k]==new[k]
new['restored_second_dsp_placement']=dict(parent=str(a.patch.resolve()),cell=n,from_bel=step['to_bel'],to_bel=step['from_bel'],logic_changed=False,execution_cycles_changed=False);new['sha256'].update({str(q.resolve()):digest(q) for q in [a.patch,base,Path(__file__)]});a.out.mkdir();(a.out/'patch.json').write_text(json.dumps(new,separators=(',',':'))+'\n');print(json.dumps(new['restored_second_dsp_placement']))
