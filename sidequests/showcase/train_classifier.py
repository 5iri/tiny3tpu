#!/usr/bin/env python3
"""Train and quantize a small MNIST classifier; export generic StableHLO."""
import json,hashlib,sys
from dataclasses import replace
from pathlib import Path
import numpy as np
import jax,jax.numpy as jnp
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.jax_stablehlo import export_function
from tools.program import compile_stablehlo,CompileOptions,KC705
from test_stablehlo_compiler import Compiled
out=ROOT/'build-classifier';out.mkdir(exist_ok=True)
def main():
 data=np.load(out/'mnist.npz');x=data['x_train'].reshape(-1,784).astype(np.float32)/255;y=data['y_train'];xt=data['x_test'].reshape(-1,784).astype(np.float32)/255;yt=data['y_test'];rng=np.random.default_rng(705)
 params=(jnp.zeros((784,10),jnp.float32),jnp.zeros(10,jnp.float32));mom=jax.tree.map(jnp.zeros_like,params);vel=mom
 def loss(p,a,b):return -jnp.mean(jax.nn.log_softmax(a@p[0]+p[1])[jnp.arange(a.shape[0]),b])
 @jax.jit
 def update(p,m,v,a,b,t):
  grad=jax.grad(loss)(p,a,b);m=jax.tree.map(lambda u,g:.9*u+.1*g,m,grad);v=jax.tree.map(lambda u,g:.999*u+.001*g*g,v,grad)
  p=jax.tree.map(lambda w,u,z:w-.003*(u/(1-.9**t))/(jnp.sqrt(z/(1-.999**t))+1e-8),p,m,v);return p,m,v
 t=0
 for epoch in range(10):
  order=rng.permutation(len(x))
  for begin in range(0,len(x)-256,256):
   idx=order[begin:begin+256];t+=1;params,mom,vel=update(params,mom,vel,x[idx],y[idx],jnp.float32(t))
  accuracy=float(np.mean(np.argmax(np.asarray(jnp.asarray(xt)@params[0]+params[1]),axis=1)==yt));print('epoch',epoch+1,'test_accuracy',accuracy,flush=True)
 w,b=map(np.asarray,params);scale=np.float32(127/np.max(np.abs(w)));qw=np.rint(w*scale).astype(np.int8);qb=np.rint(b*127*scale).astype(np.int32);qx=np.rint(xt*127).astype(np.int8)
 logits=qx.astype(np.int32)@qw.astype(np.int32)+qb;qa=float(np.mean(np.argmax(logits,axis=1)==yt))
 np.savez(out/'trained.npz',weights=w,bias=b,qweights=qw,qbias=qb,weight_scale=scale)
 def classifier(a):
  z=jax.lax.dot_general(a,jnp.array(qw),(((1,),(0,)),((),())),preferred_element_type=jnp.int32)+jnp.array(qb)
  return z.astype(jnp.float32)/jnp.float32(127*scale)
 artifact=export_function(classifier,qx[:1],output=out/'classifier.mlirbc');opts=CompileOptions(target=KC705,symbol='classifier',math_mode='freestanding',allow_approximation=True)
 report=compile_stablehlo(artifact,out/'classifier.h',opts);(out/'compile-report.json').write_text(json.dumps(report,indent=2))
 native=Compiled(artifact,replace(opts,symbol="t3p"));expected=[]
 for i in range(20):
  status,outputs=native.run(qx[i:i+1]);assert status==0;np.testing.assert_allclose(outputs[0],np.asarray(classifier(qx[i:i+1])),rtol=1e-6,atol=1e-6);expected.append(outputs[0].ravel())
 native.close();np.save(out/'expected.npy',expected);np.savez(out/'samples.npz',inputs=qx[:20],images=data['x_test'][:20],labels=yt[:20])
 fixture='static const int8_t digit_inputs[20][784]={'+','.join('{'+','.join(map(str,row))+'}' for row in qx[:20])+'};\n';(out/'digits.h').write_text(fixture)
 evidence={'dataset':'MNIST','dataset_sha256':hashlib.sha256((out/'mnist.npz').read_bytes()).hexdigest(),'seed':705,'architecture':'784 -> 10 linear logits','train_examples':60000,'test_examples':10000,'epochs':10,'float32_test_accuracy':accuracy,'int8_test_accuracy':qa,'test_split_used_for_training':False,'quantization':'global symmetric int8 weights, nonnegative int8 pixels, int32 bias/accumulation','demo_samples':'first 20 test examples, no cherry-picking','weights_sha256':hashlib.sha256((out/'trained.npz').read_bytes()).hexdigest()};(out/'training-report.json').write_text(json.dumps(evidence,indent=2));print(json.dumps(evidence),flush=True)
if __name__=='__main__':main()
