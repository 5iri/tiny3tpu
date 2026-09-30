import json,re,subprocess,hashlib,argparse
from pathlib import Path
root=Path.cwd();p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();source=a.source.resolve();out=a.out.resolve();assert not out.exists();out.mkdir()
yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v'
s=lib.read_text();s=s[s.index('module DSP48E1 ('):];s=s[:s.index('endmodule')+len('endmodule')];model=out/'DSP48E1.v';assert not model.exists();model.write_text(s+'\n')
m=json.loads(source.read_text())['modules']['kc705_synapse32_top'];cells={n:c for n,c in m['cells'].items() if c['type']=='DSP48E1' and 'cpu' in n};assert len(cells)==4
records=[]
def literal(v):return str(len(v))+"'b"+v if re.fullmatch('[01xz]+',v) else json.dumps(v)
for index,(name,cell) in enumerate(cells.items()):
 d=out/str(index);d.mkdir();params=cell['parameters'];assert int(params['MREG'],2)==0 and int(params['PREG'],2)==1
 ports=cell['connections'];assert ports['OPMODE']==['1','0','1','0','0','0','0']
 inputs=[];conn={};outputs=['P','PCOUT']
 for p,bs in ports.items():
  if cell['port_directions'][p]!='input':continue
  if any(isinstance(b,int) for b in bs):
   inputs.append('input wire '+(f'[{len(bs)-1}:0] ' if len(bs)>1 else '')+'i_'+p)
  values=[('i_'+p+(f'[{i}]' if len(bs)>1 else '')) if isinstance(b,int) else "1'b"+b for i,b in enumerate(bs)]
  conn[p]='{'+','.join(reversed(values))+'}' if len(values)>1 else values[0]
 widths={'P':48,'PCOUT':48,'ACOUT':30,'BCOUT':18}
 text='module proof('+','.join(inputs)+',output same);\n'
 for which in ['gold','actual']:
  for p in outputs:text+=f'wire [{widths[p]-1}:0] {which}_{p};\n'
  cfg=dict(params);wires=dict(conn)
  if which=='actual':
   wires['A']="{5'b0,"+','.join(('i_A['+str(i)+']') if isinstance(ports['A'][i],int) else "1'b"+ports['A'][i] for i in reversed(range(25)))+'}' 
  wires.update({p:which+'_'+p for p in outputs})
  text+='DSP48E1 #('+','.join('.'+k+'('+literal(v)+')' for k,v in cfg.items())+') '+which+'('+','.join('.'+k+'('+v+')' for k,v in wires.items())+');\n'
 text+='assign same='+' && '.join('(gold_'+p+'==actual_'+p+')' for p in outputs)+';\nendmodule\n';v=d/'proof.v';v.write_text(text)
 ys=d/'proof.ys';ys.write_text(f'read_verilog {model} {v}\nprep -top proof; flatten; opt; check -assert; sat -seq 3 -set-init-zero -tempinduct -maxsteps 8 -prove same 1 -verify;\n')
 with (d/'proof.log').open('w') as log:
  try:r=subprocess.run([str(yosys),'-Q','-T','-s',str(ys)],stdout=log,stderr=subprocess.STDOUT,timeout=120);rc=r.returncode;timeout=False
  except subprocess.TimeoutExpired:rc=None;timeout=True
 records.append(dict(cell=name,areg=int(params['AREG'],2),breg=int(params['BREG'],2),passed=rc==0,returncode=rc,timed_out=timeout));print(records[-1],flush=True)
 if rc!=0:break
paths=[source,lib,model,Path(__file__).resolve(),yosys]+[p for p in out.glob('*/*') if p.is_file()]
record=dict(passed=len(records)==4 and all(r['passed'] for r in records),profiles=records,claim='Actual synthesized pure-multiply DSP parameter/control profiles; Pure multiply A[29:25] tied to zero. Temporal induction from common zero/reset state compares P and PCOUT under arbitrary live inputs. Other output observability must be checked before applying a netlist transform.',sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
(out/'results.json').write_text(json.dumps(record,indent=2)+'\n')
raise SystemExit(0 if record['passed'] else 2)
