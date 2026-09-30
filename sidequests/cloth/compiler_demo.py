#!/usr/bin/env python3
"""Record JAX JIT, full-graph rejection, and compiler/RTL force-island execution."""
import sys,json,time,subprocess
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),sys.argv[1]]
import jax,jax.numpy as jnp
from model import Cloth
from tools.jax_export import export_function,ExportError
from tools.jax_affine_lowering import split_signed16
out=ROOT/'build-cloth/compiler-demo';out.mkdir(exist_ok=True)
c=Cloth(6,3)
initial=jnp.concatenate(c.initial,axis=1)
def step(state):return jnp.concatenate(c.advance((state[:,:3],state[:,3:]),1),axis=1)
start=time.perf_counter();lowered=jax.jit(step).lower(initial);executable=lowered.compile();compile_ms=(time.perf_counter()-start)*1000
(out/'cloth_step.stablehlo.mlir').write_text(str(lowered.compiler_ir(dialect='stablehlo')))
start=time.perf_counter();result=executable(initial);result.block_until_ready();first_ms=(time.perf_counter()-start)*1000
start=time.perf_counter()
for _ in range(30):executable(initial).block_until_ready()
warm_ms=(time.perf_counter()-start)*1000/30
primitives=set()
def walk(jp):
 if hasattr(jp,'jaxpr'):jp=jp.jaxpr
 if not hasattr(jp,'eqns'):return
 for e in jp.eqns:
  primitives.add(e.primitive.name)
  for v in e.params.values():
   if isinstance(v,(list,tuple)):
    for x in v:walk(x)
   else:walk(v)
walk(jax.make_jaxpr(step)(initial))
try:export_function(step,initial,out/'full_cloth.json')
except ExportError as exc:full={'status':'unsupported','reason':str(exc)}
else:raise AssertionError('full float cloth unexpectedly accepted')
records=[];rng=np.random.default_rng(42)
for group in range(2):
 model=ROOT/f'build-cloth/force_group{group}.json';binary=out/f'force_group{group}.t3m'
 compiled=subprocess.run([str(ROOT/'build-cloth/compiler/tiny3tpu-compile'),str(model),'-o',str(binary)],capture_output=True,text=True,check=True)
 (out/f'compile_group{group}.log').write_text(compiled.stdout+compiled.stderr)
 graph=json.loads(model.read_text());w=np.array(graph['tensors'][1]['data'],np.int32).reshape(2,2).T
 wide=rng.integers(-32640,32640,(54,2),dtype=np.int32);lo,hi=split_signed16(wide);inputs=np.concatenate([lo,hi])
 expected=inputs.astype(np.int32)@w
 runs={}
 for backend,path in [('C_runtime',ROOT/'build-cloth/compiler/tiny3tpu-run'),('TPU_RTL',ROOT/'build-banana/axis-rtl/obj/Vsynapse32_tpu_peripheral')]:
  start=time.perf_counter();r=subprocess.run([str(path),str(binary),*map(str,inputs.ravel())],capture_output=True,text=True,check=True);elapsed=(time.perf_counter()-start)*1000
  (out/f'{backend}_group{group}.log').write_text(r.stdout+r.stderr)
  actual=np.array([int(x) for x in r.stdout.split()],np.int32).reshape(108,2)
  assert np.array_equal(actual,expected),(backend,group)
  reconstructed=actual[:54]+256*actual[54:]
  assert np.array_equal(reconstructed,wide@w)
  runs[backend]={'exact_match':True,'outputs':int(actual.size),'execution_wall_ms':elapsed}
 reference=jax.jit(lambda x:jnp.asarray(x,jnp.int32)@jnp.asarray(w,jnp.int32))(jnp.asarray(wide));reference.block_until_ready()
 assert np.array_equal(reference,wide@w)
 records.append({'group':group,'artifact':str(binary),'model_bytes':binary.stat().st_size,'weights':w.tolist(),'JAX_wide_reference_match':True,'runs':runs})
report={'full_JAX_JIT':{'backend':jax.default_backend(),'compile_ms':compile_ms,'first_execution_ms':first_ms,'warm_execution_ms':warm_ms,'finite':bool(np.isfinite(result).all()),'primitives':sorted(primitives)},'full_tiny3tpu_export':full,'compiled_force_islands':records,'scope':'JAX JIT timings are host CPU. TPU execution is actual accelerator RTL simulation, not physical KC705 or full-cloth TPU execution.'}
(out/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
