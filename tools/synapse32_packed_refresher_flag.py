"""Insert an inductively proved same-edge refresher predicate into the packed SoC."""
import gc
gc.disable()
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_ddr_dead_macro_cleanup import apply_verified as apply_base
from synapse32_packed_counter_encoding import logical
from synapse32_packed_selector_patch_v4 import packed
FLAG='$tiny3tpu$refresher_predicate_flag'
NET='$tiny3tpu$refresher_predicate_next'
FIELDS=['passed','checkpoint','original_cells','replacements','added_cells','added_netnames','placements','added_latency_cycles','removed_cells','removed_netnames']

def derive(m,fresh):
 cs=m['cells'];root=next(n for n in cs if n.endswith('$217672'));old=cs[root];w,p,table=logical(old)
 assert w==4 and table==51967 and [p[f'I{i}'] for i in range(4)]==[54777,54779,54736,54773] and p['O']==54724
 assert not any(k.startswith('CONSTR_') for k in old['attributes'])
 regs=[next(n for n in cs if n.endswith('slice$'+s)) for s in ['67247','66879','79207','79208']]
 ds=[138457,135004,199437,55756]
 directions={'CK':'input','SR':'input','D':'input','CE':'input','Q':'output'}
 roles={'CK':'C','SR':'R','D':'D','CE':'CE','Q':'Q'}
 for i,n in enumerate(regs):
  c=cs[n];assert c['type']=='SLICE_FFX' and c['parameters']=={'INIT':'0'} and c['attributes']['X_ORIG_TYPE']=='FDRE' and c['attributes']['X_FFSYNC'].strip()=='1'
  assert c['port_directions']==directions
  assert all(c['attributes']['X_ORIG_PORT_'+k]==v for k,v in roles.items())
  assert c['connections']==dict(CK=[156059],SR=[50991],D=[ds[i]],CE=[137083] if i==3 else [],Q=[p[f'I{i}']])
 template=next(n for n in cs if n.endswith('slice$78002'));f=copy.deepcopy(cs[template]);assert f['type']=='SLICE_FFX' and f['parameters']=={'INIT':'1'} and f['attributes']['X_ORIG_TYPE']=='FDSE' and f['attributes']['X_FFSYNC'].strip()=='1' and f['port_directions']==directions
 assert all(f['attributes']['X_ORIG_PORT_'+k]==('S' if k=='SR' else v) for k,v in roles.items())
 f['attributes']={k:v for k,v in f['attributes'].items() if not k.startswith('CONSTR_') and k not in ['NEXTPNR_BEL','BEL_STRENGTH']}
 f['connections']=dict(CK=[156059],SR=[50991],D=[fresh],CE=[],Q=[54724])
 mask=0
 for word in range(64):
  q3=((word>>3)&1) if word&16 else ((word>>5)&1)
  mask|=((table>>((word&7)|(q3<<3)))&1)<<word
 lut=packed(ds+[137083,54773],fresh,mask)
 lut['hide_name']=old['hide_name'];lut['attributes'].update({k:v for k,v in old['attributes'].items() if not k.startswith('X_ORIG_PORT_') and k not in ['X_ORIG_TYPE','MUX_TREE_ROOT']})
 return root,regs,template,lut,f,table,mask

def miter(table,mask):
 lines=['module proof(input clk,rst,ce,input [3:0] d,output same);','wire [3:0] q;wire expected,fd,flag;']
 for i in range(4):
  ce='ce' if i==3 else "1'b1"
  lines.append(f"FDRE #(.INIT(1'b0)) r{i}(.C(clk),.R(rst),.CE({ce}),.D(d[{i}]),.Q(q[{i}]));")
 lines.extend([f"LUT4 #(.INIT(16'b{table:016b})) decode(.I0(q[0]),.I1(q[1]),.I2(q[2]),.I3(q[3]),.O(expected));",f"LUT6 #(.INIT(64'b{mask:064b})) next_decode(.I0(d[0]),.I1(d[1]),.I2(d[2]),.I3(d[3]),.I4(ce),.I5(q[3]),.O(fd));","FDSE #(.INIT(1'b1)) f(.C(clk),.S(rst),.CE(1'b1),.D(fd),.Q(flag));",'assign same=flag==expected;','endmodule'])
 return '\n'.join(lines)+'\n'

