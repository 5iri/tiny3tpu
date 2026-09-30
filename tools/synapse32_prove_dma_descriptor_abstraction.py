#!/usr/bin/env python3
"""Prove an actual DMA control endpoint depends on address/length only through descriptor validity."""
import argparse,json,re,subprocess
from pathlib import Path
from synapse32_capture_zqcs_zero import cone_for
from synapse32_factor_branch_predicate import digest,drivers_of,verilog

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();parent=a.parent.resolve();out=a.out.resolve();assert not out.exists()
    source=parent/'board/soc.json';design=json.loads(source.read_text());m=design['modules']['kc705_synapse32_top'];cells=m['cells']
    ff=cells['$auto$ff.cc:337:slice$77288'];assert ff['type']=='FDRE' and ff['connections']['CE']==['1'];root=ff['connections']['D'][0];assert root==32742
    comb={'INV','MUXF7','MUXF8','CARRY4'}|{f'LUT{i}' for i in range(1,7)}
    boundary={b for c in cells.values() if c['type'] not in comb for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs}
    boundary.update(b for v in m['ports'].values() if v['direction']=='input' for b in v['bits'])
    cone=cone_for([root],cells,drivers_of(cells),boundary)
    outputs={b for c in cone.values() for p,bs in c['connections'].items() if c['port_directions'][p]=='output' for b in bs}
    leaves=sorted({b for c in cone.values() for p,bs in c['connections'].items() if c['port_directions'][p]=='input' for b in bs}-outputs-{'0','1'})
    words={n:m['netnames']['soc.dma.'+n]['bits'] for n in ['tx_address','rx_address','byte_count']};data_bits=set(sum(words.values(),[]));assert len(data_bits)==96 and data_bits<=set(leaves)
    rtl=Path(__file__).resolve().parents[1]/'multi-core/synapse32_axi_dma.sv';match=re.search(r'    wire \[32:0\] tx_end=.*?    wire write_ok=',rtl.read_text(),re.S);assert match
    predicate=match.group(0).removesuffix('    wire write_ok=')
    samples=[dict(tx_address=0,rx_address=0,byte_count=0),dict(tx_address=0x40000000,rx_address=0x40000100,byte_count=8)]
    text=verilog(cone,leaves,root,'original')+f'\nmodule proof(input [{len(leaves)-1}:0] x,output same);\nwire actual,c0,c1;original g(x,actual);\n'
    for n,bs in words.items():text+=f'wire [31:0] {n}={{{",".join(f"x[{leaves.index(b)}]" for b in reversed(bs))}}};\n'
    text+=predicate
    for i,sample in enumerate(samples):
        values={b:(sample[n]>>j)&1 for n,bs in words.items() for j,b in enumerate(bs)}
        pins=["1'b"+str(values[b]) if b in values else f'x[{leaves.index(b)}]' for b in reversed(leaves)]
        text+=f'original c_{i}({{{",".join(pins)}}},c{i});\n'
    text+='assign same=actual==(descriptor_valid ? c1:c0);\nendmodule\n'
    out.mkdir();v=out/'proof.v';v.write_text(text);yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');lib=yosys.parents[1]/'share/yosys/xilinx/cells_sim.v';ys=out/'proof.ys';ys.write_text(f'read_verilog {lib} {v}\nprep -top proof\nflatten\nopt\ncheck -assert\nsat -verify -prove same 1 -show-inputs\n')
    with (out/'proof.log').open('w') as f:subprocess.run([str(yosys),'-s',str(ys)],stdout=f,stderr=subprocess.STDOUT,check=True)
    assert 'SUCCESS!' in (out/'proof.log').read_text()
    record=dict(passed=True,parent=str(parent),root=root,endpoint='$auto$ff.cc:337:slice$77288/D',cone=cone,leaves=leaves,descriptor_words=words,samples=samples,claim='Actual mapped write-pending D cone depends on all 96 address/length bits only through the original descriptor-valid predicate, for arbitrary values of every other cut input. Primitive SAT proves replacement with the two constant-descriptor control cofactors. No design change or timing improvement is claimed by this proof alone.',full_soc_timing_accepted=False,sha256={str(q):digest(q) for q in [source,rtl,yosys,lib,v,ys,out/'proof.log',Path(__file__).resolve(),Path(__file__).with_name('synapse32_capture_zqcs_zero.py').resolve(),Path(__file__).with_name('synapse32_factor_branch_predicate.py').resolve()]})
    (out/'results.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(dict(passed=True,cone_cells=len(cone),cut_inputs=len(leaves),descriptor_bits=96)))

if __name__=='__main__':main()
