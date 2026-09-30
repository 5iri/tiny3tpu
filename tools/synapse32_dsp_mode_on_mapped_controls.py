"""Probe exact DSP mode A->P arcs using source SDF; not a Kintex signoff model."""
import argparse,hashlib,json,re
from collections import Counter
from pathlib import Path
from synapse32_analyze_timing_endpoints import analyze
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--route',type=Path,required=True);p.add_argument('--graph',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();root=Path(__file__).resolve().parents[1];route=a.route.resolve();out=a.out.resolve();out.mkdir(exist_ok=False)
sdf=Path('/tmp/tiny3tpu-nextpnr-current/xilinx/external/prjxray-db/artix7/timings/DSP_R.sdf');s=sdf.read_text();mode='DSP48E1_AREG_0_A_INPUT_DIRECT_MREG_0_PREG_0_USE_DPORT_FALSE_USE_MULT_MULTIPLY';block=s.split('(CELLTYPE "'+mode+'")',1)[1].split('(CELLTYPE ',1)[0];line=next(v for v in block.splitlines() if '(IOPATH A P ' in v);values=re.findall(r'\d+\.\d+',line);assert values==['0.609','1.642','1.391','3.841'];delay_ns=3.841
cells=json.loads((route/'routed.json').read_text())['modules']['top']['cells'];targets=set()
for name,c in cells.items():
 if c['type']!='DSP48E1_DSP48E1':continue
 param=c['parameters']
 if all(param.get(k)==v for k,v in {'USE_DPORT':'FALSE','USE_MULT':'MULTIPLY','A_INPUT':'DIRECT','AREG':'0'*32,'MREG':'0'*32,'PREG':'0'*32,'ADREG':'0'*32}.items()):targets.add(name)
assert targets, 'No exact-mode DSPs'
graph=a.graph.resolve();new=out/'mode-graph.tsv';count=Counter()
with graph.open() as src,new.open('w') as dst:
 assert next(src).rstrip()=='VERSION\t1';dst.write('VERSION\t1\n')
 for line in src:
  v=line.rstrip('\n').split('\t')
  if v[0]=='CELLARC' and v[1] in targets and re.fullmatch(r'A\d+',v[2]) and re.fullmatch(r'P\d+',v[3]):
   assert abs(float(v[4])-5.4)<1e-6;v[4]=str(delay_ns);count[v[1]]+=1
  dst.write('\t'.join(v)+'\n')
assert count and set(count)==targets,(len(count),len(targets))
result=analyze(new);assert not result['unresolved_nodes'];(out/'analysis.json').write_text(json.dumps(result,indent=2)+'\n')
r=dict(exact_mode=mode,source_sdf=str(sdf),source_sdf_arc=line.strip(),sensitivity_delay_ns=delay_ns,baseline_model_delay_ns=5.4,mode_matched_dsp_cells=len(targets),changed_arcs=sum(count.values()),maxima=result['maxima'],scope='Sensitivity only: Artix-7 SDF mode-specific A->P max replaces pooled 5.4 ns on exact-mode DSPs. Artix timing is not qualified as Kintex-7 -2 timing. All remaining symbolic primitive/route/clock/DDR limits remain. No physical Fmax claim.',physical_timing_accepted=False,sha256={str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in [sdf,graph,route/'routed.json',new,Path(__file__).resolve()]});(out/'manifest.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({'mode_matched_dsp_cells':r['mode_matched_dsp_cells'],'changed_arcs':r['changed_arcs'],'worst_ns':max(v['arrival_ns'] for v in result['maxima']),'physical_timing_accepted':False}))
