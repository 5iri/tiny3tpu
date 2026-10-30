#!/usr/bin/env python3
"""Execute generated tile kernels against the independent MMIO device model."""
import ctypes
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from test_stablehlo_compiler import Compiled, HARNESS, np
from tools.program import CompileOptions, KC705, KC705_DIRECT
from tools.program._schedule import ExecutionPlan


DEVICE = r'''
#define main generic_mmio_selftest
#include "DEVICE_SOURCE"
#undef main
static device simulated;
static unsigned kernel_calls;
void configure(unsigned flags,unsigned failure){
 memset(&simulated,0,sizeof(simulated));kernel_calls=0;calls=0;packed_calls=0;
 simulated.accum_cap=(flags&1)!=0;simulated.result_window=(flags&2)!=0;
 simulated.stuck=(flags&4)!=0;simulated.instant=(flags&8)!=0;
 simulated.pending=(flags&16)?1:0;simulated.fail_at=failure;
}
unsigned accesses(void){return simulated.accesses;}
unsigned launches(void){return simulated.starts;}
unsigned specialized_calls(void){return kernel_calls;}
static int kernel_write(void *user,uint32_t offset,uint32_t value){
 int status=write32(user,offset,value);
 /* An instant completion has no outstanding busy interval. */
 if(!status&&simulated.instant&&offset==0U&&(value==1U||value==9U))simulated.pending=0;
 return status;
}
static int kernel_entry(void *user,tiny3tpu_mmio_kernel kernel,void *context){
 if(user)return -1;
 tiny3tpu_mmio io={&simulated,read32,kernel_write,16};kernel_calls++;
 return tiny3tpu_mmio_run_kernel(&io,kernel,context);
}
'''.replace('DEVICE_SOURCE', str(ROOT/'tests/mmio_backend_test.c'))
HARNESS = HARNESS.replace('int run(', DEVICE+'\nint run(').replace(
    'mode>=3?gemm_packed:0,0}', 'mode>=3?gemm_packed:0,mode>=5?kernel_entry:0}')


