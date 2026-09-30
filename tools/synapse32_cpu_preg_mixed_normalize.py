"""Require native mixed LUTRAM timing to match independent expanded checks."""
from synapse32_cpu_preg_guidance_normalize import normalize as normalize_ram_dsp
from synapse32_lutram_timing_model import apply_model as lutram_model
from synapse32_registered_dsp_model import GraphIndex


def row_key(row):
    row=list(row)
    if row[0]=='CLOCK': row[6:9]=[round(float(v)*1000) for v in row[6:9]]
    if row[0]=='CELLARC': row[4]=round(float(row[4])*1000)
    if row[0]=='NETARC': row[6]=round(float(row[6])*1000)
    return tuple(row)


def normalize_lutram(rows,cells,limits):
    ix=GraphIndex(rows,cells)
    names={n for n,c in cells.items() if c['type']=='SLICE_LUTX' and c['attributes'].get('X_LUT_AS_DRAM','').strip()=='1'}
    observable={n for n in names if any(v[4]=='output' and ix.fanout[n,p] for p,v in ix.by_cell[n].items())}
    legacy=[]
    for r in rows:
        if r[0]=='CLOCK' and r[1] in observable:continue
        if r[0]=='PORT' and r[1] in observable:
            orig=cells[r[1]]['attributes'].get('X_ORIG_PORT_'+r[3])
            if orig=='O': cls=5
            elif orig and orig.startswith('RADR'): cls=4
            elif orig in ('CLK','I','WE') or (orig and orig.startswith('WADR')): cls=8
            else: cls=None
            if cls is not None:
                r=list(r);r[5:7]=[str(cls),'0']
        legacy.append(r)
    expected,coverage=lutram_model(legacy,cells,limits)
    actual={row_key(r) for r in rows};want={row_key(r) for r in expected}
    assert actual==want,('Native mixed LUTRAM mismatch',list(actual-want)[:8],list(want-actual)[:8])
    # Every read-address arc and routed connection must remain byte-identical.
    assert [r for r in legacy if r[0] in ('CELLARC','NETARC')]==[r for r in rows if r[0] in ('CELLARC','NETARC')]
    return legacy,dict(passed=True,**coverage['counts'],native_matches_independent_model=True,
                       new_clock_rows=sum(r[0]=='CLOCK' and r[1] in observable for r in rows),
                       asynchronous_read_arcs_retained=True,full_soc_timing_accepted=False)


def normalize(rows,cells,bram_limits,dsp_limits,lutram_limits):
    intermediate,lutram=normalize_lutram(rows,cells,lutram_limits)
    legacy,primitives=normalize_ram_dsp(intermediate,cells,bram_limits,dsp_limits)
    primitives['lutram']=lutram
    primitives['scope']+=' LUTRAM write-clock origins and setup/hold checks match the independent model; asynchronous read arcs and all routed net delays are retained.'
    return legacy,primitives
