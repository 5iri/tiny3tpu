#!/usr/bin/env python3
"""Capture the exact timer-zero predicate on the existing decrement/reload edge."""
import argparse,copy,json,subprocess
from pathlib import Path
from synapse32_factor_branch_predicate import digest,drivers_of,lut

def cone_for(roots,cells,drivers,leaves):
 seen=set();external=set(leaves)
 def visit(bit):
  if isinstance(bit,str) or bit in external:return
  name,cell,port,index=drivers[bit]
  if name in seen:return
  assert cell['type'] in ['INV','MUXF7','MUXF8','CARRY4'] or cell['type'].startswith('LUT'),(name,cell['type'],bit)
  seen.add(name)
  for p,bs in cell['connections'].items():
   if cell['port_directions'][p]=='input':
    for b in bs:visit(b)
 for bit in roots:visit(bit)
 return {n:cells[n] for n in sorted(seen)}

def evaluate(bit,values,drivers):
 if bit in values:return values[bit]
 if isinstance(bit,str):return int(bit)
 name,c,p,i=drivers[bit];con=c['connections'];f=lambda b:evaluate(b,values,drivers)
 if c['type']=='INV':v=1-f(con['I'][0])
 elif c['type'] in ['MUXF7','MUXF8']:v=f(con['I1' if f(con['S'][0]) else 'I0'][0])
 elif c['type'].startswith('LUT'):v=(int(c['parameters']['INIT'],2)>>sum(f(con[f'I{j}'][0])<<j for j in range(int(c['type'][3:]))))&1
 else:raise ValueError((name,c['type']))
 values[bit]=v;return v

def module(cells,inputs,outputs,name):
 bits={b for c in cells.values() for bs in c['connections'].values() for b in bs if isinstance(b,int)}|set(inputs)|set(outputs)
 wire=lambda b:f'n{b}' if isinstance(b,int) else "1'b"+b
 lines=[f'module {name}(input [{len(inputs)-1}:0] x,output [{len(outputs)-1}:0] y);','wire '+','.join(wire(b) for b in sorted(bits))+';']
 lines += [f'assign n{b}=x[{i}];' for i,b in enumerate(inputs)]
 lines += [f'assign y[{i}]=n{b};' for i,b in enumerate(outputs)]
 for i,c in enumerate(cells.values()):
  params=','.join(f'.{k}({len(v)}\'b{v})' for k,v in c['parameters'].items())
  ports=','.join(f'.{p}({{{",".join(wire(b) for b in reversed(bs))}}})' for p,bs in c['connections'].items())
  lines += [f'{c["type"]} '+(f'#({params}) ' if params else '')+f'c{i}({ports});']
 return '\n'.join(lines+['endmodule'])

