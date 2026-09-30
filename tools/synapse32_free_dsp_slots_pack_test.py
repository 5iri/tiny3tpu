#!/usr/bin/env python3
"""Exercise the actual packer on current SoC and a two-DSP cascade fixture."""
import argparse,copy,json,os,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
p=argparse.ArgumentParser();p.add_argument('--board',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();board=a.board.resolve();out=a.out.resolve();assert not out.exists()
tool=Path('/tmp/tiny3tpu-nextpnr-free-dsp-slots/nextpnr-xilinx').resolve();old_tool=Path('/tmp/tiny3tpu-nextpnr-grade2-guidance/nextpnr-xilinx').resolve();bp=tool.with_name('build-manifest.json');build=json.loads(bp.read_text());assert build['passed'] and build['baseline_unchanged'] and digest(tool)==build['tool_sha256']
for n,h in build['baseline_sha256'].items():assert digest(n)==h
source=board/'soc.json';original=json.loads(source.read_text());fixture=copy.deepcopy(original);cells=fixture['modules']['kc705_synapse32_top']['cells'];names=sorted(n for n,c in cells.items() if c['type']=='DSP48E1' and 'cpu' in n);assert len(names)==4
first,second=names[:2];old_pcin=cells[second]['connections']['PCIN'];assert old_pcin==['0']*48
cells[second]['connections']['PCIN']=cells[first]['connections']['PCOUT'].copy();restored=copy.deepcopy(fixture);restored['modules']['kc705_synapse32_top']['cells'][second]['connections']['PCIN']=old_pcin;assert restored==original
out.mkdir();fixture_path=out/'cascade-fixture.json';fixture_path.write_text(json.dumps(fixture,separators=(',',':'))+'\n')
chipdb=Path('/tmp/tiny3tpu-nextpnr-current/kc705.bin').resolve();paths=[source,fixture_path,board/'kc705.xdc',tool,old_tool,bp,chipdb,Path(__file__).resolve()];hashes={str(q):digest(q) for q in paths};rows=[];outputs=[]
for label,input_path in [('soc',source),('cascade',fixture_path)]:
 designs={}
 for mode,binary,enabled in [('original',old_tool,False),('disabled',tool,False),('enabled',tool,True)]:
  folder=out/(label+'-'+mode);folder.mkdir();packed=folder/'packed.json';log=folder/'pack.log'
  cmd=[str(binary),'--chipdb',str(chipdb),'--json',str(input_path),'--xdc',str(board/'kc705.xdc'),'--freq','100','--seed','5','--pack-only','--write',str(packed),'--log',str(log)]
  env={k:v for k,v in os.environ.items() if not k.startswith(('NEXTPNR_','TINY3TPU_'))}
  if enabled:env['TINY3TPU_FREE_STANDALONE_DSP_SLOTS']='1'
  with (folder/'console.log').open('w') as f:r=subprocess.run(cmd,env=env,stdout=f,stderr=subprocess.STDOUT)
  assert r.returncode==0,log;designs[mode]=json.loads(packed.read_text());outputs += [packed,log]
 assert designs['original']==designs['disabled']
 gold=designs['original'];actual=copy.deepcopy(designs['enabled']);gm=gold['modules']['top']['cells'];am=actual['modules']['top']['cells'];changed=[];cascaded=[]
 assert set(gm)==set(am)
 for name,cell in gm.items():
  if cell['type']!='DSP48E1_DSP48E1':continue
  attrs=cell['attributes'];standalone=not attrs.get('CONSTR_PARENT','').strip() and not attrs.get('CONSTR_CHILDREN','').strip()
  if standalone:
   assert int(attrs['CONSTR_Z'],2)==6 and int(attrs['CONSTR_ABS_Z'],2)==1
   new=am[name]['attributes'];assert 'CONSTR_Z' not in new and ('CONSTR_ABS_Z' not in new or int(new['CONSTR_ABS_Z'],2)==0)
   for k in ['CONSTR_Z','CONSTR_ABS_Z']:
    if k in attrs:new[k]=attrs[k]
    else:new.pop(k,None)
   changed.append(name)
  else:assert am[name]==cell;cascaded.append(name)
 assert actual==gold,'Only standalone DSP slot constraints may differ'
 assert len(changed)==(36 if label=='soc' else 34)
 if label=='cascade':assert set(cascaded)=={first,second}
 rows.append(dict(fixture=label,disabled_pack_exact=True,only_standalone_slot_constraints_changed=True,released=len(changed),cascaded_cells_exact=cascaded));print(rows[-1],flush=True)
assert all(digest(n)==h for n,h in hashes.items())
record=dict(passed=True,tests=rows,scope='Actual packer tests only, not routed timing. Current logic and all non-placement metadata exact; two-DSP cascade fixture retains both cells and constraints exactly. Fixture is not a workload candidate.',sha256=hashes,output_sha256={str(q):digest(q) for q in outputs},full_soc_timing_accepted=False);(out/'results.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS actual standalone and cascade packer regression tests')
