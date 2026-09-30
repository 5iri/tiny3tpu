"""Validate all four actual CPU input-register profiles and reject hybrid stages."""
import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import synapse32_cpu_preg_dsp_model as model
class ProfileTest(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  fixture=json.loads((ROOT/'tests/fixtures/cpu_dsp_preg_profiles.json').read_text())
  cls.cells=fixture['cells'];cls.rows=fixture['rows']
  cls.names=[n for n,c in cls.cells.items() if c['type']=='DSP48E1_DSP48E1' and 'cpu' in n]
  assert len(cls.names)==4
 def make(self):
  cells=copy.deepcopy(self.cells)
  for n in self.names:cells[n]['parameters'].update(MREG='0',PREG='1')
  return model.GraphIndex(self.rows,cells)
 def test_actual_four_profiles(self):
  index=self.make();seen=set()
  for n in self.names:
   p=model.profile(index,n);self.assertEqual(p['kind'],'cpu_preg');seen.add((p['registers']['AREG'],p['registers']['BREG']))
  self.assertEqual(seen,{(0,0),(0,1),(1,0),(1,1)})
 def test_rejects_extra_product_stage(self):
  index=self.make();n=self.names[0];index.cells[n]['parameters']['MREG']='1'
  with self.assertRaises(AssertionError):model.profile(index,n)
 def test_rejects_input_register_mismatch(self):
  index=self.make();n=self.names[0];index.cells[n]['parameters'].update(AREG='1',ACASCREG='0')
  with self.assertRaises(AssertionError):model.profile(index,n)
 def test_original_mreg_profiles_preserved(self):
  index=model.GraphIndex(self.rows,self.cells)
  self.assertTrue(all(model.profile(index,n)['kind']=='cpu_mreg' for n in self.names))
