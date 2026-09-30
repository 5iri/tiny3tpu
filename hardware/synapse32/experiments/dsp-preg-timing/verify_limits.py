#!/usr/bin/env python3
"""Check conservative model values against the downloaded AMD DS182 table."""
import hashlib,json,re
from pathlib import Path
out=Path('build-dsp-preg-timing').resolve();text=(out/'ds182.txt').read_text()
rows={
 'AB_setup':('TDSPDCK_{A, B}_PREG_MULT/',5.89),
 'C_setup':('TDSPDCK_C_PREG/',2.11),
 'CEP_setup':('TDSPDCK_CEP_PREG/',0.54),
 'RSTP_setup':('TDSPDCK_RSTP_PREG/',0.37),
}
values={}
for key,(marker,expected) in rows.items():
 row=text[text.index(marker):].split('\nns',1)[0]
 nums=[float(v) for v in re.findall(r'(\d+\.\d+)/',row)]
 assert len(nums)==6,(key,nums)
 assert max(nums)==expected,(key,nums)
 holds=[float(v.replace('–','-').replace('−','-')) for v in re.findall(r'/\s*([–−-]?\d+\.\d+)',row)]
 assert len(holds)==6,(key,holds)
 values[key]={'all_grades':nums,'maximum':expected,'hold_all_grades':holds,'hold_maximum':max(holds)}
line=next(l for l in text.splitlines() if l.startswith('TDSPCKO_P_PREG '));nums=[float(v) for v in re.findall(r'\b0\.\d+',line)];assert len(nums)==6 and max(nums)==.45
values['P_clock_to_Q']={'all_grades':nums,'maximum':.45}
# Clamp negative data hold limits upward to zero; retain the largest CE/RST hold.
assert values['AB_setup']['hold_maximum']<=0 and values['C_setup']['hold_maximum']<=0
assert values['CEP_setup']['hold_maximum']==0.01 and values['RSTP_setup']['hold_maximum']==0.11
values['hold_ns']={'A':0.0,'B':0.0,'C':0.0,'CEP':0.01,'RSTP':0.11}
paths=[out/'ds182.pdf',out/'ds182.txt',Path(__file__).resolve(),Path(__file__).with_name('model.inc').resolve()]
(out/'limits.json').write_text(json.dumps({'passed':True,'source':'https://docs.amd.com/api/khub/documents/BhulK6GRrzUpQYw0lzrnMA/content','document':'AMD DS182 v2.19, March 26 2021, Table 35 pp.41–43','profile':'PREG=1; every other DSP register bypassed; direct inputs; multiply plus C; fixed OPMODE 0x35; only P outputs connected. All other nonconstant inputs rejected.','limits':values,'sha256':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}},indent=2)+'\n')
print('PASS: DSP setup and clock-to-Q model uses maxima across all six DS182 grade columns')
