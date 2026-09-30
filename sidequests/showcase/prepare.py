#!/usr/bin/env python3
"""Export unrelated tensor programs through the same StableHLO backend."""
import argparse,json,sys
from pathlib import Path
import numpy as np
import jax,jax.numpy as jnp
ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.jax_stablehlo import export_function
from tools.program import compile_stablehlo,CompileOptions,KC705
from test_stablehlo_compiler import Compiled

def workloads():
 rng=np.random.default_rng(705)
 w1=jnp.array(rng.integers(-3,4,(8,12)),jnp.int8);w2=jnp.array(rng.integers(-3,4,(12,5)),jnp.int8)
 def dot(a,b):return jax.lax.dot_general(a,b,(((1,),(0,)),((),())),preferred_element_type=jnp.int32)
 def mlp(x):
  hidden=jnp.clip(dot(x.astype(jnp.int8),w1),0,127).astype(jnp.int8)
  return dot(hidden,w2).astype(jnp.float32)
 # A synthetic, single-head attention block. Matmuls are explicit int8;
 # normalization, stable softmax and requantization remain CPU operations.
 wq=jnp.array(rng.integers(-2,3,(8,8)),jnp.int8)
 wk=jnp.array(rng.integers(-2,3,(8,8)),jnp.int8)
 wv=jnp.array(rng.integers(-2,3,(8,8)),jnp.int8)
 wo=jnp.array(rng.integers(-2,3,(8,8)),jnp.int8)
 def attention(x):
  centered=x-jnp.mean(x,axis=-1,keepdims=True)
  normalized=centered/jnp.sqrt(jnp.mean(centered*centered,axis=-1,keepdims=True)+jnp.float32(.00001))
  a=jnp.clip(normalized*8,-127,127).astype(jnp.int8)
  q=jnp.clip(dot(a,wq),-127,127).astype(jnp.int8)
  k=jnp.clip(dot(a,wk),-127,127).astype(jnp.int8)
  v=jnp.clip(dot(a,wv),-127,127).astype(jnp.int8)
  scores=dot(q,k.T).astype(jnp.float32)/jnp.float32(256)
  scores=jnp.where(jnp.arange(8)[:,None]>=jnp.arange(8)[None,:],scores,jnp.float32(-10000))
  weights=jax.nn.softmax(scores,axis=-1)
  encoded=jnp.clip(weights*127,0,127).astype(jnp.int8)
  mixed=jnp.clip(dot(encoded,v)/jnp.float32(127),-127,127).astype(jnp.int8)
  return dot(mixed,wo).astype(jnp.float32)/jnp.float32(8)+x
 mesh=np.load(ROOT/'build-banana/render/mesh.npz')
 banana_report=json.loads((ROOT/'build-banana/render/report.json').read_text())
 vertex_scale=banana_report['vertex_scale'];qscale=vertex_scale*127
 vertices=jnp.array(np.rint(mesh['vertices']*vertex_scale),jnp.int8)
 def banana(x):
  angle=x[0]+jnp.float32(.06)
  angle=jnp.where(angle>jnp.float32(2*np.pi),angle-jnp.float32(2*np.pi),angle)
  c=jnp.cos(angle);s=jnp.sin(angle)
  matrix=jnp.stack([jnp.stack([c,s*.5,-s*.8660254]),jnp.array([0.,.8660254,.5]),jnp.stack([s,-c*.5,c*.8660254])])*127
  weights=jnp.where(matrix<0,matrix-.5,matrix+.5).astype(jnp.int8)
  coordinates=dot(vertices,weights)+jnp.array([0,0,round(2*qscale)],jnp.int32)
  return jnp.concatenate((angle[None],coordinates.astype(jnp.float32).reshape(-1)))
 return [('quantized_mlp',mlp,rng.integers(-8,9,(4,8)).astype(np.float32),'Two synthetic dense layers with ReLU; exact int8 TPU matrix products.'),
         ('attention_block',attention,rng.integers(-8,9,(8,8)).astype(np.float32),'Synthetic causal attention: six int8 matrix products, CPU normalization and stable softmax. Not a pretrained language model.'),
         ('banana',banana,np.zeros(1,np.float32),'Resident banana rotation and camera transform; angle and coordinates calculated on board, host pixels only.')]

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,default=ROOT/'build-showcase');a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 records=[]
 for index,(name,fn,data,description) in enumerate(workloads()):
  d=out/name;d.mkdir(exist_ok=True);artifact=export_function(fn,data,output=d/'program.mlirbc');np.save(d/'input.npy',data)
  options=CompileOptions(target=KC705,math_mode='freestanding',allow_approximation=True,affine_offload=False)
  native=Compiled(artifact,options)
  try:
   status,outputs=native.run(data);assert status==0;expected=np.asarray(jax.jit(fn)(data));np.testing.assert_allclose(outputs[0],expected,rtol=5e-6,atol=5e-6)
   np.save(d/'expected-native.npy',outputs[0]);np.save(d/'expected-jax.npy',expected)
   report=compile_stablehlo(artifact,d/(name+'.h'),CompileOptions(target=KC705,symbol=name,math_mode='freestanding',allow_approximation=True,affine_offload=False))
   (d/'compile-report.json').write_text(json.dumps(report,indent=2)+'\n')
   record=dict(id=index,name=name,description=description,input_shape=list(data.shape),output_shape=list(outputs[0].shape),workspace_bytes=report['workspace_bytes'],native_backend_calls=native.library.backend_calls(),jax_max_abs_error=float(np.max(np.abs(outputs[0]-expected))),native_passed=True)
   records.append(record);print(json.dumps(record),flush=True)
  finally:native.close()
 (out/'manifest.json').write_text(json.dumps(records,indent=2)+'\n')
if __name__=='__main__':main()
