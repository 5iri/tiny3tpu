"""Find missing carry-cell timing dependencies after local constant propagation."""
from synapse32_registered_dsp_model import GraphIndex
from synapse32_apply_bram_timing import number


def carry_support(values, initial):
    """Exact Boolean support of four carry mux/XOR stages, for fixed input pins.

    Values map S0..S3/DI0..DI3 and the selected initial pin to 0, 1 or None.
    `initial` is a constant bit or the selected CIN/CYINIT pin name. Dynamic
    ports remain independent; no global reachability or timing exception used.
    """
    keys=['S'+str(i) for i in range(4)]+['DI'+str(i) for i in range(4)]
    if isinstance(initial,str):keys.append(initial)
    variables=[k for k in keys if values.get(k) is None]
    size=1<<len(variables);mask=(1<<size)-1
    tables={}
    for k in keys:
        v=values.get(k)
        tables[k]=(mask if v else 0) if v is not None else sum(1<<r for r in range(size) if (r>>variables.index(k))&1)
    carry=tables[initial] if isinstance(initial,str) else mask if initial else 0
    outputs={}
    for i in range(4):
        s=tables['S'+str(i)];d=tables['DI'+str(i)]
        outputs['O'+str(i)]=s^carry
        carry=(s&carry)|((mask^s)&d);outputs['CO'+str(i)]=carry
    support={}
    for out,truth in outputs.items():
        deps=set()
        for i,k in enumerate(variables):
            lower=mask^tables[k]
            if (truth^(truth>>(1<<i)))&lower:deps.add(k)
        support[out]=deps
    return support


def audit(lines,cells):
    ix=GraphIndex(lines,cells);arcs={(v[1],v[2],v[3]) for v in lines if v[0]=='CELLARC'}
    missing=[];affected=set();checked=0
    for name,c in cells.items():
        if c['type']!='CARRY4':continue
        params=c.get('parameters',{});pins=ix.by_cell[name]
        if 'PRECYINIT_CONST' in params:initial=number(params,'PRECYINIT_CONST');assert initial in (0,1)
        elif 'CIN' in pins:initial='CIN'
        elif 'CYINIT' in pins:initial='CYINIT'
        else:initial=0
        values={pin:ix.constant(name,pin) for pin in pins}
        support=carry_support(values,initial)
        for output,deps in support.items():
            if not ix.fanout[name,output]:continue
            for pin in sorted(deps):
                if (name,pin) not in ix.incoming:continue
                checked+=1
                if (name,pin,output) not in arcs:
                    missing.append(dict(cell=name,input=pin,output=output));affected.add(name)
    return dict(scope='Carry mux/XOR Boolean dependencies with local constant propagation and packed PRECYINIT selection. Dynamic ports remain independent; no reachability assumptions or timing exceptions.',
                required_carry_arcs=checked,missing_carry_arc_count=len(missing),carry_cells_with_missing_arcs=len(affected),missing_carry_arcs=missing,
                carry_arcs_complete=not missing)
