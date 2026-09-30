import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from synapse32_lutram_timing_model import apply_model
from synapse32_mixed_primitive_guidance_normalize import normalize_lutram


class MixedNormalizationTest(unittest.TestCase):
    def setUp(self):
        attrs={'X_LUT_AS_DRAM':'1','X_ORIG_TYPE':'RAMD32'}
        self.pins={'CLK':'CLK','DI1':'I','WE':'WE','WA1':'WADR0','A1':'RADR0','O6':'O'}
        attrs.update({'X_ORIG_PORT_'+p:o for p,o in self.pins.items()})
        self.cells={'ram':dict(type='SLICE_LUTX',attributes=attrs,parameters={'IS_WCLK_INVERTED':'0'}),
                    'source':dict(type='SLICE_FFX',attributes={},parameters={}),
                    'sink':dict(type='SLICE_FFX',attributes={},parameters={})}
        self.legacy=[]
        for p,o in self.pins.items():
            cls=5 if o=='O' else 4 if o.startswith('RADR') else 8
            self.legacy.append(['PORT','ram','SLICE_LUTX',p,'output' if o=='O' else 'input',str(cls),'0',p+'_net'])
            self.legacy.append(['NETARC',p+'_net','ram','O6','sink','D','0.23'] if o=='O' else ['NETARC',p+'_net','source','Q','ram',p,'0.17'])
        self.legacy.append(['CELLARC','ram','A1','O6','0.2'])
        self.limits={'data':dict(setup_ns=.69,hold_ns=.33),'write_enable':dict(setup_ns=.46,hold_ns=.11),
                     'write_address':dict(setup_ns=.63,hold_ns=.63),'clock_to_read':dict(max_ns=1.44)}
        self.native=apply_model(copy.deepcopy(self.legacy),self.cells,self.limits)[0]

    def call(self,rows):return normalize_lutram(rows,self.cells,self.limits)

    def test_both_origins_retained(self):
        legacy,record=self.call(self.native)
        self.assertEqual(legacy,self.legacy)
        self.assertTrue(record['asynchronous_read_arcs_retained'])
        self.assertEqual(record['new_clock_rows'],4)

    def test_rejects_clock_origin_removed(self):
        rows=[r for r in self.native if not (r[0]=='CLOCK' and r[2]=='O6')]
        with self.assertRaises(AssertionError):self.call(rows)

    def test_rejects_registered_output_class(self):
        rows=copy.deepcopy(self.native)
        next(r for r in rows if r[0]=='PORT' and r[3]=='O6')[5]='3'
        with self.assertRaises(AssertionError):self.call(rows)

    def test_rejects_write_setup_reduction(self):
        rows=copy.deepcopy(self.native)
        next(r for r in rows if r[0]=='CLOCK' and r[2]=='DI1')[6]='0.68'
        with self.assertRaises(AssertionError):self.call(rows)

    def test_rejects_write_hold_reduction(self):
        rows=copy.deepcopy(self.native)
        next(r for r in rows if r[0]=='CLOCK' and r[2]=='WA1')[7]='0.62'
        with self.assertRaises(AssertionError):self.call(rows)

    def test_rejects_unknown_primitive(self):
        self.cells['ram']['attributes']['X_ORIG_TYPE']='RAMD64'
        with self.assertRaises(AssertionError):self.call(self.native)


if __name__=='__main__':unittest.main()
