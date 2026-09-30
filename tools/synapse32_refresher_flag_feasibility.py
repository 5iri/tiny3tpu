"""Prove a same-edge redundant refresher predicate; does not yet modify the SoC."""
import argparse,json,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_counter_encoding import logical,evaluate
p=argparse.ArgumentParser();p.add_argument('--route',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();rp=a.route.resolve()/'manifest.json';integrity=a.route.resolve()/'iteration-integrity.json';record=json.loads(rp.read_text());audit=json.loads(integrity.read_text());assert record['passed'] and audit['passed'] and audit['logical_cells_match_proved_patch'];source=a.route.resolve()/'input.json';assert record['sha256'][str(source)]==digest(source)
m=json.loads(source.read_text())['modules']['top'];cs=m['cells'];root=next(n for n in cs if n.endswith('$217672'));w,ports,table=logical(cs[root]);assert w==4 and table==51967;qs=[ports[f'I{i}'] for i in range(4)];drv={b:n for n,c in cs.items() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs};regs=[drv[b] for b in qs];ds=[];ces=[]
for n in regs:
 c=cs[n];assert c['type']=='SLICE_FFX' and c['attributes']['X_ORIG_TYPE']=='FDRE' and c['attributes']['X_FFSYNC'].strip()=='1' and c['parameters']=={'INIT':'0'};assert c['connections']['CK']==[156059] and c['connections']['SR']==[50991];assert len(c['connections']['D'])==1;ds+=c['connections']['D'];ces.append(c['connections']['CE'])
assert ces==[[],[],[],[137083]];assert len(set(ds+qs+[137083]))==9
# The installed packer explicitly disconnects CE only when tied to VCC.
packer=Path('/tmp/tiny3tpu-nextpnr-current/xilinx/pack.cc').resolve();pack_text=packer.read_text();assert 'ce->name == vcc' in pack_text and 'disconnect_port(ctx, ci, id_CE);' in pack_text
mask=0
for word in range(64):
 vals=[(word>>i)&1 for i in range(4)];ce=(word>>4)&1;hold=(word>>5)&1;vals[3]=vals[3] if ce else hold;mask|=evaluate(cs[root],dict(zip(qs,vals)))<<word
lines=['module proof(input clk,rst,ce,input [3:0] d,output same);','wire [3:0] q;wire expected,fd,flag;']
for i in range(4):lines.append(f"FDRE #(.INIT(1'b0)) r{i}(.C(clk),.R(rst),.CE({'ce' if i==3 else chr(49)+chr(39)+'b1'}),.D(d[{i}]),.Q(q[{i}]));")
lines.append(f"LUT4 #(.INIT(16'b{table:016b})) decode(.I0(q[0]),.I1(q[1]),.I2(q[2]),.I3(q[3]),.O(expected));")
lines.append(f"LUT6 #(.INIT(64'b{mask:064b})) next_decode(.I0(d[0]),.I1(d[1]),.I2(d[2]),.I3(d[3]),.I4(ce),.I5(q[3]),.O(fd));")
lines.extend(["FDSE #(.INIT(1'b1)) f(.C(clk),.S(rst),.CE(1'b1),.D(fd),.Q(flag));",'assign same=flag==expected;','endmodule']);out.mkdir();v=out/'miter.v';v.write_text('\n'.join(lines)+'\n');tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';ys=out/'prove.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -seq 4 -prove same 1 -verify\nsat -seq 3 -tempinduct -maxsteps 8 -prove same 1 -verify\n');log=out/'prove.log'
with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
assert 'SUCCESS!' in log.read_text();paths=[rp,integrity,source,packer,Path(__file__),Path(__file__).with_name('synapse32_packed_counter_encoding.py'),tool,lib,v,ys,log];(out/'manifest.json').write_text(json.dumps(dict(passed=True,source_lut=root,source_registers=regs,source_q_bits=qs,source_d_bits=ds,source_ces=ces,predicate_table=table,next_table=mask,flag_type='FDSE',flag_init=1,flag_clock=156059,flag_set=50991,flag_ce_constant=1,actual_primitive_induction=True,architecture_latency_added=0,soc_modified=False,new_route_run=False,scope='Same-edge predicate invariant from actual FDRE zero initial states and shared synchronous reset; source bit 3 CE hold is included. Proposed FDSE starts and synchronously sets to predicate(0)=1. No packed SoC implementation or timing result yet.',sha256={str(p.resolve()):digest(p) for p in paths}),indent=2)+'\n');print('PASS actual-primitive same-edge refresher predicate induction; SoC implementation pending')
