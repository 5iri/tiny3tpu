import copy,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import synapse32_kc705_grade2_limits as model
class GradeSelection(unittest.TestCase):
 def test_dsp_column_and_negative_hold(self):
  original={'AB_P':{'setup_ns':99,'hold_ns':99,'all_grades':[('3.41','-0.24'),('3.90','-0.24'),('4.64','-0.24'),('4.64','-0.24'),('3.90','-0.24'),('5.89','-0.41')]},'P_P':{'max_ns':.45,'all_grades':[.31,.35,.42,.42,.35,.45]}}
  frozen=copy.deepcopy(original)
  with patch.object(model,'all_dsp',return_value=original):actual=model.dsp_limits('')
  self.assertEqual(actual['AB_P']['setup_ns'],3.9);self.assertEqual(actual['AB_P']['hold_ns'],0);self.assertEqual(actual['P_P']['max_ns'],.35);self.assertEqual(original,frozen)
 def test_bram_uses_matching_grade_not_global_extreme(self):
  original={'data':{'setup_ns':9,'hold_ns':9,'setup_all_grades':[.4,.55,.7,.7,.55,.78],'hold_all_grades':[.4,.53,.6,.6,.53,.64]},'read_output':{'clock_to_output_ns':9,'all_grades':[1.6,1.8,2.1,2.1,1.8,2.44]},'internal_fmax':{'minimum_mhz':1,'all_grades':[600,543.77,450,450,543.77,372.44]}}
  with patch.object(model,'all_bram',return_value=original):actual=model.bram_limits('')
  self.assertEqual((actual['data']['setup_ns'],actual['data']['hold_ns']),(.55,.53));self.assertEqual(actual['read_output']['clock_to_output_ns'],1.8);self.assertEqual(actual['internal_fmax']['minimum_mhz'],543.77)
 def test_lutram_checks_both_address_rows_in_same_column(self):
  pairs=[(9,9)]*12;pairs[1]=(.4,.1);pairs[7]=(.3,.5)
  original={'write_address':{'setup_ns':9,'hold_ns':9,'all_grades':pairs},'clock_to_read':{'max_ns':9,'all_grades':[.8,.95,1.1,1.1,.95,1.44]}}
  with patch.object(model,'all_lutram',return_value=original):actual=model.lutram_limits('')
  self.assertEqual((actual['write_address']['setup_ns'],actual['write_address']['hold_ns']),(.4,.5));self.assertEqual(actual['clock_to_read']['max_ns'],.95)
if __name__=='__main__':unittest.main()
