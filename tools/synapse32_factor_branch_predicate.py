#!/usr/bin/env python3
"""Replace an actual mapped branch predicate with parallel exact decodes."""
import argparse, copy, hashlib, json, subprocess
from pathlib import Path

def digest(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def evaluate(bit, values, drivers, seen):
    if bit in values: return values[bit]
    if isinstance(bit, str): return int(bit)
    name, cell, port, index = drivers[bit]; seen.add(name)
    con = cell['connections']; f = lambda b: evaluate(b, values, drivers, seen)
    kind = cell['type']
    if kind == 'INV': value = 1-f(con['I'][0])
    elif kind.startswith('LUT'):
        address = sum(f(con[f'I{i}'][0]) << i for i in range(int(kind[3:])))
        value = (int(cell['parameters']['INIT'], 2) >> address) & 1
    elif kind == 'CARRY4':
        carry = f(con['CI'][0]) | f(con['CYINIT'][0])
        for i in range(index+1):
            select = f(con['S'][i]); output = select ^ carry
            carry = carry if select else f(con['DI'][i])
        value = carry if port == 'CO' else output
    else: raise ValueError((bit, name, kind))
    values[bit] = value
    return value

def drivers_of(cells):
    return {b:(n,c,p,i) for n,c in cells.items() for p,bs in c['connections'].items()
            if c['port_directions'][p]=='output' for i,b in enumerate(bs) if isinstance(b,int)}

def lut(inputs, output, mask):
    width=len(inputs)
    return dict(hide_name=0,type=f'LUT{width}',parameters={'INIT':format(mask,f'0{1<<width}b')},
        attributes={'keep':'1'},port_directions={**{f'I{i}':'input' for i in range(width)},'O':'output'},
        connections={**{f'I{i}':[b] for i,b in enumerate(inputs)},'O':[output]})

def verilog(cells, leaves, root, name):
    bits=sorted({b for c in cells.values() for bs in c['connections'].values() for b in bs if isinstance(b,int)})
    def wire(b): return f'n{b}' if isinstance(b,int) else "1'b"+b
    lines=[f'module {name}(input [{len(leaves)-1}:0] x, output y);', 'wire '+','.join(map(wire,bits))+';']
    lines += [f'assign n{b}=x[{i}];' for i,b in enumerate(leaves)]
    lines += [f'assign y=n{root};']
    for i,c in enumerate(cells.values()):
        params=','.join(f'.{k}({len(v)}\'b{v})' for k,v in c['parameters'].items())
        ports=','.join(f'.{p}({{{",".join(wire(b) for b in reversed(bs))}}})' for p,bs in c['connections'].items())
        lines.append(f'{c["type"]} '+(f'#({params}) ' if params else '')+f'c{i}({ports});')
    return '\n'.join(lines+['endmodule'])

def main():
    p=argparse.ArgumentParser();p.add_argument('--parent',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    parent=a.parent.resolve();out=a.out.resolve();assert not out.exists()
    source=parent/'board/soc.json';gold=json.loads(source.read_text());m=gold['modules']['kc705_synapse32_top'];cells=m['cells'];drivers=drivers_of(cells)
    ids=m['netnames']['soc.cpu.ex_unit_inst0.alu_inst.instr_id']['bits'];assert len(ids)==7
    conditions=[m['netnames']['soc.cpu.ex_unit_inst0.'+n]['bits'][0] for n in ['branch_equal','branch_less_signed','branch_less_unsigned']]
    root=8237;target,old,port,index=drivers[root];assert old['type']=='LUT2' and port=='O'
    leaves=ids+conditions;seen=set();truth=[]
    for word in range(1<<len(leaves)):
        values={b:(word>>i)&1 for i,b in enumerate(leaves)};v=evaluate(root,values,drivers,seen)
        instruction=word&127;condition=(word>>7)
        expected=int(instruction in range(28,34) and (((condition>>((instruction-28)//2))&1) ^ (instruction&1)))
        assert v==expected;truth.append(v)
    cone={n:cells[n] for n in sorted(seen)}
    fresh=max(b for c in cells.values() for bs in c['connections'].values() for b in bs if isinstance(b,int))+1
    added={};terms=[]
    for i,pair in enumerate([14,15,16]):
        group=fresh+2*i;term=group+1;terms.append(term)
        added[f'$tiny3tpu$branch_pair_{i}']=lut(ids[1:],group,1<<pair)
        mask=sum((g & (c^inv)) << (g|(c<<1)|(inv<<2)) for g in [0,1] for c in [0,1] for inv in [0,1])
        added[f'$tiny3tpu$branch_condition_{i}']=lut([group,conditions[i],ids[0]],term,mask)
    replacement=lut(terms,root,0xfe);new_cone={**added,target:replacement};new_drivers=drivers_of(new_cone)
    for word,v in enumerate(truth):assert evaluate(root,{b:(word>>i)&1 for i,b in enumerate(leaves)},new_drivers,set())==v
    actual=copy.deepcopy(gold);ac=actual['modules']['kc705_synapse32_top']['cells'];assert not(set(added)&set(ac));ac.update(added);ac[target]=replacement
    restored=copy.deepcopy(actual);rc=restored['modules']['kc705_synapse32_top']['cells'];rc[target]=old
    for n in added:del rc[n]
    assert restored==gold
    out.mkdir();proof=out/'predicate-proof';proof.mkdir()
    vpath=proof/'miter.v';vpath.write_text(verilog(cone,leaves,root,'gold')+'\n'+verilog(new_cone,leaves,root,'candidate')+'\nmodule miter(input [9:0] x,output equal);wire a,b;gold g(x,a);candidate c(x,b);assign equal=a==b;endmodule\n')
    yosys=Path('/Users/siriboi/.apio/packages/oss-cad-suite/bin/yosys');library=Path('/Users/siriboi/.apio/packages/oss-cad-suite/share/yosys/xilinx/cells_sim.v')
    script=proof/'prove.ys';script.write_text(f'read_verilog {library}\nread_verilog {vpath}\nprep -top miter\nflatten\nopt\nsat -verify -prove equal 1 -show-inputs\n')
    log=proof/'prove.log'
    with log.open('w') as f:r=subprocess.run([str(yosys),'-s',str(script)],stdout=f,stderr=subprocess.STDOUT)
    assert r.returncode==0 and 'SUCCESS!' in log.read_text(),log
    record=dict(passed=True,claim='All 1024 actual instruction/branch-condition combinations, plus independent Yosys SAT over actual Xilinx primitive models. Exact direct branch decode, no state or latency change.',cone=cone,leaves=leaves,truth_table=truth,added=added,replacement=replacement,root=root,target=target,added_latency_cycles=0,sha256={str(q):digest(q) for q in [source,Path(__file__).resolve(),vpath,script,log,yosys,library]})
    (proof/'results.json').write_text(json.dumps(record,indent=2)+'\n')
    board=out/'board';board.mkdir();(board/'soc.json').write_text(json.dumps(actual,separators=(',',':'))+'\n')
    for n in ['kc705.xdc','firmware.hex','synth.ys']:(board/n).write_bytes((parent/'board'/n).read_bytes())
    mapping=dict(passed=True,kind='factored_branch_predicate',parent=str(parent),source=str(source),proof=str(proof/'results.json'),target=target,original_cell=old,candidate_cell=replacement,added=added,added_latency_cycles=0,all_other_netlist_content_exact=True,new_rtl_synthesis_run=False,new_workload_simulation_run=False,full_soc_timing_accepted=False,checked_manifests=[dict(path=str(q),sha256=digest(q)) for q in [parent/'iteration-integrity.json',parent/'mapping.json',proof/'results.json']],sha256={str(q):digest(q) for q in [source,Path(__file__).resolve()]},output_sha256={str(q):digest(q) for q in board.iterdir()})
    (out/'mapping.json').write_text(json.dumps(mapping,indent=2)+'\n');print('PASS 1024 cases and primitive SAT; direct branch predicates, no new state or latency')

if __name__=='__main__':main()
