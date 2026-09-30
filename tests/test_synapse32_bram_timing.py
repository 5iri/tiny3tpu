"""Known-path checks and rejection checks for the narrow boot-RAM model."""
from copy import deepcopy
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from synapse32_apply_bram_timing import apply_model, check_profile, limits_from_text
from synapse32_analyze_timing_graph import analyze

class BramTimingTest(unittest.TestCase):
    def setUp(self):
        self.limits=limits_from_text((Path(__file__).resolve().parents[1]/'build-dsp-preg-timing/ds182.txt').read_text())
        self.ram=dict(type='RAMB36E1_RAMB36E1',parameters=dict(RAM_MODE='TDP',WRITE_MODE_A='NO_CHANGE',RAM_EXTENSION_A='NONE',RAM_EXTENSION_B='NONE',READ_WIDTH_A='10',WRITE_WIDTH_A='10',IS_RSTRAMARSTRAM_INVERTED='1'),attributes={})
        self.cells={'ram':self.ram,'src':{'type':'SLICE_FFX'},'dst':{'type':'SLICE_FFX'},'clk':{'type':'BUFGCTRL'},'one':{'type':'PSEUDO_VCC'}}
        self.lines=[['VERSION','1']]
        def add(s):self.lines.append(s.split())
        add('PORT src SLICE_FFX CK input 0 0 clk')
        add('PORT src SLICE_FFX Q output 3 1 data')
        add('CLOCK src Q 0 CK 0 0 0 0.4')
        add('PORT clk BUFGCTRL O output 8 0 clk')
        add('PORT one PSEUDO_VCC Y output 8 0 one')
        for port,orig,net,direction in [('CLKARDCLKL','CLKARDCLK','clk','input'),('CLKARDCLKU','CLKARDCLK','clk','input'),('ADDRARDADDRL1','ADDRARDADDR[1]','data','input'),('DOADO0','DOADO[0]','result','output'),('RSTRAMARSTRAML','RSTRAMARSTRAM','one','input')]:
            self.ram['attributes']['X_ORIG_PORT_'+port]=orig
            add(f'PORT ram RAMB36E1_RAMB36E1 {port} {direction} 8 0 {net}')
        add('NETARC clk clk O ram CLKARDCLKL 0')
        add('NETARC clk clk O ram CLKARDCLKU 0')
        add('NETARC data src Q ram ADDRARDADDRL1 2')
        add('NETARC one one Y ram RSTRAMARSTRAML 0')
        add('NETARC result ram DOADO0 dst D 1.5')
        add('PORT dst SLICE_FFX D input 2 1 result')
        add('PORT dst SLICE_FFX CK input 0 0 clk')
        add('CLOCK dst D 0 CK 0 0.1 0 0')

    def test_known_paths_and_reset_inversion(self):
        rows,decisions=apply_model(self.lines,self.cells,self.limits)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'graph.tsv';path.write_text(''.join('\t'.join(v)+'\n' for v in rows))
            r=analyze(path,tracked_cells=['ram'])
        self.assertFalse(r['unresolved_nodes'])
        maxima={m['group']:m['arrival_ns'] for m in r['tracked_maxima']}
        self.assertEqual(maxima,{'tracked_input':3.05,'tracked_output':4.04})
        self.assertFalse(any(v[0]=='CELLARC' for v in rows))

    def test_unsupported_profiles_rejected(self):
        for key,value in [('READ_WIDTH_A','100'),('WRITE_WIDTH_B','10'),('DOA_REG','1'),('RAM_MODE','SDP'),('EN_ECC_READ','TRUE'),('RAM_EXTENSION_A','LOWER'),('IS_CLKARDCLK_INVERTED','1')]:
            c=deepcopy(self.ram);c['parameters'][key]=value
            with self.subTest(key=key),self.assertRaises(AssertionError):check_profile(c)

    def test_live_reset_and_missing_input_rejected(self):
        self.ram['parameters']['IS_RSTRAMARSTRAM_INVERTED']='0'
        with self.assertRaises(AssertionError):apply_model(self.lines,self.cells,self.limits)
        self.ram['parameters']['IS_RSTRAMARSTRAM_INVERTED']='1'
        rows=[v for v in self.lines if not (v[0]=='NETARC' and v[1]=='data')]
        with self.assertRaises(AssertionError):apply_model(rows,self.cells,self.limits)

if __name__=='__main__':unittest.main()