class MMIOCodegenTests(unittest.TestCase):
    def compile(self, m, k, n, *, batch=None, constant=None, view=False, prepack=True,
                target=KC705,policy='tpu',specialize=True):
        rng = np.random.default_rng(m * 100 + k * 10 + n)
        ashape = (m,k) if batch is None else (batch,m,k)
        bshape = (k,n) if batch is None else (batch,k,n)
        a = rng.integers(-128,128,ashape,dtype=np.int8)
        b = rng.integers(-128,128,bshape,dtype=np.int8)
        plan = ExecutionPlan()
        aid = plan.const(a) if constant in ('a','both') else plan.value(ashape,'int8')
        bid = plan.const(b) if constant in ('b','both') else plan.value(bshape,'int8')
        plan.inputs = [i for i in (aid,bid) if plan.values[i].data is None]
        arrays = [a,b] if constant is None else [b] if constant=='a' else [a] if constant=='b' else []
        if view:
            mapping = np.arange(b.size).reshape(bshape)[...,::-1].ravel().tolist()
            bid = plan.operation('index',[bid],bshape,'int8',map=mapping)
            b = b[...,::-1]
        shape = (m,n) if batch is None else (batch,m,n)
        result = plan.operation('matmul',[aid,bid],shape,'int32')
        plan.outputs = [result]
        compiled = Compiled(None,CompileOptions(target=target,gemm_policy=policy,prepack_constants=prepack,
                                               specialize_matmuls=specialize),
                            harness=HARNESS,plan=plan,extra_sources=[ROOT/'src/mmio_backend.c'])
        self.addCleanup(compiled.close)
        compiled.library.configure.argtypes = [ctypes.c_uint,ctypes.c_uint]
        return compiled,arrays,a,b

    def check(self, compiled, arrays, a, b, flags=3):
        compiled.library.configure(flags,0)
        status,actual = compiled.run(*arrays,mode=5)
        self.assertEqual(status,0)
        np.testing.assert_array_equal(actual[0],a.astype(np.int64) @ b.astype(np.int64))
        self.assertEqual(compiled.library.specialized_calls(),1 if a.ndim==2 else a.shape[0])
        self.assertEqual(compiled.library.backend_calls()+compiled.library.packed_backend_calls(),0)

    def test_schedules_and_tails(self):
        for shape in [(1,1,1),(4,4,8),(8,4,4),(4,8,4),(5,11,7),(9,9,9),
                      (1,9,1),(1,17,10),(28,3,3),(17,5,9),(8,8,8),(16,32,16),
                      (4,9,17),(9,5,1),(9,3,9),(1,3,17)]:
            with self.subTest(shape=shape):
                c,arrays,a,b = self.compile(*shape)
                self.check(c,arrays,a,b)
                # Different inputs on the same device must replace previous
                # operands, including hoisted weights and padded K lanes.
                for value in arrays:value[:] = np.bitwise_not(value)
                status,actual = c.run(*arrays,mode=5)
                self.assertEqual(status,0)
                np.testing.assert_array_equal(actual[0],a.astype(np.int64) @ b.astype(np.int64))

    def test_constants_batches_and_index_views(self):
        for constant in ('a','b','both'):
            for prepack in (False,True):
                with self.subTest(constant=constant,prepack=prepack):
                    c,arrays,a,b = self.compile(5,9,7,batch=2,constant=constant,view=True,prepack=prepack)
                    self.check(c,arrays,a,b)

    def test_shared_projection_kernel_uses_each_context(self):
        rng=np.random.default_rng(42)
        a=rng.integers(-128,128,(8,8),dtype=np.int8)
        weights=[rng.integers(-128,128,(8,8),dtype=np.int8) for _ in range(3)]
        plan=ExecutionPlan();aid=plan.value(a.shape,'int8');plan.inputs=[aid]
        plan.outputs=[plan.operation('matmul',[aid,plan.const(b)],(8,8),'int32') for b in weights]
        c=Compiled(None,CompileOptions(target=KC705,gemm_policy='tpu'),harness=HARNESS,
                   plan=plan,extra_sources=[ROOT/'src/mmio_backend.c'])
        self.addCleanup(c.close)
        self.assertEqual(c.report['specialized_kernel_count'],1)
        c.library.configure(3,0)
        status,outputs=c.run(a,mode=5)
        self.assertEqual(status,0)
        for actual,b in zip(outputs,weights):
            np.testing.assert_array_equal(actual,a.astype(np.int64) @ b.astype(np.int64))
        self.assertEqual(c.library.specialized_calls(),3)

    def test_shared_kernel_self_product_then_distinct_operands(self):
        plan=ExecutionPlan();aid=plan.value((4,4),'int8');bid=plan.value((4,4),'int8')
        plan.inputs=[aid,bid]
        plan.outputs=[plan.operation('matmul',[aid,aid],(4,4),'int32'),
                      plan.operation('matmul',[aid,bid],(4,4),'int32')]
        c=Compiled(None,CompileOptions(target=KC705,gemm_policy='tpu'),harness=HARNESS,
                   plan=plan,extra_sources=[ROOT/'src/mmio_backend.c'])
        self.addCleanup(c.close)
        self.assertEqual(c.report['specialized_kernel_count'],1)
        a=np.arange(16,dtype=np.int8).reshape(4,4)-8;b=np.flip(a,axis=0)
        c.library.configure(3,0)
        status,outputs=c.run(a,b,mode=5)
        self.assertEqual(status,0)
        np.testing.assert_array_equal(outputs[0],a.astype(np.int64) @ a.astype(np.int64))
        np.testing.assert_array_equal(outputs[1],a.astype(np.int64) @ b.astype(np.int64))

    def test_legacy_capabilities_fall_back_before_writes(self):
        c,arrays,a,b = self.compile(5,11,7,constant='b')
        for flags in (0,1,2):
            c.library.configure(flags,0)
            status,actual = c.run(*arrays,mode=5)
            self.assertEqual(status,0)
            np.testing.assert_array_equal(actual[0],a.astype(np.int64) @ b.astype(np.int64))
            self.assertEqual(c.library.launches(),0)
            self.assertEqual(c.library.accesses(),1)
            self.assertEqual(c.library.packed_backend_calls(),1)

    def test_errors_do_not_retry_after_writes(self):
        c,arrays,a,b = self.compile(5,11,7)
        self.check(c,arrays,a,b)
        count = c.library.accesses()
        for failure in range(1,count+1):
            c.library.configure(3,failure)
            status,_ = c.run(*arrays,mode=5)
            self.assertEqual(status,-5,f'bus access {failure}')
            self.assertEqual(c.library.backend_calls()+c.library.packed_backend_calls(),0)
        for flags in (3|4,3|16):
            c.library.configure(flags,0)
            self.assertEqual(c.run(*arrays,mode=5)[0],-5)
        self.check(c,arrays,a,b,flags=3|8)

    def test_accumulator_bound(self):
        c,arrays,a,b = self.compile(1,131071,1)
        for value in arrays:value.fill(-128)
        self.check(c,arrays,a,b)
        a.fill(127)
        self.check(c,arrays,a,b)

    def test_direct_placement_and_generic_opt_out(self):
        for shape in ((1,784,10),(204,3,3),(8,8,8),(16,256,16)):
            for specialize in (False,True):
                with self.subTest(shape=shape,specialize=specialize):
                    c,arrays,a,b = self.compile(*shape,target=KC705_DIRECT,policy='auto',specialize=specialize)
                    placement = next(p for p in c.report['placement'] if p['op']=='matmul')
                    expected_tpu = specialize or shape==(16,256,16)
                    self.assertEqual(placement['device'],'tpu' if expected_tpu else 'cpu')
                    self.assertEqual(bool(c.report['specialized_matmuls']),specialize)
                    c.library.configure(3,0)
                    status,actual = c.run(*arrays,mode=5)
                    self.assertEqual(status,0)
                    np.testing.assert_array_equal(actual[0],a.astype(np.int64) @ b.astype(np.int64))
                    self.assertEqual(c.library.specialized_calls(),int(specialize))


if __name__=='__main__':
    unittest.main()
