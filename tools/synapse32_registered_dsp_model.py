"""Exact current DSP profiles; one cascade clock delay remains symbolic.

CPU: MREG=1, PREG=0, optional single A/B input stages, fixed multiply/add modes.
PE: PREG=1, all other registers bypassed, fixed A*B+C. No mode inference from
constant physical nets without first undoing packed pin inversions.
"""
from collections import Counter, defaultdict
import re
from synapse32_apply_bram_timing import number

REGS=('AREG','BREG','CREG','DREG','ADREG','MREG','PREG','ACASCREG','BCASCREG',
      'ALUMODEREG','CARRYINREG','CARRYINSELREG','INMODEREG','OPMODEREG')


def limits_from_text(text):
    limits={}
    rows=[('A','TDSPDCK_A_AREG/',.38),('B','TDSPDCK_B_BREG/',.51),
          ('AB_M','TDSPDCK_{A, B}_MREG_MULT/',3.66),
          ('AB_P','TDSPDCK_{A, B}_PREG_MULT/',5.89),('C_P','TDSPDCK_C_PREG/',2.11),
          ('CE_AB','TDSPDCK_{CEA;CEB}_{AREG;BREG}/',.55),('CEM','TDSPDCK_CEM_MREG/',.39),
          ('CEP','TDSPDCK_CEP_PREG/',.54),('RST_AB','TDSPDCK_{RSTA; RSTB}_{AREG; BREG}/',.53),
          ('RSTM','TDSPDCK_RSTM_MREG/',.24),('RSTP','TDSPDCK_RSTP_PREG/',.37)]
    for key,marker,expected in rows:
        row=text[text.index(marker):].split('\nns',1)[0].replace('–','-').replace('−','-')
        pairs=re.findall(r'(-?\d+\.\d+)/\s*(-?\d+\.\d+)',row)
        assert len(pairs)==6,(key,pairs)
        setup,hold=zip(*[(float(s),float(h)) for s,h in pairs]);assert max(setup)==expected
        limits[key]=dict(setup_ns=max(setup),hold_ns=max(0,max(hold)),all_grades=pairs)
    for key,marker,expected in [('P_M','TDSPCKO_P_MREG ',2.31),('P_P','TDSPCKO_P_PREG ',.45),
                                ('C_P_comb','TDSPDO_C_P ',1.84),('PCIN_P_comb','TDSPDO_PCIN_P ',1.54)]:
        row=text[text.index(marker):].split(' ns',1)[0]
        nums=[float(n) for n in re.findall(r'\d+\.\d+',row)]
        assert len(nums)==6 and max(nums)==expected,(key,nums)
        limits[key]=dict(max_ns=max(nums),all_grades=nums)
    return limits


class GraphIndex:
    def __init__(self,lines,cells):
        self.cells=cells;self.ports={};self.by_cell=defaultdict(dict);self.incoming={};self.fanout=Counter()
        for v in lines:
            if v[0]=='PORT':
                self.ports[v[1],v[3]]=v;self.by_cell[v[1]][v[3]]=v
            elif v[0]=='NETARC':
                self.incoming[v[4],v[5]]=(v[2],v[3]);self.fanout[v[2],v[3]]+=1

    def constant(self,name,pin):
        c=self.cells[name];key=(name,pin);driver=self.incoming.get(key)
        raw=None
        if driver:
            t=self.cells[driver[0]]['type']
            raw=0 if t=='PSEUDO_GND' else 1 if t=='PSEUDO_VCC' else None
        else:
            for val,attr in [(0,'DSP_GND_PINS'),(1,'DSP_VCC_PINS')]:
                if pin in c['attributes'].get(attr,'').split():raw=val
        if raw is None:return None
        orig=c['attributes'].get('X_ORIG_PORT_'+pin)
        if orig is None:
            m=re.fullmatch(r'(OPMODE|INMODE|ALUMODE|CARRYINSEL)(\d+)',pin)
            orig=m[1]+'['+m[2]+']' if m else pin
        return raw ^ number(c['parameters'],'IS_'+orig+'_INVERTED')

    def word(self,name,base,width):
        values=[self.constant(name,base+str(i)) for i in range(width)]
        assert None not in values,('Nonconstant mode',name,base,values)
        return sum(v<<i for i,v in enumerate(values))


