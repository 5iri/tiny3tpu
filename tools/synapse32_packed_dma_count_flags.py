"""Maintain exact nonzero flags on the existing DMA count capture edges."""
import gc
gc.disable()
import argparse,copy,json,re,subprocess
from pathlib import Path
from synapse32_apply_bram_timing import digest
from synapse32_packed_wdata_capture_replicas import apply_verified as apply_base
from synapse32_packed_branch_carry_cuts_v2 import abstract
from synapse32_factor_branch_predicate import drivers_of,evaluate,verilog
from synapse32_packed_selector_patch_v4 import packed
from synapse32_packed_counter_encoding import logical
PREFIX='$tiny3tpu$op_count_'


def counters(m):
    cs=m['cells'];bits=[m['netnames'][f'soc.dma.engine.axi_dma_wr_inst.op_word_count_reg[{i}]']['bits'][0] for i in range(16)];regs=[]
    for bit in bits:
        matches=[(n,c) for n,c in cs.items() if c['type']=='SLICE_FFX' and c['connections'].get('Q')==[bit]];assert len(matches)==1;n,c=matches[0]
        assert c['attributes']['X_ORIG_TYPE']=='FDRE' and c['parameters']=={'INIT':'0'} and not c['connections'].get('SR') and c['attributes']['X_FFSYNC'].strip()=='1';regs.append(n)
    clock=cs[regs[0]]['connections']['CK'];assert len(clock)==1 and all(cs[n]['connections']['CK']==clock for n in regs)
    assert all(cs[n]['connections']['CE']==cs[regs[0]]['connections']['CE'] for n in regs[:6]);assert all(cs[n]['connections']['CE']==cs[regs[6]]['connections']['CE'] for n in regs[6:]);assert cs[regs[0]]['connections']['CE']!=cs[regs[6]]['connections']['CE']
    return bits,regs


def construct(m):
    cs=m['cells'];bits,regs=counters(m);allbits={b for c in cs.values() for bs in c['connections'].values() for b in bs}|{b for v in m['netnames'].values() for b in v['bits']}|{b for v in m['ports'].values() for b in v['bits']};fresh=max(b for b in allbits if isinstance(b,int))+1;added={};nets={}
    def allocate(name,c):
        nonlocal fresh
        assert name not in cs and name not in added;bit=fresh;fresh+=1;added[name]=c(bit);nets[name+'$net']=dict(hide_name=1,bits=[bit],attributes={});return bit
    def or_lut(label,ins):return allocate(PREFIX+label,lambda bit:packed(ins,bit,(1<<(1<<len(ins)))-2))
    def flag(label,index,d):
        def cell(bit):
            c=copy.deepcopy(cs[regs[index]]);c['connections']['D']=[d];c['connections']['Q']=[bit];c['attributes']={k:v for k,v in c['attributes'].items() if not k.startswith('CONSTR_') and k not in ['NEXTPNR_BEL','BEL_STRENGTH']};return c
        return allocate(PREFIX+label,cell)
    ds=[cs[n]['connections']['D'][0] for n in regs];lo=or_lut('lo_d',ds[:6]);lq=flag('lo_q',0,lo);hi0=or_lut('hi_d0',ds[6:11]);hi1=or_lut('hi_d1',ds[11:]);hi=or_lut('hi_d',[hi0,hi1]);hq=flag('hi_q',6,hi);pred=or_lut('nonzero',[lq,hq]);replacements={};ports={}
    assert all(53544 not in v['bits'] for v in m['ports'].values())
    for n,c in cs.items():
        used=[p for p,bs in c['connections'].items() if c['port_directions'][p]=='input' and 53544 in bs]
        if not used:continue
        assert c['type']=='SLICE_LUTX';new=copy.deepcopy(c)
        for p in used:new['connections'][p]=[pred if b==53544 else b for b in new['connections'][p]]
        replacements[n]=new;ports[n]=used
    assert {n.split('$')[-1] for n in replacements}=={'217433','220770','232238'}
    return dict(bits=bits,regs=regs,added=added,nets=nets,replacements=replacements,ports=ports,nonzero=pred,groups=[regs[:6],regs[6:]])


def predicate_cone(m,bits):
    cells=abstract(m);drivers=drivers_of(cells);seen=set()
    for word in [0,65535,*[1<<i for i in range(16)]]:assert evaluate(53544,{b:(word>>i)&1 for i,b in enumerate(bits)},drivers,seen)==int(word!=0)
    while True:
        previous=set(seen)
        for n in previous:
            for p,bs in cells[n]['connections'].items():
                if cells[n]['port_directions'][p]=='input':
                    for b in bs:evaluate(b,{v:0 for v in bits},drivers,seen)
        if seen==previous:break
    return {n:cells[n] for n in sorted(seen)}


