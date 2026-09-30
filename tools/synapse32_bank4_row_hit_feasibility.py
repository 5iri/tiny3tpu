"""Prove prospective same-edge bank4 row-hit lookahead with exact source registers."""
import argparse,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_counter_encoding import logical,evaluate,emit
p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--cone',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();m=json.loads(a.source.read_text())['modules']['top'];cs=m['cells'];record=json.loads(a.cone.read_text());cone=record['combinational_cells'];leaves=record['leaf_cells'];assert all(cs[n]==c for n,c in {**cone,**leaves}.items());regs={n:c for n,c in leaves.items() if c['type']=='SLICE_FFX'};assert len(regs)==29
for c in regs.values():
 assert c['attributes']['X_ORIG_TYPE']=='FDRE' and c['parameters']=={'INIT':'0'} and c['attributes']['X_FFSYNC'].strip()=='1' and c['connections']['CK']==[156059]
 assert all(c['attributes']['X_ORIG_PORT_'+p]==v for p,v in dict(CK='C',SR='R',CE='CE',D='D',Q='Q').items())
 assert c['port_directions']==dict(CK='input',SR='input',D='input',CE='input',Q='output')
ground=cs['$PACKER_GND_DRV'];vcc=cs['$PACKER_VCC_DRV'];assert ground['type']=='PSEUDO_GND' and vcc['type']=='PSEUDO_VCC';assert [b for p,bs in ground['connections'].items() if ground['port_directions'][p]=='output' for b in bs]==[241167];assert [b for p,bs in vcc['connections'].items() if vcc['port_directions'][p]=='output' for b in bs]==[241169]
op=[n for n,c in regs.items() if c['connections']['SR']==[138431]];assert len(op)==1;op=op[0];oc=regs[op];assert oc['connections']['CE']==[79604] and oc['connections']['D']==[241169];ob=oc['connections']['Q'][0]
pipes=sorted(c['connections']['Q'][0] for c in regs.values() if c['connections']['CE']==[138906]);rows=sorted(c['connections']['Q'][0] for c in regs.values() if c['connections']['CE']==[79604] and c['connections']['SR']==[50991]);assert len(pipes)==len(rows)==14
for c in regs.values():assert c['connections']['SR']==[138431 if c is oc else 50991]
available={b for c in leaves.values() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};pending=dict(cone);order={}
while pending:
 ready=[n for n,c in pending.items() if {b for p,b in logical(c)[1].items() if p!='O'}<=available];assert ready
 for n in ready:c=pending.pop(n);order[n]=c;available.add(logical(c)[1]['O'])
output=logical(cone[record['root']])[1]['O']
def old_value(over):
 vs={c['connections']['Q'][0]:0 for c in regs.values()}|{241167:0}|over
 for c in order.values():vs[logical(c)[1]['O']]=evaluate(c,vs)
 return vs[output]
assert old_value({})==0 and old_value({ob:1})==1;matching={b:[r for r in rows if old_value({ob:1,b:1,r:1})==1] for b in pipes};assert all(len(v)==1 for v in matching.values());rows=[matching[b][0] for b in pipes];assert len(set(rows))==14
byq={c['connections']['Q'][0]:n for n,c in regs.items()};pn=[byq[b] for b in pipes];rn=[byq[b] for b in rows];dp=[regs[n]['connections']['D'][0] for n in pn];dr=[regs[n]['connections']['D'][0] for n in rn];assert len(set(pipes+rows+[ob]))==29
mask=0
for word in range(64):
 b=[(word>>i)&1 for i in range(6)];mask|=int((b[0] if b[4] else b[1])==(b[2] if b[5] else b[3]))<<word
old=emit(cone,[*pipes,*rows,ob,241167],[output],'old_predicate');lines=['module proof(input clk,r_common,r_open,ce_pipe,ce_row,input [13:0] dp,dr,output same);','wire [13:0] qp,qr,e;wire qo,expected,open_next,a0,a1,a2,fd,flag;']
for i in range(14):
 lines.append(f"FDRE #(.INIT(1'b0)) p{i}(.C(clk),.R(r_common),.CE(ce_pipe),.D(dp[{i}]),.Q(qp[{i}]));")
 lines.append(f"FDRE #(.INIT(1'b0)) r{i}(.C(clk),.R(r_common),.CE(ce_row),.D(dr[{i}]),.Q(qr[{i}]));")
 lines.append(f"LUT6 #(.INIT(64'b{mask:064b})) e{i}(.I0(dp[{i}]),.I1(qp[{i}]),.I2(dr[{i}]),.I3(qr[{i}]),.I4(ce_pipe),.I5(ce_row),.O(e[{i}]));")
