#!/usr/bin/env python3
"""Apply the formally checked four-DSP MREG-to-PREG mapping to a frozen netlist."""
import argparse,copy,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def check(p):
 d=json.loads(p.read_text());assert d['passed']
 for key in ['sha256','output_sha256']:
  for n,h in d.get(key,{}).items():assert digest(n)==h,(p,n)
 return d
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists()
parent=ROOT/'build-ddr-uart-prefix';source=parent/'board/soc.json';proof_path=ROOT/'build-cpu-dsp-preg-proof/results.json';proof=check(proof_path)
assert proof['sha256'][str(source)]==digest(source);synthesis=check(parent/'board/synthesis.json')
for q in [parent/'smoke/results.json',parent/'gemm/results.json']:assert check(q)['all_profile_metrics_dma_exact']
original=json.loads(source.read_text());mapped=copy.deepcopy(original);m=mapped['modules']['kc705_synapse32_top'];cells=m['cells']
used={b for c in cells.values() for pn,bs in c['connections'].items() if c['port_directions'][pn]=='input' for b in bs if isinstance(b,int)}
used.update(b for port in m['ports'].values() if port['direction']=='output' for b in port['bits'] if isinstance(b,int))
changes=[]
for r in proof['profiles']:
 name=r['cell'];c=cells[name];assert c['type']=='DSP48E1'
 for pn,bs in c['connections'].items():
  if c['port_directions'][pn]=='output' and any(b in used for b in bs):assert pn=='P',(name,pn)
 old=copy.deepcopy(c);assert int(c['parameters']['MREG'],2)==1 and int(c['parameters']['PREG'],2)==0
 c['parameters']['MREG']='0'*32;c['parameters']['PREG']='0'*31+'1'
 c['connections']['CEP']=old['connections']['CEM'];c['connections']['RSTP']=old['connections']['RSTM']
 c['connections']['CEM']=['1'];c['connections']['RSTM']=['0']
 c['port_directions'].update(CEP='input',RSTP='input',CEM='input',RSTM='input')
 changes.append(dict(cell=name,original=old,candidate=copy.deepcopy(c),observable_outputs=['P']))
restored=copy.deepcopy(mapped)
for r in changes:restored['modules']['kc705_synapse32_top']['cells'][r['cell']]=r['original']
assert restored==original and len(changes)==4
board=out/'board';board.mkdir(parents=True)
(board/'soc.json').write_text(json.dumps(mapped,separators=(',',':'))+'\n')
for name in ['kc705.xdc','firmware.hex','synth.ys']:(board/name).write_bytes((parent/'board'/name).read_bytes())
inputs=[source,proof_path,parent/'board/synthesis.json',parent/'smoke/results.json',parent/'gemm/results.json',Path(__file__).resolve()]+[parent/'board'/n for n in ['kc705.xdc','firmware.hex','synth.ys']]
outputs=list(board.iterdir())
record=dict(passed=True,parent=str(parent),source=str(source),proof=str(proof_path),mapping_changes=changes,all_other_cells_connections_parameters_exact=True,firmware_identical=True,constraints_identical=True,added_latency_cycles=0,
 scope='Derived from the real frozen Yosys synthesis, followed by a proved DSP register mapping. This is not a fresh RTL synthesis. The copied synth.ys is provenance only and still names the parent paths; do not rerun it in this derived directory. Functional workloads are the parent CPU/DMA/TPU runs composed with the actual DSP-model induction; no new RTL workload run is claimed.',
 checked_manifests=[dict(path=str(q),sha256=digest(q)) for q in [proof_path,parent/'board/synthesis.json',parent/'smoke/results.json',parent/'gemm/results.json']],sha256={str(q):digest(q) for q in inputs},output_sha256={str(q):digest(q) for q in outputs},full_soc_timing_accepted=False)
(out/'mapping.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS four proved DSP mappings; all other netlist content and constraints exact')
