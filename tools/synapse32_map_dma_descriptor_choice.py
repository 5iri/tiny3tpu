#!/usr/bin/env python3
"""Map narrow DMA descriptor validation and independent write-pending control choices."""
import argparse,copy,importlib.util,json,subprocess
from pathlib import Path
from synapse32_factor_branch_predicate import digest,drivers_of,lut,verilog

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ['parent','abstraction','out']:p.add_argument('--'+k,type=Path,required=True)
    a=p.parse_args();parent=a.parent.resolve();out=a.out.resolve();assert not out.exists()
    ap=a.abstraction.resolve()/'results.json';ab=json.loads(ap.read_text());assert ab['passed'] and ab['parent']==str(parent)
    for n,h in ab['sha256'].items():assert digest(n)==h,n
    source=parent/'board/soc.json';gold=json.loads(source.read_text());m=gold['modules']['kc705_synapse32_top'];cells=m['cells']
    root=ab['root'];leaves=ab['leaves'];cone=ab['cone'];words=ab['descriptor_words'];assert all(cells[n]==c for n,c in cone.items())
    target,old,port,index=drivers_of(cells)[root];assert port=='O' and old['type'].startswith('LUT')
    spec_path=Path(__file__).resolve().parents[1]/'hardware/synapse32/experiments/boot-ddr-first/descriptor_ranges.py'
    spec=importlib.util.spec_from_file_location('descriptor_ranges',spec_path);descriptor=importlib.util.module_from_spec(spec);spec.loader.exec_module(descriptor)
    predicate=descriptor.NEW.removesuffix('    wire write_ok=')
    text=verilog(cone,leaves,root,'original')+f'\nmodule mapped(input [{len(leaves)-1}:0] x,output [2:0] y);\n'
    for n,bs in words.items():text+=f'wire [31:0] {n}={{{",".join(f"x[{leaves.index(b)}]" for b in reversed(bs))}}};\n'
    text+=predicate+'assign y[0]=descriptor_valid;\n'
    for i,sample in enumerate(ab['samples']):
        values={b:(sample[n]>>j)&1 for n,bs in words.items() for j,b in enumerate(bs)}
        pins=["1'b"+str(values[b]) if b in values else f'x[{leaves.index(b)}]' for b in reversed(leaves)]
        text+=f'original c{i}({{{",".join(pins)}}},y[{i+1}]);\n'
    text+='endmodule\n'
    out.mkdir();proof=out/'predicate-proof';proof.mkdir();(proof/'mapped.v').write_text(text)
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v'
    ys=proof/'synth.ys';ys.write_text(f'read_verilog {lib} {proof/"mapped.v"}\nhierarchy -top mapped\nproc\nflatten\nopt\nsynth_xilinx -family xc7 -top mapped -noiopad -noclkbuf -nodsp -nosrl\nclean\ncheck -assert\nwrite_json {proof/"mapped.json"}\n')
    with (proof/'synth.log').open('w') as f:subprocess.run([str(yosys),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
    mapped=json.loads((proof/'mapped.json').read_text())['modules']['mapped'];allowed={'INV','CARRY4','MUXF7','MUXF8'}|{f'LUT{i}' for i in range(1,7)}
    assert all(c['type'] in allowed|{'$scopeinfo'} for c in mapped['cells'].values())
    assert all(not c['connections'] for c in mapped['cells'].values() if c['type']=='$scopeinfo')
    oldbits={b for c in cells.values() for bs in c['connections'].values() for b in bs if isinstance(b,int)}|{b for v in m['netnames'].values() for b in v['bits'] if isinstance(b,int)}|{b for v in m['ports'].values() for b in v['bits'] if isinstance(b,int)}
    fresh=max(oldbits)+1;bitmap=dict(zip(mapped['ports']['x']['bits'],leaves));assert len(bitmap)==len(leaves)
    def bit(b):
        nonlocal fresh
        if isinstance(b,str):assert b in ['0','1'];return b
        if b not in bitmap:bitmap[b]=fresh;fresh+=1
        return bitmap[b]
    added={}
    for i,(n,c) in enumerate(sorted(mapped['cells'].items())):
        if c['type']=='$scopeinfo':continue
        new=copy.deepcopy(c);new['connections']={p:list(map(bit,bs)) for p,bs in c['connections'].items()};new['attributes']={'keep':'1'}
        added[f'$tiny3tpu$descriptor_choice_{i}']=new
    valid,c0,c1=map(bit,mapped['ports']['y']['bits']);replacement=lut([c0,c1,valid],root,0xca);newcone={**added,target:replacement}
    v=proof/'miter.v';v.write_text(verilog(cone,leaves,root,'gold')+'\n'+verilog(newcone,leaves,root,'candidate')+f'\nmodule proof(input [{len(leaves)-1}:0] x,output same);wire a,b;gold g(x,a);candidate c(x,b);assign same=a==b;endmodule\n')
    ys=proof/'prove.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1 -show-inputs\n')
    with (proof/'prove.log').open('w') as f:subprocess.run([str(yosys),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (proof/'prove.log').read_text()
    actual=copy.deepcopy(gold);ac=actual['modules']['kc705_synapse32_top']['cells'];assert not set(added)&set(ac);ac.update(added);ac[target]=replacement
    restored=copy.deepcopy(actual);rc=restored['modules']['kc705_synapse32_top']['cells'];rc[target]=old
    for n in added:del rc[n]
    assert restored==gold
    record=dict(passed=True,claim='Actual original mapped write-pending D equals the translated narrow descriptor predicate plus independent control cofactors, for all 182 arbitrary cut inputs. Only combinational logic changes; all state, memory ordering and execution cycles are preserved.',abstraction=str(ap),root=root,target=target,cone=cone,leaves=leaves,added=added,replacement=replacement,added_latency_cycles=0,sha256={str(q):digest(q) for q in [source,ap,spec_path,yosys,lib,Path(__file__).resolve(),Path(__file__).with_name('synapse32_factor_branch_predicate.py').resolve()]+list(proof.iterdir())})
    (proof/'results.json').write_text(json.dumps(record,indent=2)+'\n');board=out/'board';board.mkdir();(board/'soc.json').write_text(json.dumps(actual,separators=(',',':'))+'\n')
    for n in ['kc705.xdc','firmware.hex','synth.ys']:(board/n).write_bytes((parent/'board'/n).read_bytes())
    mapping=dict(passed=True,kind='factored_dma_descriptor_choice',parent=str(parent),source=str(source),proof=str(proof/'results.json'),target=target,original_cell=old,candidate_cell=replacement,added=added,added_latency_cycles=0,all_other_netlist_content_exact=True,new_rtl_synthesis_run=False,new_workload_simulation_run=False,full_soc_timing_accepted=False,checked_manifests=[dict(path=str(q),sha256=digest(q)) for q in [parent/'iteration-integrity.json',parent/'mapping.json',ap,proof/'results.json']],sha256={str(q):digest(q) for q in [source,Path(__file__).resolve()]},output_sha256={str(q):digest(q) for q in board.iterdir()})
    (out/'mapping.json').write_text(json.dumps(mapping,indent=2)+'\n');print(json.dumps(dict(passed=True,cut_inputs=len(leaves),added_cells=len(added),added_latency_cycles=0)))

if __name__=='__main__':main()
