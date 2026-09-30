#!/usr/bin/env python3
"""Execute generated code and compare independent StableHLO/JAX workloads."""
import ctypes
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    import jax
    import jax.numpy as jnp
    import numpy as np
except ImportError:
    print('SKIP: install the StableHLO/JAX test dependencies')
    raise SystemExit(77)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.jax_stablehlo import export_function
from tools.program import compile_stablehlo, CompileOptions, CPU, KC705, KC705_ROCKET, Target, ProgramError, AffineCostModel


HARNESS = r'''
#include "program.h"
static t3p_workspace workspace;
static unsigned calls;
static int gemm(void *user,const int8_t *a,const int8_t *b,int32_t *out,
                uint32_t m,uint32_t k,uint32_t n) {
    calls++;
    if(user)return -1;
    for(uint32_t i=0;i<m;i++) {
        for(uint32_t j=0;j<n;j++) {
            int64_t sum=0;
            for(uint32_t t=0;t<k;t++)sum+=(int32_t)a[i*k+t]*b[t*n+j];
            if(sum<INT32_MIN||sum>INT32_MAX)return -1;
            out[i*n+j]=(int32_t)sum;
        }
    }
    return 0;
}
int run(const void *const *inputs,void *const *outputs,int mode) {
    tiny3tpu_qgemm_backend backend={mode==2?&calls:0,gemm};
    return t3p_run(inputs,outputs,&workspace,mode==1?0:&backend);
}
unsigned backend_calls(void){return calls;}
unsigned workspace_size(void){return sizeof(workspace);}
'''


class Compiled:
    def __init__(self, source, options=None):
        self.temp = tempfile.TemporaryDirectory(prefix='tiny3tpu-stablehlo-')
        self.path = Path(self.temp.name)
        self.report = compile_stablehlo(source, self.path/'program.h', options)
        (self.path/'check.c').write_text(HARNESS)
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic',
                        '-O2','-ffp-contract=off','-shared','-fPIC', '-I'+str(ROOT/'include'),
                        str(self.path/'check.c'),'-lm','-o',str(self.path/'check.so')], check=True, capture_output=True)
        self.library = ctypes.CDLL(str(self.path/'check.so'))
        self.library.run.argtypes = [ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p), ctypes.c_int]
        assert self.library.workspace_size()==self.report['workspace_bytes'], 'workspace size report mismatch'

    def run(self, *inputs, mode=0):
        arrays = [np.ascontiguousarray(x) for x in inputs]
        outputs = [np.full(v['shape'], 17, dtype=v['dtype']) for v in self.report['signature']['outputs']]
        in_ptrs = (ctypes.c_void_p*len(arrays))(*(a.ctypes.data for a in arrays))
        out_ptrs = (ctypes.c_void_p*len(outputs))(*(a.ctypes.data for a in outputs))
        status = self.library.run(in_ptrs, out_ptrs, mode)
        return status, outputs

    def close(self):
        self.temp.cleanup()