def state_miter(m,spec):
    cs=m['cells'];added=spec['added'];ds=[cs[n]['connections']['D'][0] for n in spec['regs']];ce0=cs[spec['regs'][0]]['connections']['CE'][0];ce1=cs[spec['regs'][6]]['connections']['CE'][0];clock=cs[spec['regs'][0]]['connections']['CK'][0];signals={**{b:f'd[{i}]' for i,b in enumerate(ds)},ce0:'ce[0]',ce1:'ce[1]',clock:'clk'};assert len(set(ds))==16 and not set(ds)&{ce0,ce1,clock}
    for c in added.values():
        output=c['connections']['Q'][0] if c['type']=='SLICE_FFX' else logical(c)[1]['O'];signals[output]=f'n{output}'
    names=[v for v in signals.values() if v.startswith('n')];lines=['module proof(input clk,input [1:0] ce,input [15:0] d,output same);','wire [15:0] q;','wire '+','.join(names)+';']
    for i in range(16):lines.append(f"FDRE #(.INIT(1'b0)) r{i}(.C(clk),.CE(ce[{0 if i<6 else 1}]),.R(1'b0),.D(d[{i}]),.Q(q[{i}]));")
    for i,c in enumerate(added.values()):
        if c['type']=='SLICE_FFX':
            con=c['connections'];assert not con['SR'] and c['parameters']=={'INIT':'0'};lines.append(f"FDRE #(.INIT(1'b0)) f{i}(.C({signals[con['CK'][0]]}),.CE({signals[con['CE'][0]]}),.R(1'b0),.D({signals[con['D'][0]]}),.Q({signals[con['Q'][0]]}));")
        else:
            w,p,t=logical(c);lines.append(f"LUT{w} #(.INIT({1<<w}'b{t:0{1<<w}b})) l{i}("+','.join(f'.{k}({signals[b]})' for k,b in p.items())+');')
    lines.append(f"assign same=({signals[spec['nonzero']]}==(|q)) && (n{added[PREFIX+'lo_q']['connections']['Q'][0]}==(|q[5:0])) && (n{added[PREFIX+'hi_q']['connections']['Q'][0]}==(|q[15:6]));")
    return '\n'.join(lines+['endmodule'])+'\n'


def apply_verified(patch,design):
    assert patch['passed'] and patch['added_latency_cycles']==0 and patch['added_redundant_registers']==2;prior=patch['count_flag_base'];base=apply_base(prior,design);spec=construct(base['modules']['top']);assert patch['count_flag_groups']==spec['groups'] and patch['count_flag_consumers']==spec['ports'];targets=set(spec['replacements'])
    for n,c in patch['original_cells'].items():assert design['modules']['top']['cells'][n]==c
    for field in ['replacements','added_cells','added_netnames']:
        for n,c in prior[field].items():
            if field=='replacements' and n in targets:continue
            assert patch[field][n]==c
    assert set(patch['replacements'])==set(prior['replacements'])|targets;assert set(patch['added_cells'])==set(prior['added_cells'])|set(spec['added']);assert set(patch['added_netnames'])==set(prior['added_netnames'])|set(spec['nets'])
    for n,c in spec['added'].items():assert patch['added_cells'][n]==c
    for n,c in spec['nets'].items():assert patch['added_netnames'][n]==c
    for n,c in spec['replacements'].items():assert patch['replacements'][n]==c
    v=Path(patch['count_flag_state_miter']);assert v.read_text()==state_miter(base['modules']['top'],spec)
    assert 'SUCCESS!' in Path(patch['count_flag_state_log']).read_text();assert 'SUCCESS!' in Path(patch['count_flag_predicate_log']).read_text()
    m=base['modules']['top'];m['cells'].update(copy.deepcopy(patch['replacements']));m['cells'].update(copy.deepcopy(patch['added_cells']));m['netnames'].update(copy.deepcopy(patch['added_netnames']));return base