def main():
 p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();parent=a.parent.resolve();out=a.out.resolve();assert not out.exists()
 source=parent/'board/soc.json';gold=json.loads(source.read_text());m=gold['modules']['kc705_synapse32_top'];cells=m['cells'];drivers=drivers_of(cells)
 count=m['netnames']['memory.main_zqcs_timer_count0']['bits'];assert len(count)==27
 counter={drivers[b][0]:drivers[b][1] for b in count};initial=0
 for i,b in enumerate(count):
  c=drivers[b][1];assert c['type'] in ['FDRE','FDSE'] and c['connections']['C']==[37425] and c['connections']['CE']==['1']
  assert c['connections']['R' if c['type']=='FDRE' else 'S']==[31262]
  init=int(c['parameters']['INIT'],2);assert init==int(c['type']=='FDSE');initial |=init<<i
 assert initial==99999999
 controls=[1873,1880,1915,1916];root=1870;target,old,port,index=drivers[root];assert old['type']=='MUXF7' and port=='O'
 leaves=count+controls;cone=cone_for([root],cells,drivers,leaves);mask=0
 for word in range(32):
  zero=word&1;sample_count=0 if zero else 1;values={b:(sample_count>>i)&1 for i,b in enumerate(count)};values.update({b:(word>>(i+1))&1 for i,b in enumerate(controls)})
  mask |=evaluate(root,values,drivers)<<word
 allbits={b for c in cells.values() for bs in c['connections'].values() for b in bs if isinstance(b,int)}|{b for n in m['netnames'].values() for b in n['bits'] if isinstance(b,int)}|{b for n in m['ports'].values() for b in n['bits'] if isinstance(b,int)};fresh=max(allbits)+1
 added={};groups=[]
 for i,start in enumerate(range(0,27,6)):
  bit=fresh+i;groups.append(bit);added[f'$tiny3tpu$zqcs_one_group_{i}']=lut(count[start:start+6],bit,1<<(1 if start==0 else 0))
 d=fresh+5;flag=fresh+6;added['$tiny3tpu$zqcs_one']=lut(groups,d,1<<31)
 added['$tiny3tpu$zqcs_zero_q']=dict(hide_name=0,type='FDRE',parameters={'INIT':'0'},attributes={'keep':'1'},port_directions={'C':'input','CE':'input','D':'input','R':'input','Q':'output'},connections={'C':[37425],'CE':['1'],'D':[d],'R':[31262],'Q':[flag]})
 replacement=lut([flag]+controls,root,mask)
 actual=copy.deepcopy(gold);ac=actual['modules']['kc705_synapse32_top']['cells'];assert not set(ac)&set(added);ac.update(added);ac[target]=replacement
 restored=copy.deepcopy(actual);rc=restored['modules']['kc705_synapse32_top']['cells'];rc[target]=old
 for n in added:del rc[n]
 assert restored==gold
 out.mkdir();proof=out/'predicate-proof';proof.mkdir();yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v'
 abstraction=module(cone,leaves,[root],'gold')+f"\nmodule candidate(input [30:0] x,output y);wire z=(x[26:0]==0);LUT5 #(.INIT(32'b{mask:032b})) l(.I0(z),.I1(x[27]),.I2(x[28]),.I3(x[29]),.I4(x[30]),.O(y));endmodule\nmodule proof(input [30:0] x,output same);wire a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n"
 data_cone=cone_for([c['connections']['D'][0] for c in counter.values()],cells,drivers,count)
 state_cells={**data_cone,**counter,**added};state=module(state_cells,[37425,31262],count+[flag],'state')+"\nmodule proof(input [1:0] x,output same);wire [27:0] y;state s(x,y);assign same=y[27]==(y[26:0]==0);endmodule\n"
 for name,text,sequential in [('abstraction',abstraction,False),('state',state,True)]:
  v=proof/(name+'.v');v.write_text(text);ys=proof/(name+'.ys');ys.write_text(f'read_verilog {lib} {v}\nprep -top proof; flatten; opt; check -assert; '+('sat -seq 3 -tempinduct -maxsteps 8 -prove same 1 -verify;' if sequential else 'sat -prove same 1 -verify;')+'\n')
  with (proof/(name+'.log')).open('w') as f:subprocess.run([str(yosys),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
 paths=[source,yosys,lib,Path(__file__).resolve(),Path(__file__).with_name('synapse32_factor_branch_predicate.py').resolve()]+list(proof.iterdir())
 record=dict(passed=True,claim='Actual mapped 27-bit timer and reload value 99999999. Full 31-input SAT proves its control output depends on count only through zero. Actual counter/DSP-free combinational cells and FDRE/FDSE primitives prove the added zero FF equals count==0 by induction from specified INIT, for arbitrary synchronous reload. The predicate uses the existing counter edge; maintenance-event latency is unchanged.',count=count,controls=controls,root=root,target=target,cone=cone,counter=counter,data_cone=data_cone,added=added,replacement=replacement,added_latency_cycles=0,sha256={str(q):digest(q) for q in paths});(proof/'results.json').write_text(json.dumps(record,indent=2)+'\n')
 board=out/'board';board.mkdir();(board/'soc.json').write_text(json.dumps(actual,separators=(',',':'))+'\n')
 for n in ['kc705.xdc','firmware.hex','synth.ys']:(board/n).write_bytes((parent/'board'/n).read_bytes())
 record=dict(passed=True,kind='captured_zqcs_zero',parent=str(parent),source=str(source),proof=str(proof/'results.json'),target=target,original_cell=old,candidate_cell=replacement,added=added,added_latency_cycles=0,new_rtl_synthesis_run=False,new_workload_simulation_run=False,full_soc_timing_accepted=False,checked_manifests=[dict(path=str(q),sha256=digest(q)) for q in [parent/'mapping.json',parent/'iteration-integrity.json',proof/'results.json']],sha256={str(q):digest(q) for q in [source,Path(__file__).resolve()]},output_sha256={str(q):digest(q) for q in board.iterdir()});(out/'mapping.json').write_text(json.dumps(record,indent=2)+'\n');print('PASS complete control SAT and actual timer/zero-flag induction; no event-cycle change')
if __name__=='__main__':main()