class StableHLOTests(unittest.TestCase):
    def compile(self, source, options=None):
        result = Compiled(source, options)
        self.addCleanup(result.close)
        return result

    def check(self, function, inputs, options=None, atol=2e-6, rtol=2e-6):
        compiled = self.compile(export_function(function, *inputs), options)
        status, actual = compiled.run(*inputs)
        self.assertEqual(status, 0)
        expected = jax.tree.leaves(function(*[jnp.asarray(a) for a in inputs]))
        self.assertEqual(len(actual), len(expected))
        for got, wanted in zip(actual, expected):
            if got.dtype == np.float32:
                np.testing.assert_allclose(got, wanted, atol=atol, rtol=rtol)
            else:
                np.testing.assert_array_equal(got, wanted)
        return compiled

    def test_handwritten_stablehlo_without_jax_import(self):
        source = '''module {func.func @main(%a:tensor<2x3xf32>, %b:tensor<2x3xf32>)
          -> (tensor<2x3xf32>,tensor<2x3xf32>) {
          %x=stablehlo.add %a,%b:tensor<2x3xf32>
          %y=stablehlo.multiply %a,%b:tensor<2x3xf32>
          return %x,%y:tensor<2x3xf32>,tensor<2x3xf32>}}'''
        c = self.compile(source)
        a=np.arange(6,dtype=np.float32).reshape(2,3);b=a+2
        status,out=c.run(a,b)
        self.assertEqual(status,0)
        np.testing.assert_array_equal(out[0],a+b)
        np.testing.assert_array_equal(out[1],a*b)
        (c.path/'input.mlir').write_text(source)
        script = '''import importlib.abc, sys
class NoJax(importlib.abc.MetaPathFinder):
 def find_spec(self,name,path=None,target=None):
  if name=='jax' or name.startswith('jax.'): raise ImportError('JAX is forbidden')
sys.meta_path.insert(0,NoJax())
from tools.program import compile_stablehlo
from pathlib import Path
compile_stablehlo(Path(sys.argv[1]),Path(sys.argv[2]))
assert 'jax' not in sys.modules
'''
        subprocess.run([sys.executable,'-c',script,str(c.path/'input.mlir'),str(c.path/'independent.h')],
                       cwd=ROOT,check=True,capture_output=True)

    def test_multiple_inputs_outputs_shapes_and_reduction(self):
        x=np.arange(24,dtype=np.float32).reshape(2,3,4)/8
        b=np.array([1,-2,3,4],np.float32)
        self.check(lambda x,b:(jnp.sum(x+b,axis=(0,2)),jnp.transpose(x,(2,0,1)),x[:,1:,:2]),[x,b])

    def test_tpu_dynamic_weights_exact_and_backend_errors(self):
        rng=np.random.default_rng(11)
        a=rng.integers(-128,128,(5,9),dtype=np.int8)
        b=rng.integers(-128,128,(9,7),dtype=np.int8)
        def f(a,b):
            return jax.lax.dot_general(a,b,(((1,),(0,)),((),())),preferred_element_type=jnp.int32)
        for target in (KC705,KC705_ROCKET):
            c=self.check(f,[a,b],CompileOptions(target=target))
            self.assertGreater(c.library.backend_calls(),0)
            self.assertEqual([p['device'] for p in c.report['placement'] if p['op']=='matmul'],['tpu'])
            for mode in (1,2):
                status,output=c.run(a,b,mode=mode)
                self.assertEqual(status,-5)
                np.testing.assert_array_equal(output[0],17)
        cpu=self.check(f,[a,b])
        self.assertEqual(cpu.library.backend_calls(),0)

    def test_float_matmul_stays_float(self):
        a=np.arange(15,dtype=np.float32).reshape(3,5)/10
        b=np.arange(20,dtype=np.float32).reshape(5,4)/7
        c=self.check(lambda x,y:x@y,[a,b],CompileOptions(target=KC705))
        self.assertEqual(c.library.backend_calls(),0)

    def test_wrapping_integer_math(self):
        a=np.array([2147483647,-2147483648,65536,-2147483647],np.int32)
        self.check(lambda x:(x+1,x*x,-x,jnp.abs(x),jnp.sum(x)),[a])
        u=np.array([0,4294967295,2147483648],np.uint32)
        self.check(lambda x:(x+1,x*x,-x),[u])

    def test_integer_conversion_and_predicate(self):
        x=np.array([-np.inf,-2147483648.,-129.,0.,128.,2147483648.,np.inf,np.nan],np.float32)
        self.check(lambda x:(x.astype(jnp.int32),x.astype(jnp.int8),x.astype(jnp.bool_)),[x])

    def test_ieee_math_and_signed_zero(self):
        x=np.array([0.,-0.,1.,-1.,np.inf,-np.inf,np.nan],np.float32)
        y=np.array([-0.,0.,-1.,1.,np.inf,-np.inf,2.],np.float32)
        c=self.check(lambda x,y:(jnp.minimum(x,y),jnp.maximum(x,y),jnp.sign(x),jnp.atan2(x,y)),[x,y])
        _,out=c.run(x,y)
        self.assertTrue(np.signbit(out[0][0]))
        self.assertFalse(np.signbit(out[1][0]))

    def test_freestanding_math_requires_explicit_policy(self):
        x=np.array([0.,1e-30,0.3,1.,12.,1e30],np.float32)
        source=export_function(lambda x:jnp.sqrt(x),x)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ProgramError,'no libm'):
                compile_stablehlo(source,Path(d)/'bad.h',CompileOptions(target=KC705))
            with self.assertRaisesRegex(ProgramError,'allow_approximation'):
                compile_stablehlo(source,Path(d)/'bad.h',CompileOptions(target=KC705,math_mode='freestanding'))
        opts=CompileOptions(target=KC705,math_mode='freestanding',allow_approximation=True)
        self.check(lambda x:jnp.sqrt(x),[x],opts)
        z=np.array([-1.,-.9999,-.2,0.,.1,.9999,1.],np.float32)
        self.check(lambda x:jnp.acos(x),[z],opts,atol=5e-7)

    def test_static_loop_and_calls(self):
        x=np.arange(12,dtype=np.float32).reshape(3,4)/8
        @jax.jit
        def inner(x):return x*1.25+0.125
        c=self.check(lambda x:jax.lax.fori_loop(0,4,lambda _,v:inner(v),x),[x])
        self.assertEqual(c.report['program']['static_loops_inlined'],1)

    def test_runtime_loop_zero_iterations_and_nested_carries(self):
        x=np.arange(12,dtype=np.float32).reshape(3,4)/8
        def f(x,n):
            def outer(i,s):
                return jax.lax.fori_loop(0,n,lambda j,v:v*.5+(i+j).astype(jnp.float32),s)
            return jax.lax.fori_loop(0,n,outer,x),n+1
        c=self.compile(export_function(f,x,np.int32(3)))
        self.assertTrue(c.report['regions'])
        for n in (0,1,3,5):
            status,actual=c.run(x,np.int32(n))
            self.assertEqual(status,0)
            for got,want in zip(actual,jax.tree.leaves(f(x,np.int32(n)))):
                np.testing.assert_array_equal(got,want)

    def test_runtime_loop_with_tpu_failure_is_atomic(self):
        x=np.arange(12,dtype=np.float32).reshape(3,4)
        w=jnp.eye(4,dtype=jnp.int8)
        def f(x,n):
            def body(_,v):
                y=jax.lax.dot_general(v.astype(jnp.int8),w,(((1,),(0,)),((),())),preferred_element_type=jnp.int32)
                return y.astype(jnp.float32)+1
            return jax.lax.fori_loop(0,n,body,x)
        c=self.compile(export_function(f,x,np.int32(3)),CompileOptions(target=KC705))
        for n in (0,1,3):
            status,out=c.run(x,np.int32(n));self.assertEqual(status,0)
            np.testing.assert_array_equal(out[0],x+n)
        status,out=c.run(x,np.int32(3),mode=2)
        self.assertEqual(status,-5);np.testing.assert_array_equal(out[0],17)
        self.assertEqual(c.run(x,np.int32(0),mode=1)[0],0)

    def test_runtime_loop_parallel_tuple_update_and_boolean_guard(self):
        a=np.array([1,2,3],np.int32);b=np.array([4,5,6],np.int32)
        def f(a,b,n):
            return jax.lax.while_loop(lambda s:(s[0]<n)&(n>=0),
                lambda s:(s[0]+1,s[2],s[1]),(jnp.int32(0),a,b))
        c=self.compile(export_function(f,a,b,np.int32(3)))
        for n in (-1,0,1,2,5):
            status,out=c.run(a,b,np.int32(n));self.assertEqual(status,0)
            for got,want in zip(out,jax.tree.leaves(f(a,b,np.int32(n)))):
                np.testing.assert_array_equal(got,want)

    def test_dynamic_gather_windows_nonleading_axes_and_batching(self):
        x=np.arange(2*4*3,dtype=np.float32).reshape(2,4,3)
        idx=np.array([[2,0,7,-1],[1,1,-8,3]],np.int32)
        self.check(lambda x,i:jax.vmap(lambda a,b:a[b])(x,i),[x,idx])
        self.check(lambda x,i:x[:,i,:],[x,np.array([2,0,3],np.int32)])
        dn=jax.lax.GatherDimensionNumbers(offset_dims=(1,2),collapsed_slice_dims=(),start_index_map=(0,1))
        a=np.arange(20,dtype=np.float32).reshape(5,4);indices=np.array([[4,3],[-9,0],[1,2]],np.int32)
        self.check(lambda a,i:jax.lax.gather(a,i,dn,(2,2)),[a,indices])

    def test_dynamic_scatter_updates_and_duplicates(self):
        x=np.arange(20,dtype=np.float32).reshape(5,4)
        i=np.array([2,2,-1,9,-8],np.int32)
        updates=np.arange(20,dtype=np.float32).reshape(5,4)/3
        self.check(lambda x,i,u:(x.at[i].add(u),x.at[i].max(u),x.at[i].multiply(u)),[x,i,updates])
        y=np.arange(24,dtype=np.float32).reshape(2,4,3);idx=np.array([[1,1],[3,0]],np.int32)
        self.check(lambda x,i:jax.vmap(lambda a,b:a.at[b].add(jnp.ones((2,3))))(x,i),[y,idx])
        self.check(lambda x,i:x.at[:,i].set(jnp.full((5,2),-4.)),[x,np.array([1,3],np.int32)])

    def test_reductions_general_initializers(self):
        x=np.arange(12,dtype=np.float32).reshape(3,4)/8-1
        self.check(lambda x:(jnp.min(x,axis=0),jnp.max(x,axis=1),jnp.prod(x,axis=0)),[x])
        self.check(lambda x,z:jax.lax.reduce(x,z,jax.lax.add,(1,)),[x,np.float32(2)])
        mask=np.array([[True,False],[False,False]],np.bool_)
        self.check(lambda x:(jnp.any(x,axis=0),jnp.all(x,axis=1)),[mask])

    def test_general_dot_batch_and_multiple_contracting_axes(self):
        rng=np.random.default_rng(53)
        a=rng.integers(-9,10,(2,3,4),dtype=np.int8)
        b=rng.integers(-9,10,(2,4,5),dtype=np.int8)
        def f(a,b):return jax.lax.dot_general(a,b,(((2,),(1,)),((0,),(0,))),preferred_element_type=jnp.int32)
        c=self.check(f,[a,b],CompileOptions(target=KC705))
        self.assertEqual(c.library.backend_calls(),2)
        a=rng.normal(size=(3,2,4)).astype(np.float32);b=rng.normal(size=(4,5,2)).astype(np.float32)
        self.check(lambda a,b:jax.lax.dot_general(a,b,(((1,2),(2,0)),((),()))),[a,b])
        self.check(lambda x,y:jnp.dot(x,y),[np.arange(4,dtype=np.float32),np.arange(4,dtype=np.float32)])

    def test_freestanding_trig_full_float_range(self):
        rng=np.random.default_rng(54)
        bits=rng.integers(0,2**32,4096,dtype=np.uint32)
        x=bits.view(np.float32);x=x[np.isfinite(x)]
        x=np.concatenate([x,np.array([0.,-0.,1e-30,1e30,np.finfo(np.float32).max,np.inf,-np.inf,np.nan],np.float32)])
        opts=CompileOptions(target=KC705,math_mode='freestanding',allow_approximation=True)
        c=self.compile(export_function(lambda x:(jnp.sin(x),jnp.cos(x)),x),opts)
        status,out=c.run(x);self.assertEqual(status,0)
        with np.errstate(invalid='ignore'):
            for got,fn in zip(out,(np.sin,np.cos)):
                np.testing.assert_allclose(got,fn(x.astype(np.float64)).astype(np.float32),atol=1.5e-7,rtol=1e-7)
        self.assertTrue(np.signbit(out[0][-7]))

    def test_gather_clamping_and_scatter_duplicates(self):
        x=np.arange(15,dtype=np.float32).reshape(5,3)
        idx=jnp.array([0,1,1,4,9],jnp.int32)
        self.check(lambda x:(x[jnp.array([4,-1,7])],x.at[idx].add(jnp.ones((5,3)))),[x])

    def test_affine_is_opt_in_and_checks_range(self):
        def f(x,y):return (x-y)*2+(x+y)*3-x*4+y*2
        x=np.arange(48,dtype=np.float32).reshape(16,3)/32
        y=x/2-1
        source=export_function(f,x,y)
        plain=self.check(f,[x,y],CompileOptions(target=KC705))
        self.assertEqual(plain.report['partitions'],[])
        opts=CompileOptions(target=KC705,allow_approximation=True,affine_offload=True,affine_policy='force')
        c=self.check(f,[x,y],opts,atol=1e-5)
        self.assertGreater(len(c.report['partitions']),0)
        self.assertGreater(c.library.backend_calls(),0)
        self.assertEqual(c.run(x+100,y)[0],-4)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(ProgramError,'allow_approximation'):
                compile_stablehlo(source,Path(d)/'out.h',replace(opts,allow_approximation=False))

    def test_generic_fusion_preserves_bits_and_exposed_intermediates(self):
        x=np.array([0.,-0.,1e20,-1e20,1.,1e-20,-2.,3.],np.float32)
        y=np.array([-0.,0.,1.,1.,1e-7,-1e-20,4.,-5.],np.float32)
        def f(x,y):
            t=x-y
            a=(t*t+1)*.25
            b=jnp.where(a>2,a-1,-a)
            return t,b,jnp.sum(b),jnp.stack((b,b+1))
        source=export_function(f,x,y)
        plain=self.compile(source,CompileOptions(fusion=False))
        fused=self.compile(source)
        self.assertGreater(fused.report['fusion']['eliminated_arrays'],0)
        self.assertLess(fused.report['workspace_bytes'],plain.report['workspace_bytes'])
        for a,b in zip(plain.run(x,y)[1],fused.run(x,y)[1]):
            np.testing.assert_array_equal(a.view(np.uint32),b.view(np.uint32))

    def test_fusion_mixed_integer_types_broadcast_and_wrapping(self):
        x=np.array([-2147483648,2147483647,65536,129],np.int32)
        y=np.arange(12,dtype=np.int32).reshape(3,4)
        def f(x,y):
            z=((x+y)*3-7).astype(jnp.int8)
            return jnp.where(z<0,-z,z)+jnp.int8(127),z.astype(jnp.float32)*.25
        source=export_function(f,x,y)
        plain=self.compile(source,CompileOptions(fusion=False));fused=self.check(f,[x,y])
        for a,b in zip(plain.run(x,y)[1],fused.run(x,y)[1]):np.testing.assert_array_equal(a,b)

    def test_composed_index_maps_and_runtime_loop_fusion(self):
        x=np.arange(48,dtype=np.float32).reshape(4,3,4)/32
        def f(x,n):
            y=x.transpose(2,0,1).reshape(4,12)[:,1:10:2]
            return jax.lax.fori_loop(0,n,lambda _,v:(v*.5+.25)*2-.5,y)
        source=export_function(f,x,np.int32(2))
        plain=self.compile(source,CompileOptions(fusion=False));fused=self.check(f,[x,np.int32(2)])
        self.assertGreater(fused.report['composed_index_maps'],0)
        for n in (0,2,7):
            np.testing.assert_array_equal(plain.run(x,np.int32(n))[1][0].view(np.uint32),
                                          fused.run(x,np.int32(n))[1][0].view(np.uint32))

    def test_affine_cost_placement_is_target_specific_not_workload_specific(self):
        def f(x,y):return (x-y)*2+(x+y)*3-x*4+y*2
        x=np.arange(48,dtype=np.float32).reshape(16,3)/32;y=x/2-1
        opts=CompileOptions(target=KC705,allow_approximation=True,affine_offload=True)
        cpu=self.check(f,[x,y],opts)
        self.assertEqual(cpu.library.backend_calls(),0)
        self.assertFalse(cpu.report['affine_placement_decisions'][0]['selected'])
        fast=replace(KC705,affine_cost_model=AffineCostModel(register_cycles=1,
                     pack_input_cycles=1,unpack_output_cycles=1))
        accelerated=self.check(f,[x,y],replace(opts,target=fast),atol=1e-5)
        self.assertGreater(accelerated.library.backend_calls(),0)
        self.assertTrue(accelerated.report['affine_placement_decisions'][0]['selected'])
        unknown=self.check(f,[x,y],replace(opts,target=replace(KC705,affine_cost_model=None)))
        self.assertEqual(unknown.library.backend_calls(),0)
        self.assertEqual(unknown.report['affine_placement_decisions'][0]['reason'],'no target cost model')
        def dense(x,y):
            for _ in range(100):x=x+y
            return x
        profitable=self.check(dense,[x,y],opts,atol=1e-5)
        self.assertGreater(profitable.library.backend_calls(),0)
        self.assertTrue(profitable.report['affine_placement_decisions'][0]['selected'])
        with self.assertRaisesRegex(ValueError,'nonnegative'):AffineCostModel(register_cycles=-1)

    def test_affine_cost_does_not_count_shared_nodes_as_savings(self):
        from tools.program._schedule import ExecutionPlan
        from tools.program.partition import partition_affine
        def plan(expose):
            p=ExecutionPlan();x=p.value((32,3),np.float32);y=p.value((32,3),np.float32);p.inputs=[x,y]
            v=x;values=[]
            for i in range(10):
                v=p.operation('add',[v,y],(32,3),np.float32);values.append(v)
            p.outputs=values if expose else [v]
            decisions=[]
            partition_affine(p,cost_model=AffineCostModel(),decisions=decisions)
            return decisions[0]['estimate']['cpu_cycles']
        self.assertLess(plan(True),plan(False))

    def test_identity_constant_output_and_dead_values(self):
        x=np.arange(6,dtype=np.float32).reshape(2,3)
        self.check(lambda x:(x.reshape(3,2),jnp.array([2,3],jnp.int32),x+1),[x])

    def test_no_inputs_nonfinite_constants_and_namespaced_headers(self):
        source=export_function(lambda:jnp.array([np.nan,np.inf,-np.inf,-0.],jnp.float32))
        c=self.compile(source)
        status,out=c.run()
        self.assertEqual(status,0)
        np.testing.assert_array_equal(out[0],np.array([np.nan,np.inf,-np.inf,-0.],np.float32))
        self.assertTrue(np.signbit(out[0][-1]))
        compile_stablehlo(source,c.path/'second.h',CompileOptions(symbol='second'))
        (c.path/'both.c').write_text('#include "program.h"\n#include "second.h"\nint main(void){return 0;}\n')
        subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-I'+str(ROOT/'include'),
                        '-c',str(c.path/'both.c'),'-o',str(c.path/'both.o')],check=True,capture_output=True)

    def test_cli_and_malformed_input(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)
            source=export_function(lambda x:x*2,np.ones(3,np.float32))
            (path/'input.mlirbc').write_bytes(source)
            subprocess.run([sys.executable,'-m','tools.program',str(path/'input.mlirbc'),
                            '-o',str(path/'out.h'),'--report',str(path/'report.json')],
                           cwd=ROOT,check=True,capture_output=True)
            self.assertEqual(json.loads((path/'report.json').read_text())['input_format'],'StableHLO')
            with self.assertRaisesRegex(ProgramError,'parsing/lowering failed'):
                compile_stablehlo('invalid mlir',path/'bad.h')
            self.assertFalse((path/'bad.h').exists())

    def test_failures_are_diagnostic_and_write_no_artifact(self):
        x=np.ones(4,np.float32)
        cases=[(lambda x:jnp.exp(x),(x,),'stablehlo.exponential'),
               (lambda x:jax.lax.cond(jnp.sum(x)>0,lambda y:y+1,lambda y:y-1,x),(x,),'stablehlo.case')]
        with tempfile.TemporaryDirectory() as d:
            output=Path(d)/'rejected.h'
            for f,inputs,message in cases:
                with self.assertRaisesRegex(ProgramError,message):
                    compile_stablehlo(export_function(f,*inputs),output)
                self.assertFalse(output.exists())
            with self.assertRaisesRegex(ProgramError,'workspace requires'):
                compile_stablehlo(export_function(lambda x:x+1,x),output,
                                 CompileOptions(target=replace(CPU,workspace_limit_bytes=1)))
            self.assertFalse(output.exists())
            with self.assertRaisesRegex(ProgramError,'no backend implementation'):
                compile_stablehlo(export_function(lambda x:x+1,x),output,
                                 CompileOptions(target=Target('empty',cpu_ops=frozenset())))
            self.assertFalse(output.exists())


if __name__=='__main__':
    unittest.main()