def main():
    p=argparse.ArgumentParser();p.add_argument('--base-patch',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();out=a.out.resolve();assert not out.exists();bp=a.base_patch.resolve();prior=json.loads(bp.read_text());assert prior['passed']
    for n,h in prior['sha256'].items():assert digest(n)==h,n
    cp=Path(prior['checkpoint']);source=cp.parent/'pre-fixup.json';gold=json.loads(source.read_text());base=apply_base(prior,gold);m=base['modules']['top'];spec=construct(m);cone=predicate_cone(m,spec['bits']);patch=copy.deepcopy(prior);patch.pop('sha256');patch.update(kind='packed_dma_count_nonzero_flags',count_flag_base=prior,count_flag_groups=spec['groups'],count_flag_consumers=spec['ports'],added_redundant_registers=2);patch['added_cells'].update(spec['added']);patch['added_netnames'].update(spec['nets']);patch['replacements'].update(spec['replacements']);patch['original_cells'].update({n:gold['modules']['top']['cells'][n] for n in set(spec['regs'])|set(spec['replacements'])|set(cone)})
    reference=Path(json.loads(cp.read_text())['parent']).parent/'routed.json';placed=json.loads(reference.read_text())['modules']['top']['cells'];effective={n:patch['placements'].get(n,c['attributes']['NEXTPNR_BEL']) for n,c in placed.items()};occupied=set(effective.values())|set(patch['placements'].values());sites={b.split('/')[0] for b in occupied if b.startswith('SLICE_')};bad={effective[n].split('/')[0] for n,c in placed.items() if c['type'] in ['CARRY4','SELMUX2_1'] or c['attributes'].get('X_ORIG_TYPE')=='RAMD32'};ffsites={effective[n].split('/')[0] for n,c in placed.items() if c['type']=='SLICE_FFX'};free=[s+'/'+l+'6LUT' for s in sites-bad for l in 'ABCD' if s+'/'+l+'5LUT' not in occupied and s+'/'+l+'6LUT' not in occupied]
    def xy(b):return tuple(map(int,re.search(r'SLICE_X(\d+)Y(\d+)',b).groups()))
    for label,index in [('lo',0),('hi',6)]:
        x,y=xy(effective[spec['regs'][index]]);choices=[b for b in free if b.split('/')[0] not in ffsites and b.replace('6LUT','FF') not in occupied];bel=min(choices,key=lambda b:(abs(xy(b)[0]-x)+abs(xy(b)[1]-y),b));free.remove(bel);ffsites.add(bel.split('/')[0]);patch['placements'][PREFIX+label+'_d']=bel;patch['placements'][PREFIX+label+'_q']=bel.replace('6LUT','FF')
    for label in ['hi_d0','hi_d1','nonzero']:
        near=patch['placements'][PREFIX+'hi_d'];x,y=xy(near);bel=min(free,key=lambda b:(abs(xy(b)[0]-x)+abs(xy(b)[1]-y),b));free.remove(bel);patch['placements'][PREFIX+label]=bel
    out.mkdir();yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';pv=out/'predicate.v';pv.write_text(verilog(cone,spec['bits'],53544,'gold')+'\nmodule proof(input [15:0] x,output same);wire y;gold g(x,y);assign same=y==(|x);endmodule\n');sv=out/'state.v';sv.write_text(state_miter(m,spec));proof_files=[]
    for stem,v,commands in [('predicate',pv,'sat -verify -prove same 1'),('state',sv,'sat -seq 4 -set-init-zero -prove same 1 -verify\nsat -seq 3 -set-init-zero -tempinduct -maxsteps 8 -prove same 1 -verify')]:
        ys=out/(stem+'.ys');ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\n{commands}\n');log=out/(stem+'.log')
        with log.open('w') as f:subprocess.run([str(yosys),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
        assert 'SUCCESS!' in log.read_text();proof_files.extend([v,ys,log])
    patch.update(count_flag_state_miter=str(sv),count_flag_state_log=str(out/'state.log'),count_flag_predicate_log=str(out/'predicate.log'));apply_verified(patch,gold);patch['sha256']=dict(prior['sha256']);patch['sha256'].update({str(q.resolve()):digest(q) for q in [bp,source,reference,Path(__file__),Path(__file__).with_name('synapse32_packed_wdata_capture_replicas.py'),Path(__file__).with_name('synapse32_packed_branch_carry_cuts_v2.py'),Path(__file__).with_name('synapse32_factor_branch_predicate.py'),yosys,lib,*proof_files]});(out/'patch.json').write_text(json.dumps(patch,separators=(',',':'))+'\n');print(json.dumps(dict(passed=True,predicate_primitive_sat=True,redundant_flag_primitive_induction=True,added_registers=2,added_luts=5,added_latency_cycles=0)))
if __name__=='__main__':main()
