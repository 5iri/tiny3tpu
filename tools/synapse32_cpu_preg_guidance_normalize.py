"""Require native RAM/MREG guidance to reproduce the independent DS182 models."""
from synapse32_apply_bram_timing import apply_model as bram_model, number
from synapse32_cpu_preg_dsp_model import apply_model as dsp_model, REGS


def normalize(rows,cells,bram_limits,dsp_limits):
    rams={n for n,c in cells.items() if c['type']=='RAMB36E1_RAMB36E1'}
    dsps={n for n,c in cells.items() if c['type']=='DSP48E1_DSP48E1' and any(number(c['parameters'],r) for r in REGS)}
    modeled=rams|dsps
    assert len(rams)==16 and len(dsps)==4
    assert not any(r[0]=='CELLARC' and r[1] in modeled for r in rows), 'Hybrid bypass arcs unsupported'
    legacy=[]
    for r in rows:
        if r[0]=='CLOCK' and r[1] in modeled:continue
        if r[0]=='PORT' and r[1] in modeled:
            r=list(r);r[5:7]=['8','0']
        legacy.append(r)
    expected,ram_decisions=bram_model(legacy,cells,bram_limits)
    expected,dsp_coverage=dsp_model(expected,cells,dsp_limits,pcout_ns=0)
    assert not dsp_coverage['unknown_delays']
    assert all(p['mode']==5 and p['kind'] in ('cpu_mreg','cpu_preg') for p in dsp_coverage['profiles'].values())
    # The offline engine supports clock origins on a combinational output.
    # Native nextpnr requires REGISTER_OUTPUT here. Pure multiply has no bypass
    # input arcs, so these classifications describe the same timing graph.
    adjusted=[]
    for r in expected:
        if r[0]=='PORT' and r[1] in dsps and r[5]=='5':
            assert not any(v[0]=='CELLARC' and v[1]==r[1] and v[3]==r[3] for v in expected)
            r=list(r);r[5]='3'
        adjusted.append(r)
    def key(r):
        r=list(r)
        if r[0]=='CLOCK':r[6:9]=[round(float(v)*1000) for v in r[6:9]]
        if r[0]=='CELLARC':r[4]=round(float(r[4])*1000)
        if r[0]=='NETARC':r[6]=round(float(r[6])*1000)
        return tuple(r)
    actual={key(r) for r in rows};want={key(r) for r in adjusted}
    assert actual==want, ('Native primitive model mismatch',list(actual-want)[:8],list(want-actual)[:8])
    return legacy,dict(passed=True,ram_count=len(rams),registered_dsp_count=len(dsps),
        native_matches_independent_models=True,
        new_clock_rows=sum(r[0]=='CLOCK' and r[1] in modeled for r in rows),
        scope='Only added RAM/MREG port classifications and clock checks are normalized for the established expanded analyzer. All net connections and routed delays remain identical. Actual native graph is retained. No hybrid DSP or unknown cascade is accepted.',
        full_soc_timing_accepted=False)