lines.extend(["FDRE #(.INIT(1'b0)) o(.C(clk),.R(r_open),.CE(ce_row),.D(1'b1),.Q(qo));","old_predicate g({1'b0,qo,qr,qp},expected);","LUT2 #(.INIT(4'b1110)) onext(.I0(qo),.I1(ce_row),.O(open_next));","LUT6 #(.INIT(64'h8000000000000000)) and0(.I0(e[0]),.I1(e[1]),.I2(e[2]),.I3(e[3]),.I4(e[4]),.I5(e[5]),.O(a0));","LUT6 #(.INIT(64'h8000000000000000)) and1(.I0(e[6]),.I1(e[7]),.I2(e[8]),.I3(e[9]),.I4(e[10]),.I5(e[11]),.O(a1));","LUT2 #(.INIT(4'b1000)) and2(.I0(e[12]),.I1(e[13]),.O(a2));","LUT5 #(.INIT(32'hff800000)) next_hit(.I0(a0),.I1(a1),.I2(a2),.I3(r_common),.I4(open_next),.O(fd));","FDRE #(.INIT(1'b0)) f(.C(clk),.R(r_open),.CE(1'b1),.D(fd),.Q(flag));",'assign same=flag==expected;','endmodule']);text=old+'\n'+'\n'.join(lines)+'\n';out.mkdir();tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';paths=[a.source,a.cone,Path(__file__),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),tool,lib];checks=[]
cases={'correct':text,'wrong_flag_init':text.replace("FDRE #(.INIT(1'b0)) f", "FDRE #(.INIT(1'b1)) f"),'ignored_open_reset':text.replace(".R(r_open),.CE(1'b1),.D(fd)",".R(1'b0),.CE(1'b1),.D(fd)"),'ignored_pipe_hold':text.replace('.I4(ce_pipe)',".I4(1'b1)"),'ignored_row_hold':text.replace('.I5(ce_row)',".I5(1'b1)"),'ignored_common_reset':text.replace('.I3(r_common)',".I3(1'b0)")}
for name,vt in cases.items():
 v=out/(name+'.v');v.write_text(vt);ys=out/(name+'.ys');ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -seq 4 -prove same 1 -verify\n'+('sat -seq 3 -tempinduct -maxsteps 8 -prove same 1 -verify\n' if name=='correct' else ''));log=out/(name+'.log')
 with log.open('w') as f:rc=subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT).returncode
 if name=='correct':assert rc==0 and 'Induction step proven: SUCCESS!' in log.read_text()
 else:assert rc!=0 and 'proof did fail' in log.read_text(),name
 checks.append(dict(name=name,expected_outcome_verified=True));paths.extend([v,ys,log])
(out/'manifest.json').write_text(json.dumps(dict(passed=True,source_root=record['root'],source_registers=regs,pipe_registers=pn,row_registers=rn,open_register=op,pipe_q=pipes,row_q=rows,open_q=ob,pipe_d=dp,row_d=dr,predicate_output=output,eq_lut6_table=mask,flag_clock=156059,flag_reset=138431,common_source_reset=50991,ce_pipe=138906,ce_row=79604,flag_init=0,prospective_candidate_luts=19,prospective_added_ff=1,actual_primitive_induction=True,checks=checks,soc_modified=False,new_route_run=False,scope='Prospective same-edge row-hit invariant including both independent source CE holds, separate row-open reset, common address reset, actual source INITs and constant drivers. The 29 original source registers stay unchanged. Packed implementation and all timing checks are still pending.',sha256={str(q.resolve()):digest(q) for q in paths}),indent=2)+'\n');print('PASS bank4 same-edge row-hit primitive induction and five negative controls; no packed edit or route yet')
