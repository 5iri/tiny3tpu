"""Checks for modeled primitive boundaries, packed constants and missing arcs."""
from copy import deepcopy
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import synapse32_registered_dsp_model as dsp
import synapse32_lutram_timing_model as ram
from synapse32_missing_cell_arcs import audit, carry_support
from synapse32_analyze_timing_graph import analyze

ROOT=Path(__file__).resolve().parents[1]
TEXT=(ROOT/'build-dsp-preg-timing/ds182.txt').read_text()

def cell(kind,params=None,attrs=None):return dict(type=kind,parameters=params or {},attributes=attrs or {},connections={})

def fixture():
    params={k:'0' for k in dsp.REGS};params.update(MREG='1',A_INPUT='DIRECT',B_INPUT='DIRECT',USE_MULT='MULTIPLY',USE_DPORT='FALSE',USE_SIMD='ONE48')
    zero=['CARRYIN']+[g+str(i) for g,w in [('INMODE',5),('ALUMODE',4),('CARRYINSEL',3)] for i in range(w)]+['OPMODE1','OPMODE3','OPMODE6']
    c=cell('DSP48E1_DSP48E1',params,{'DSP_GND_PINS':' '.join(zero),'DSP_VCC_PINS':'OPMODE0 OPMODE2 OPMODE4 OPMODE5'})
    cells={'dsp':c,'src':cell('SLICE_FFX'),'dst':cell('SLICE_FFX'),'clk':cell('BUFGCTRL')}
    rows=[['VERSION','1']]
    def add(s):rows.append(s.split())
    for s in ['PORT src SLICE_FFX CK input 0 0 cpu','PORT src SLICE_FFX Q output 3 1 data','CLOCK src Q 0 CK 0 0 0 0.1',
              'PORT clk BUFGCTRL O output 8 0 sys','PORT dsp DSP48E1_DSP48E1 CLK input 8 0 sys',
              'PORT dsp DSP48E1_DSP48E1 A0 input 8 0 data','PORT dsp DSP48E1_DSP48E1 B0 input 8 0 data',
              'PORT dsp DSP48E1_DSP48E1 C0 input 8 0 data','PORT dsp DSP48E1_DSP48E1 P0 output 8 0 result',
              'NETARC sys clk O dsp CLK 0','NETARC data src Q dsp A0 1','NETARC data src Q dsp B0 1','NETARC data src Q dsp C0 1',
              'NETARC result dsp P0 dst D 1','PORT dst SLICE_FFX D input 2 1 result','PORT dst SLICE_FFX CK input 0 0 sys','CLOCK dst D 0 CK 0 0.1 0 0']:add(s)
    return rows,cells

def run(rows,tracked=()):
    with tempfile.TemporaryDirectory() as d:
        p=Path(d)/'g.tsv';p.write_text(''.join('\t'.join(v)+'\n' for v in rows));return analyze(p,tracked)

class DspTest(unittest.TestCase):
    def test_mreg_input_and_bypass_both_timed(self):
        rows,cells=fixture();modeled,coverage=dsp.apply_model(rows,cells,dsp.limits_from_text(TEXT),0)
        r=run(modeled,['dsp']);m={x['group']:x['arrival_ns'] for x in r['tracked_maxima']}
        self.assertEqual(m,{'tracked_input':4.76,'tracked_output':3.41})
        bypass=next(v for v in modeled if v[:4]==['CELLARC','dsp','C0','P0'])
        self.assertEqual(float(bypass[4]),1.84)
        self.assertFalse(coverage['unknown_delays'])

    def test_preg_keeps_original_boundary(self):
        rows,cells=fixture();cells['dsp']['parameters'].update(MREG='0',PREG='1')
        modeled,_=dsp.apply_model(rows,cells,dsp.limits_from_text(TEXT),0)
        m={x['group']:x['arrival_ns'] for x in run(modeled,['dsp'])['tracked_maxima']}
        self.assertEqual(m,{'tracked_input':6.99,'tracked_output':1.55})
        self.assertFalse(any(v[0]=='CELLARC' and v[1]=='dsp' for v in modeled))

    def test_packed_pin_inversion_and_unknown_mode(self):
        rows,cells=fixture();p=cells['dsp']['parameters'];p['IS_OPMODE[1]_INVERTED']='1'
        self.assertEqual(dsp.GraphIndex(rows,cells).word('dsp','OPMODE',7),0x37)
        with self.assertRaises(AssertionError):dsp.apply_model(rows,cells,dsp.limits_from_text(TEXT),0)
        p['IS_OPMODE[1]_INVERTED']='0';p['AREG']='10'
        with self.assertRaises(AssertionError):dsp.apply_model(rows,cells,dsp.limits_from_text(TEXT),0)

