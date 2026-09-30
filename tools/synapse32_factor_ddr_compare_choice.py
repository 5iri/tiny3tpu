#!/usr/bin/env python3
"""Precompute DDR address comparisons before the late offset carry."""
import argparse, copy, json, subprocess
from pathlib import Path
from synapse32_factor_branch_predicate import digest, drivers_of, lut, verilog
from synapse32_capture_zqcs_zero import cone_for

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--parent',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();parent=a.parent.resolve();out=a.out.resolve();assert not out.exists()
    source=parent/'board/soc.json';gold=json.loads(source.read_text())
    m=gold['modules']['kc705_synapse32_top'];cells=m['cells'];drivers=drivers_of(cells)
    root=342;slow=554
    boundary={b for c in cells.values() if c['type'].startswith('FD') for b in c['connections'].get('Q',[])}
    boundary.update(m['netnames']['memory.main_write_offset_low']['bits'][6:14])
    cone=cone_for([root],cells,drivers,boundary)
    assert cone and len(cone)<150
    target,old,port,index=drivers[root];assert port=='O' and old['type']=='MUXF7'
    outputs={b for c in cone.values() for port,bs in c['connections'].items() if c['port_directions'][port]=='output' for b in bs}
    leaves=sorted({b for c in cone.values() for port,bs in c['connections'].items() if c['port_directions'][port]=='input' for b in bs}-outputs-{'0','1'})
    assert slow in leaves and all(isinstance(b,int) for b in leaves)
    fast=[b for b in leaves if b!=slow]
    out.mkdir();proof=out/'predicate-proof';proof.mkdir()
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys')
    lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v'
    text=verilog(cone,leaves,root,'original')+'\n'+f'module cofactors(input [{len(fast)-1}:0] x,output [1:0] y);\n'
    for value in [0,1]:
        expr=["1'b"+str(value) if b==slow else f'x[{fast.index(b)}]' for b in reversed(leaves)]
        text+=f'original c{value}({{{",".join(expr)}}},y[{value}]);\n'
    text+='endmodule\n';(proof/'cofactors.v').write_text(text)
    ys=proof/'synth.ys';ys.write_text(f'read_verilog {lib} {proof/"cofactors.v"}\nsynth -top cofactors -flatten -noabc\nabc -lut 6\nclean\ncheck -assert\nwrite_json {proof/"cofactors.json"}\n')
    with (proof/'synth.log').open('w') as f:subprocess.run([str(yosys),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
    cm=json.loads((proof/'cofactors.json').read_text())['modules']['cofactors']
    assert all(c['type'] in ['$lut','$scopeinfo'] for c in cm['cells'].values())
    assert all(not c['connections'] for c in cm['cells'].values() if c['type']=='$scopeinfo')
    cm['cells']={n:c for n,c in cm['cells'].items() if c['type']=='$lut'}
    oldbits={b for c in cells.values() for bs in c['connections'].values() for b in bs if isinstance(b,int)}|{b for v in m['netnames'].values() for b in v['bits'] if isinstance(b,int)}|{b for v in m['ports'].values() for b in v['bits'] if isinstance(b,int)}
    fresh=max(oldbits)+1;bitmap=dict(zip(cm['ports']['x']['bits'],fast));assert len(bitmap)==len(fast)
    def bit(b):
        nonlocal fresh
        if isinstance(b,str):assert b in ['0','1'];return b
        if b not in bitmap:bitmap[b]=fresh;fresh+=1
        return bitmap[b]
    added={}
    for i,(name,c) in enumerate(sorted(cm['cells'].items())):
        inputs=list(map(bit,c['connections']['A']));output=bit(c['connections']['Y'][0]);assert 1<=len(inputs)<=6
        added[f'$tiny3tpu$ddr_compare_choice_{i}']=lut(inputs,output,int(c['parameters']['LUT'],2))
    choices=list(map(bit,cm['ports']['y']['bits']));assert len(choices)==2
    replacement=lut(choices+[slow],root,0xca)
    assert all(slow not in bs for c in added.values() for bs in c['connections'].values())
    newcone={**added,target:replacement}
    v=proof/'miter.v';v.write_text(verilog(cone,leaves,root,'gold')+'\n'+verilog(newcone,leaves,root,'candidate')+f'\nmodule miter(input [{len(leaves)-1}:0] x,output equal);wire a,b;gold g(x,a);candidate c(x,b);assign equal=a==b;endmodule\n')
    ys=proof/'prove.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top miter\nflatten\nopt\ncheck -assert\nsat -verify -prove equal 1 -show-inputs\n')
    with (proof/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (proof/'prove.log').read_text()
    actual=copy.deepcopy(gold);ac=actual['modules']['kc705_synapse32_top']['cells'];assert not set(added)&set(ac)
    ac.update(added);ac[target]=replacement
    restored=copy.deepcopy(actual);rc=restored['modules']['kc705_synapse32_top']['cells'];rc[target]=old
    for n in added:del rc[n]
    assert restored==gold
    record=dict(passed=True,claim='Actual primitive SAT for all arbitrary cut inputs. Both alternatives use only fast inputs; the late offset carry crosses one final LUT3. No state, memory ordering or latency changes.',cone=cone,leaves=leaves,slow=slow,added=added,replacement=replacement,root=root,target=target,added_latency_cycles=0,sha256={str(q):digest(q) for q in [source,yosys,lib,Path(__file__).resolve(),Path(__file__).with_name('synapse32_factor_branch_predicate.py').resolve()]+list(proof.iterdir())})
    (proof/'results.json').write_text(json.dumps(record,indent=2)+'\n')
    board=out/'board';board.mkdir();(board/'soc.json').write_text(json.dumps(actual,separators=(',',':'))+'\n')
    for n in ['kc705.xdc','firmware.hex','synth.ys']:(board/n).write_bytes((parent/'board'/n).read_bytes())
    mapping=dict(passed=True,kind='factored_ddr_compare_choice',parent=str(parent),source=str(source),proof=str(proof/'results.json'),target=target,original_cell=old,candidate_cell=replacement,added=added,added_latency_cycles=0,all_other_netlist_content_exact=True,new_rtl_synthesis_run=False,new_workload_simulation_run=False,full_soc_timing_accepted=False,checked_manifests=[dict(path=str(q),sha256=digest(q)) for q in [parent/'iteration-integrity.json',parent/'mapping.json',proof/'results.json']],sha256={str(q):digest(q) for q in [source,Path(__file__).resolve()]},output_sha256={str(q):digest(q) for q in board.iterdir()})
    (out/'mapping.json').write_text(json.dumps(mapping,indent=2)+'\n')
    print(json.dumps(dict(passed=True,cut_inputs=len(leaves),added_luts=len(added),late_carry_lut_depth=1,added_latency_cycles=0)))

if __name__=='__main__':main()
