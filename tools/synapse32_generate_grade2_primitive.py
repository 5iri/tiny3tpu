#!/usr/bin/env python3
"""Generate the native primitive include from the checked stock KC705 DS182 column."""
import json
from pathlib import Path
from synapse32_kc705_grade2_limits import bram_limits,dsp_limits,lutram_limits,verify_board
from synapse32_apply_bram_timing import digest
ROOT=Path(__file__).resolve().parents[1]
def main():
 source=ROOT/'hardware/synapse32/experiments/carry-guidance/cpu_preg_primitive_timing.inc';out=source.with_name('grade2_primitive_timing.inc');assert not out.exists();board=verify_board();text=ROOT/'build-dsp-preg-timing/ds182.txt';b=bram_limits(text.read_text());d=dsp_limits(text.read_text());l=lutram_limits(text.read_text());s=source.read_text();changes=[]
 def replace(old,new):
  nonlocal s
  assert s.count(old)==1,(old,s.count(old));s=s.replace(old,new);changes.append(dict(original=old,candidate=new))
 def pair(v):return f"{v['setup_ns']},{v['hold_ns']}"
 replace('t.cq=1.44;',f"t.cq={l['clock_to_read']['max_ns']};")
 for old,key in [('input("CLK",.69,.33)','data'),('input("CLK",.46,.11)','write_enable'),('input("CLK",.63,.63)','write_address')]:replace(old,f'input("CLK",{pair(l[key])})')
 replace('output("CLKARDCLKL",2.44)',f'output("CLKARDCLKL",{b["read_output"]["clock_to_output_ns"]})')
 for old,key in [('.65,.38','address'),('.78,.64','data'),('.48,.32','enable'),('.54,.29','write_enable'),('.34,.40','reset')]:replace(f'input("CLKARDCLKL",{old})',f'input("CLKARDCLKL",{pair(b[key])})')
 replace('output("CLK",pr ? .45 : 2.31)',f'output("CLK",pr ? {d["P_P"]["max_ns"]} : {d["P_M"]["max_ns"]})')
 for name,old in [('A','.38'),('B','.51')]:
  reg=name.lower();replace(f'input("CLK",{reg} ? {old} : (pr ? 5.89 : 3.66),{reg} ? .18 : 0)',f'input("CLK",{reg} ? {d[name]["setup_ns"]} : (pr ? {d["AB_P"]["setup_ns"]} : {d["AB_M"]["setup_ns"]}),{reg} ? {d[name]["hold_ns"]} : 0)')
 for old,key in [('.53,.34','RST_AB'),('.55,.09','CE_AB'),('.24,.29','RSTM'),('.39,.25','CEM'),('.37,.11','RSTP'),('.54,.01','CEP')]:replace(f'input("CLK",{old})',f'input("CLK",{pair(d[key])})')
 restored=s
 for r in reversed(changes):
  # Some new constants can equal other old constants: restore complete unique expressions in reverse order.
  assert restored.count(r['candidate'])==1,(r,restored.count(r['candidate']));restored=restored.replace(r['candidate'],r['original'])
 assert restored==source.read_text();out.write_text(s)
 paths=[source,text,board,Path(__file__).resolve(),ROOT/'tools/synapse32_kc705_grade2_limits.py']
 record=dict(passed=True,changes=changes,only_numeric_primitive_limits_changed=True,grade='Stock KC705, DS182 1.0 V -2/-2LE column',limits=dict(bram=b,dsp=d,lutram=l),sha256={str(p):digest(p) for p in paths},output_sha256={str(out):digest(out)},full_soc_timing_accepted=False)
 (ROOT/'build-kc705-grade2-limits/native-include.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS native grade-2 primitive constants generated from independent parsed limits')
if __name__=='__main__':main()
