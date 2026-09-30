"""Compiler pass checks: signed wide reconstruction and nonlinear rejection."""
import sys,tempfile,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import jax.numpy as jnp
from tools.jax_affine_lowering import lower_rowwise_affine,split_signed16,LoweringError
class AffineLoweringTest(unittest.TestCase):
 def test_signed_wide_boundaries(self):
  a=np.arange(-32640,32640,dtype=np.int32);lo,hi=split_signed16(a)
  np.testing.assert_array_equal(lo.astype(np.int32)+256*hi.astype(np.int32),a)
  for bad in ([-32641],[32640],[1.5]):
   with self.assertRaises(LoweringError):split_signed16(bad)
 def test_linear_kernel_and_shape(self):
  with tempfile.TemporaryDirectory() as d:
   r=lower_rowwise_affine(lambda x:jnp.stack((2*x[:,0]-3*x[:,1],x[:,1]),1),3,2,Path(d)/'model.json')
   self.assertEqual(r['weights'],[[2,0],[-3,1]])
   self.assertEqual(r['graph']['tensors'][0]['shape'],[6,2])
 def test_reject_nonlinear_and_mixed_rows(self):
  functions=[lambda x:x*x,lambda x:jnp.sqrt(x),lambda x:x+1,
             lambda x:x+jnp.roll(x,1,axis=0),lambda x:jnp.stack((x[0,0]*x[:,0],x[:,1]),1)]
  with tempfile.TemporaryDirectory() as d:
   for f in functions:
    with self.subTest(f=f),self.assertRaises(LoweringError):lower_rowwise_affine(f,3,2,Path(d)/'bad.json')
if __name__=='__main__':unittest.main()