def validate(patch,prior,base):
 m=base['modules']['top'];cs=m['cells'];fresh=patch['refresher_next_bit'];root,regs,template,lut,flag,table,mask=derive(m,fresh)
 bits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for n in m['netnames'].values() for b in n['bits']}|{b for p in m['ports'].values() for b in p['bits']}
 assert isinstance(fresh,int) and fresh not in bits and FLAG not in cs and NET not in m['netnames']
 assert patch['refresher_source_cells']=={n:cs[n] for n in [root,*regs,template]}
 assert root not in prior['replacements'] and root not in prior['original_cells']
 assert patch['original_cells']=={**prior['original_cells'],root:cs[root]}
 assert patch['replacements']=={**prior['replacements'],root:lut}
 assert patch['added_cells']=={**prior['added_cells'],FLAG:flag}
 assert patch['added_netnames']=={**prior['added_netnames'],NET:dict(hide_name=0,bits=[fresh],attributes={})}
 for k in ['checkpoint','removed_cells','removed_netnames','added_latency_cycles']:assert patch[k]==prior[k]
 assert patch['added_latency_cycles']==0 and patch['redundant_refresher_ff_added']==1
 assert set(patch['placements'])==set(prior['placements'])|{root,FLAG}
 for n,v in prior['placements'].items():
  if n!=root:assert patch['placements'][n]==v
 assert patch['placements'][root].endswith('6LUT') and patch['placements'][FLAG]==patch['placements'][root][:-4]+'FF'
 proof=patch['refresher_proof'];v=Path(proof['miter']);assert v.read_text()==miter(table,mask)
 for n,h in proof['sha256'].items():assert digest(n)==h,n
 assert 'SUCCESS!' in Path(proof['log']).read_text() and 'Induction step proven: SUCCESS!' in Path(proof['log']).read_text()
 contract=Path(proof['packer_contract']).read_text();assert 'ce->name == vcc' in contract and 'disconnect_port(ctx, ci, id_CE);' in contract
 cs[root]=copy.deepcopy(lut);cs[FLAG]=copy.deepcopy(flag);m['netnames'][NET]=copy.deepcopy(patch['added_netnames'][NET])
 return base

def apply_verified(patch,design):
 assert patch['passed'];bp=Path(patch['refresher_base_path']);assert digest(bp)==patch['refresher_base_sha256'];prior=json.loads(bp.read_text());return validate(patch,prior,apply_base(prior,design))

def main():
 p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--reference',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();bp=a.base_patch.resolve();out=a.out.resolve();assert not out.exists();prior=json.loads(bp.read_text());rp=a.reference.resolve()/'manifest.json';record=json.loads(rp.read_text());assert record['passed'] and Path(record['patch']).resolve()==bp
 for d in [prior,record]:
  for k in ['sha256','output_sha256']:
   for n,h in d.get(k,{}).items():assert digest(n)==h,n
 cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);m=base['modules']['top'];bits={b for c in m['cells'].values() for bs in c['connections'].values() for b in bs}|{b for n in m['netnames'].values() for b in n['bits']}|{b for p in m['ports'].values() for b in p['bits']};fresh=max(b for b in bits if isinstance(b,int))+1
 root,regs,template,lut,flag,table,mask=derive(m,fresh);patch={k:copy.deepcopy(prior[k]) for k in FIELDS};patch.update(kind='packed_same_edge_refresher_flag',refresher_base_path=str(bp),refresher_base_sha256=digest(bp),refresher_next_bit=fresh,redundant_refresher_ff_added=1,refresher_source_cells={n:m['cells'][n] for n in [root,*regs,template]})
 patch['original_cells'][root]=m['cells'][root];patch['replacements'][root]=lut;patch['added_cells'][FLAG]=flag;patch['added_netnames'][NET]=dict(hide_name=0,bits=[fresh],attributes={})
 ref=a.reference.resolve()/'routed.json';placed=json.loads(ref.read_text())['modules']['top']['cells'];occupied={c['attributes']['NEXTPNR_BEL'] for n,c in placed.items() if n!=root};sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')}
 bad={c['attributes']['NEXTPNR_BEL'].split('/')[0] for c in placed.values() if c['type'] in ['SLICE_FFX','CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE','').startswith(('RAM','SRL'))}
 free=[s+'/'+l for s in sites-bad for l in 'ABCD' if all(s+'/'+l+t not in occupied for t in ['5LUT','6LUT','FF','5FF'])];assert free
 def distance(s):
  x,y=map(int,re.search(r'SLICE_X(\d+)Y(\d+)',s).groups());return (abs(x-119)+abs(y-49),s)
 chosen=min(free,key=distance);patch['placements'][root]=chosen+'6LUT';patch['placements'][FLAG]=chosen+'FF'
 out.mkdir();v=out/'miter.v';v.write_text(miter(table,mask));tool=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=tool.parents[1]/'share/yosys/xilinx/cells_sim.v';contract=Path('build-grade2-refresher-flag-feasibility/packer-ce-contract.cc').resolve();ys=out/'prove.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -seq 4 -prove same 1 -verify\nsat -seq 3 -tempinduct -maxsteps 8 -prove same 1 -verify\n');log=out/'prove.log'
 with log.open('w') as f:subprocess.run([str(tool),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
 patch['refresher_proof']=dict(miter=str(v),log=str(log),packer_contract=str(contract),sha256={str(q.resolve()):digest(q) for q in [v,ys,log,tool,lib,contract]})
 validate(patch,prior,base);patch['sha256']=dict(prior['sha256']);patch['sha256'].update(patch['refresher_proof']['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,rp,ref,source,Path(__file__),Path(__file__).with_name('synapse32_packed_ddr_dead_macro_cleanup.py'),Path(__file__).with_name('synapse32_packed_selector_patch_v4.py'),Path(__file__).with_name('synapse32_packed_counter_encoding.py')]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,added_redundant_ff=1,added_luts=0,added_latency_cycles=0,placement=chosen,actual_primitive_induction=True)))
if __name__=='__main__':main()