def profile(index,name):
    c=index.cells[name];p=c['parameters']
    assert c['type']=='DSP48E1_DSP48E1'
    for k,v in [('A_INPUT','DIRECT'),('B_INPUT','DIRECT'),('USE_MULT','MULTIPLY'),
                ('USE_DPORT','FALSE'),('USE_SIMD','ONE48')]:assert p.get(k)==v,(name,k)
    assert p.get('USE_PATTERN_DETECT','NO_PATDET')=='NO_PATDET'
    assert number(p,'IS_CLK_INVERTED')==0
    mode=index.word(name,'OPMODE',7)
    assert index.word(name,'INMODE',5)==index.word(name,'ALUMODE',4)==index.word(name,'CARRYINSEL',3)==0
    assert index.constant(name,'CARRYIN')==0
    regs={r:number(p,r) for r in REGS}
    if regs['PREG']==1:
        assert all(v==0 for k,v in regs.items() if k!='PREG') and mode==0x35
        kind='pe_preg'
    else:
        assert regs['MREG']==1 and regs['PREG']==0
        assert regs['AREG'] in (0,1) and regs['BREG'] in (0,1)
        assert regs['ACASCREG']==regs['AREG'] and regs['BCASCREG']==regs['BREG']
        assert all(v==0 for k,v in regs.items() if k not in ('AREG','BREG','ACASCREG','BCASCREG','MREG'))
        assert mode in (0x05,0x15,0x35)
        kind='cpu_mreg'
    assert (name,'CLK') in index.incoming and index.constant(name,'CLK') is None
    return dict(kind=kind,mode=mode,registers=regs)


def apply_model(lines,cells,limits,pcout_ns):
    # pcout_ns is explicitly a symbolic diagnostic substitution, never a
    # validated bound. The caller must retain unknown-delay provenance.
    assert pcout_ns>=0
    ix=GraphIndex(lines,cells);replacements={};new=[];decisions=[];unknown=[]
    profiles={n:profile(ix,n) for n,c in cells.items() if c['type']=='DSP48E1_DSP48E1' and any(number(c['parameters'],r) for r in REGS)}
    assert profiles
    for (name,pin),v in ix.ports.items():
        if name not in profiles:continue
        cfg=profiles[name];regs=cfg['registers'];base=re.sub(r'\d+$','',pin)
        kind=cfg['kind'];mode=cfg['mode'];cls=None;bound=None;cq=None;reason=None
        is_dynamic=(name,pin) in ix.incoming and ix.constant(name,pin) is None
        if pin=='CLK':cls=0;reason='clock'
        elif v[4]=='output':
            if not ix.fanout[name,pin]:reason='unused_output'
            elif base=='P':
                cls=3 if kind=='pe_preg' else 5
                cq=limits['P_P' if kind=='pe_preg' else 'P_M']['max_ns'];reason='registered_output_with_bypass_paths' if cls==5 else 'registered_output'
            elif base=='PCOUT':
                assert kind=='cpu_mreg' and mode==0x05,('Unsupported cascade mode',name)
                cls=3;cq=pcout_ns;reason='symbolic_clock_to_PCOUT'
                unknown.append(dict(cell=name,port=pin,arc='CLK->PCOUT',substitution_ns=pcout_ns,
                                    reason='No Kintex-7 PCOUT bound in available DS182 rows or local Kintex timing data.'))
            else:raise AssertionError(('Unsupported output',name,pin))
        elif base in ('A','B'):
            cls=2;reason=base if regs[base+'REG'] else 'AB_M' if kind=='cpu_mreg' else 'AB_P';bound=limits[reason]
        elif base=='C' and mode==0x35:
            cls=2 if kind=='pe_preg' else 4;reason='C_P' if cls==2 else 'C_P_comb'
            if cls==2:bound=limits[reason]
        elif base=='PCIN' and mode==0x15:
            cls=4;reason='PCIN_P_comb'
        elif pin in ('RSTA','RSTB') and regs[pin[-1]+'REG']:
            cls=2;reason='RST_AB';bound=limits[reason]
        elif pin in ('CEA2','CEB2') and regs[pin[2]+'REG']:
            cls=2;reason='CE_AB';bound=limits[reason]
        elif pin in ('RSTM','CEM') and regs['MREG']:
            cls=2;reason=pin;bound=limits[reason]
        elif pin in ('RSTP','CEP') and regs['PREG']:
            cls=2;reason=pin;bound=limits[reason]
        else:
            assert not is_dynamic,('Unmodeled live input',name,pin)
            assert (name,pin) in ix.incoming,('Undriven input',name,pin)
            reason='constant_inactive_or_mode_input'
        if cls is not None:
            assert v[5:7]==['8','0'],('Already modeled registered DSP',name,pin)
            copy=list(v);copy[5:7]=[str(cls),'1' if bound is not None or cq is not None else '0'];replacements[name,pin]=copy
            if bound is not None or cq is not None:
                new.append(['CLOCK',name,pin,'0','CLK','0',str(bound['setup_ns'] if bound else 0),str(bound['hold_ns'] if bound else 0),str(cq or 0)])
            if cls==4:
                for o,ov in ix.by_cell[name].items():
                    if re.fullmatch('P[0-9]+',o) and ix.fanout[name,o]:
                        new.append(['CELLARC',name,pin,o,str(limits[reason]['max_ns'])])
        decisions.append(dict(cell=name,port=pin,timing_class=cls if cls is not None else 8,reason=reason,dynamic=is_dynamic))
    enhanced=[replacements.get((v[1],v[3]),v) if v[0]=='PORT' else v for v in lines]+new
    return enhanced,dict(profiles=profiles,decisions=decisions,unknown_delays=unknown,
                         timing_bounds_complete=not unknown,full_soc_timing_accepted=False)
