import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import synapse32_primitive_guidance_normalize as subject


class PrimitiveNormalizationTest(unittest.TestCase):
    def setUp(self):
        self.cells={f'ram{i}':dict(type='RAMB36E1_RAMB36E1',parameters={}) for i in range(16)}
        self.cells.update({f'dsp{i}':dict(type='DSP48E1_DSP48E1',parameters={'MREG':'1'}) for i in range(4)})
        self.legacy=[]
        for n in self.cells:
            self.legacy += [['PORT',n,self.cells[n]['type'],'D','input','8','0',n+'_d'],
                            ['PORT',n,self.cells[n]['type'],'Q','output','8','0',n+'_q']]

    @staticmethod
    def modeled(rows,prefix):
        rows=copy.deepcopy(rows);clocks=[]
        for r in rows:
            if r[0]=='PORT' and r[1].startswith(prefix):
                r[5:7]=['2' if r[3]=='D' else '5' if prefix=='dsp' else '3','1']
                clocks.append(['CLOCK',r[1],r[3],'0','CLK','0','0.65' if r[3]=='D' else '0','0.38','2.44'])
        return rows+clocks

    def call(self,rows):
        profiles={n:dict(mode=5,kind='cpu_mreg') for n in self.cells if n.startswith('dsp')}
        with patch.object(subject,'bram_model',side_effect=lambda r,c,l:(self.modeled(r,'ram'),[])), \
             patch.object(subject,'dsp_model',side_effect=lambda r,c,l,pcout_ns:(self.modeled(r,'dsp'),dict(profiles=profiles,unknown_delays=[]))):
            return subject.normalize(rows,self.cells,{}, {})

    def native(self):
        rows=self.modeled(self.modeled(self.legacy,'ram'),'dsp')
        for r in rows:
            if r[0]=='PORT' and r[5]=='5':r[5]='3'
        return rows

    def test_valid_normalization_preserves_legacy(self):
        legacy,record=self.call(self.native())
        self.assertEqual(legacy,self.legacy)
        self.assertEqual(record['new_clock_rows'],40)

    def test_decimal_format_is_not_a_timing_difference(self):
        rows=self.native()
        for r in rows:
            if r[0]=='CLOCK':r[6:9]=[format(float(v),'.6f') for v in r[6:9]]
        self.assertTrue(self.call(rows)[1]['passed'])

    def test_rejects_missing_clock_check(self):
        rows=self.native();rows.pop()
        with self.assertRaises(AssertionError):self.call(rows)

    def test_rejects_setup_change(self):
        rows=self.native();next(r for r in rows if r[0]=='CLOCK')[6]='0.649'
        with self.assertRaises(AssertionError):self.call(rows)

    def test_rejects_hold_change(self):
        rows=self.native();next(r for r in rows if r[0]=='CLOCK')[7]='0.379'
        with self.assertRaises(AssertionError):self.call(rows)

    def test_rejects_ignored_capture(self):
        rows=self.native();rows[0][5]='8'
        with self.assertRaises(AssertionError):self.call(rows)

    def test_rejects_hybrid_dsp_arc(self):
        rows=self.native()+[['CELLARC','dsp0','D','Q','0.1']]
        with self.assertRaises(AssertionError):self.call(rows)


if __name__=='__main__':unittest.main()
