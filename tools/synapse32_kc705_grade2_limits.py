"""Select DS182's 1.0 V -2/-2LE column for the documented stock KC705."""
import copy,json
from pathlib import Path
from synapse32_apply_bram_timing import limits_from_text as all_bram, digest
from synapse32_cpu_preg_dsp_model import limits_from_text as all_dsp
from synapse32_lutram_timing_model import limits_from_text as all_lutram
ROOT=Path(__file__).resolve().parents[1]
COLUMN=1
def verify_board():
 p=ROOT/'build-kc705-grade2-limits/board-evidence.json';d=json.loads(p.read_text());assert d['passed'] and d['speed_grade']==-2 and d['nominal_vccint_v']==1.0 and d['ds182_column_index']==COLUMN
 for n,h in d['sha256'].items():assert digest(n)==h
 return p

def bram_limits(text):
 d=copy.deepcopy(all_bram(text))
 for k,v in d.items():
  if 'setup_all_grades' in v:v['setup_ns']=v['setup_all_grades'][COLUMN];v['hold_ns']=v['hold_all_grades'][COLUMN]
  elif k=='read_output':v['clock_to_output_ns']=v['all_grades'][COLUMN]
  elif k=='internal_fmax':v['minimum_mhz']=v['all_grades'][COLUMN]
  else:raise AssertionError(k)
  v['selected_column']=COLUMN
 return d

def dsp_limits(text):
 d=copy.deepcopy(all_dsp(text))
 for k,v in d.items():
  if 'setup_ns' in v:
   setup,hold=v['all_grades'][COLUMN];v['setup_ns']=float(setup);v['hold_ns']=max(0,float(hold))
  else:v['max_ns']=v['all_grades'][COLUMN]
  v['selected_column']=COLUMN
 assert d['AB_P']['setup_ns']==3.9
 return d

def lutram_limits(text):
 d=copy.deepcopy(all_lutram(text))
 for k,v in d.items():
  if 'setup_ns' in v:
   pairs=v['all_grades'];assert len(pairs) in [6,12]
   selected=[pairs[i] for i in range(COLUMN,len(pairs),6)]
   v['setup_ns']=max(s for s,h in selected);v['hold_ns']=max(h for s,h in selected)
  else:v['max_ns']=v['all_grades'][COLUMN]
  v['selected_column']=COLUMN
 return d