class MissingArcsTest(unittest.TestCase):
    def test_fixed_select_stops_carry_dependency(self):
        values={'S0':1,'S1':0,'DI1':1}
        support=carry_support(values,'CIN')
        self.assertIn('CIN',support['CO0'])
        self.assertNotIn('CIN',support['CO1'])
        self.assertFalse(support['CO1'])
        self.assertIn('CIN',support['O1'])

    def test_zero_arc_carry_is_rejected(self):
        cells={'carry':cell('CARRY4'),'src':cell('SLICE_FFX'),'dst':cell('SLICE_FFX')}
        cells['carry']['connections']={'S0':[1],'CO0':[2]}
        rows=[s.split() for s in ['PORT carry CARRY4 S0 input 4 0 n','PORT carry CARRY4 CO0 output 5 0 m','NETARC n src Q carry S0 1','NETARC m carry CO0 dst D 1']]
        r=audit(rows,cells);self.assertFalse(r['carry_arcs_complete']);self.assertEqual(r['missing_carry_arc_count'],1)
        rows.append(['CELLARC','carry','S0','CO0','0.2']);self.assertTrue(audit(rows,cells)['carry_arcs_complete'])

class LutramTest(unittest.TestCase):
    def test_data_setup_and_both_read_origins(self):
        rows,cells=fixture();del cells['dsp']
        attrs={'X_ORIG_TYPE':'RAMD32','X_LUT_AS_DRAM':'1','X_ORIG_PORT_CLK':'CLK','X_ORIG_PORT_A1':'RADR0','X_ORIG_PORT_WA1':'WADR0','X_ORIG_PORT_DI2':'I','X_ORIG_PORT_WE':'WE','X_ORIG_PORT_O6':'O'}
        cells['ram']=cell('SLICE_LUTX',{'IS_WCLK_INVERTED':'0'},attrs)
        rows=[r for r in rows if not any(x=='dsp' for x in r)]
        rows.extend([s.split() for s in ['PORT ram SLICE_LUTX CLK input 8 0 sys','NETARC sys clk O ram CLK 0',
                     'PORT ram SLICE_LUTX A1 input 4 0 data','PORT ram SLICE_LUTX WA1 input 8 0 data',
                     'PORT ram SLICE_LUTX DI2 input 8 0 data','PORT ram SLICE_LUTX WE input 8 0 data',
                     'PORT ram SLICE_LUTX O6 output 5 0 result','NETARC data src Q ram A1 1',
                     'NETARC data src Q ram WA1 1','NETARC data src Q ram DI2 1','NETARC data src Q ram WE 1',
                     'NETARC result ram O6 dst D 1','CELLARC ram A1 O6 0.2']])
        modeled,coverage=ram.apply_model(rows,cells,ram.limits_from_text(TEXT));r=run(modeled,['ram'])
        self.assertEqual(coverage['counts']['observable_cells'],1)
        m={x['group']:x['arrival_ns'] for x in r['tracked_maxima']}
        self.assertEqual(m,{'tracked_input':1.79,'tracked_output':2.54})
        self.assertTrue(any(v[:4]==['CELLARC','ram','A1','O6'] for v in modeled))
        cells['ram']['parameters']['IS_WCLK_INVERTED']='1'
        with self.assertRaises(AssertionError):ram.apply_model(rows,cells,ram.limits_from_text(TEXT))

if __name__=='__main__':unittest.main()
