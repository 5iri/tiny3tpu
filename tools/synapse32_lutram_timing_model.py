"""DS182 setup and mixed asynchronous-read/clocked-write model for packed RAMD32."""
import re
from synapse32_apply_bram_timing import number
from synapse32_registered_dsp_model import GraphIndex


def limits_from_text(text):
    section=text[text.index('Table 32: CLB Distributed RAM Switching Characteristics'):text.index('Table 33:')]
    result={}
    for key,marker,expected in [('data','TDS_LRAM/',.69),('write_address','TAS_LRAM/',.63),('write_enable','TWS_LRAM/',.46)]:
        row=section[section.index(marker):]
        if key=='write_address':row=row[:row.index('TWS_LRAM/')]
        else:row=row.split('ns, Min',1)[0]
        pairs=[(float(s),float(h)) for s,h in re.findall(r'(\d+\.\d+)/(\d+\.\d+)',row)]
        assert len(pairs)==(12 if key=='write_address' else 6),(key,pairs)
        result[key]=dict(setup_ns=max(p[0] for p in pairs),hold_ns=max(p[1] for p in pairs),all_grades=pairs)
        assert result[key]['setup_ns']==expected
    row=next(l for l in section.splitlines() if l.startswith('TSHCKO_1 '))
    values=[float(v) for v in re.findall(r'\d+\.\d+',row)]
    assert len(values)==6 and max(values)==1.44
    result['clock_to_read']=dict(max_ns=1.44,all_grades=values,note='Conservative AMUX/BMUX output bound; downstream routing/cell arcs retained.')
    return result


def apply_model(lines,cells,limits):
    ix=GraphIndex(lines,cells);changes={};extra=[];decisions=[];counts=dict(physical_cells=0,observable_cells=0)
    arc_inputs={(v[1],v[2]) for v in lines if v[0]=='CELLARC'}
    for name,c in cells.items():
        attrs=c['attributes']
        if c['type']!='SLICE_LUTX' or attrs.get('X_LUT_AS_DRAM','').strip()!='1':continue
        counts['physical_cells']+=1
        assert attrs.get('X_ORIG_TYPE')=='RAMD32',('Unknown LUTRAM profile',name)
        assert number(c['parameters'],'IS_WCLK_INVERTED')==0
        connected=ix.by_cell[name]
        outputs=[p for p,v in connected.items() if v[4]=='output']
        assert len(outputs)<=1 and all(attrs.get('X_ORIG_PORT_'+p)=='O' for p in outputs)
        observable=any(ix.fanout[name,p] for p in outputs)
        if observable:
            counts['observable_cells']+=1
            assert sum(attrs.get('X_ORIG_PORT_'+p)=='I' for p in connected)==1
            assert (name,'CLK') in ix.incoming and ix.constant(name,'CLK') is None
        for pin,v in connected.items():
            orig=attrs.get('X_ORIG_PORT_'+pin)
            cls=None;bound=None;cq=None;reason=None
            if not observable:reason='unobserved_RAM_half_no_output'
            elif orig=='CLK':cls=0;reason='write_clock'
            elif orig=='O':cls=5;cq=limits['clock_to_read']['max_ns'];reason='mixed_read_address_and_write_clock_origins'
            elif orig=='I':cls=2;bound=limits['data'];reason='write_data'
            elif orig=='WE':cls=2;bound=limits['write_enable'];reason='write_enable'
            elif orig and re.fullmatch(r'WADR[0-4]',orig):cls=2;bound=limits['write_address'];reason='write_address'
            elif orig and re.fullmatch(r'RADR[0-4]',orig):cls=4;reason='asynchronous_read_address'
            else:
                assert re.fullmatch(r'A[1-6]',pin) and orig is None
                assert (name,pin) not in arc_inputs,('Shared unused input has an arc',name,pin)
                reason='shared_unused_read_input'
            if cls is not None:
                copy=list(v);copy[5:7]=[str(cls),'1' if bound is not None or cq is not None else '0'];changes[name,pin]=copy
                if cls in (0,2):assert (name,pin) in ix.incoming,('Undriven active port',name,pin)
                if bound is not None or cq is not None:
                    extra.append(['CLOCK',name,pin,'0','CLK','0',str(bound['setup_ns'] if bound else 0),str(bound['hold_ns'] if bound else 0),str(cq or 0)])
            decisions.append(dict(cell=name,port=pin,logical_port=orig,reason=reason,timing_class=cls if cls is not None else int(v[5])))
    assert counts['observable_cells']>0
    result=[changes.get((v[1],v[3]),v) if v[0]=='PORT' else v for v in lines]+extra
    return result,dict(counts=counts,decisions=decisions,full_soc_timing_accepted=False)
