#!/usr/bin/env python3
"""Check MJX physics, compiled learning, and optionally the full CPU/TPU/HDMI RTL."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import jax
import jax.numpy as jnp
import mujoco
import numpy as np
from workload import make_physics,make_tick,make_learner,initial_tick_state

ROOT=Path(__file__).resolve().parents[2]
HDMI=ROOT/'hardware/kc705_hdmi'
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(HDMI/'tests')]
from tools.program import CompileOptions,KC705_DIRECT
from tools.jax_stablehlo import export_function
from test_stablehlo_compiler import Compiled


def check_rtl(out):
    sys.path.insert(0,str(Path(__file__).with_name('render')))
    from verify_rtl import check
    return check(out)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--rtl',action='store_true')
    args=p.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    options=CompileOptions(target=KC705_DIRECT,math_mode='freestanding',allow_approximation=True,gemm_policy='tpu')
    model,physics=make_physics()
    fn=lambda x:physics(x[:2],x[2])
    compiled=Compiled(export_function(fn,np.zeros(3,np.float32)),options)
    maximum=0.
    try:
        rng=np.random.default_rng(2026)
        for _ in range(64):
            x=(rng.uniform(-1,1,3)*[.5,2,2]).astype(np.float32)
            data=mujoco.MjData(model);data.qpos[:]=x[0];data.qvel[:]=x[1];data.ctrl[:]=x[2]
            mujoco.mj_step(model,data)
            status,got=compiled.run(x);assert status==0
            want=np.concatenate((data.qpos,data.qvel)).astype(np.float32)
            np.testing.assert_allclose(got[0],want,atol=2e-6,rtol=2e-6)
            maximum=max(maximum,float(np.max(np.abs(got[0]-want))))
    finally:compiled.close()
    tick=make_tick();artifact=export_function(tick,initial_tick_state(),output=out/'tick.mlirbc')
    compiled=Compiled(artifact,options)
    _,_,rollout,_,_=make_learner(horizon=512)
    score=jax.jit(jax.vmap(rollout,in_axes=(None,0)))
    angles=jnp.array([-.25,-.1,.1,.25],jnp.float32)
    before=np.asarray(score(jnp.zeros(2,jnp.float32),angles))
    results=[]
    try:
        for seed in (1,7,19):
            state=initial_tick_state(seed)
            for _ in range(102400):
                status,result=compiled.run(state);assert status==0
                state=result[0]
            after=np.asarray(score(state[:2],angles))
            assert state[3]==100 and np.all(np.isfinite(state))
            assert float(after.min())>.98 and float(after.mean()-before.mean())>.5
            results.append(dict(seed=seed,updates=100,physics_steps=102400,weights=state[:2].tolist(),held_out_returns=after.tolist()))
        assert compiled.library.backend_calls()==307200
    finally:compiled.close()
    report=dict(passed=True,scope='Native generated C training with software QGEMM oracle; held-out evaluation uses JAX/MJX. Not FPGA training timings.',
        algorithm='antithetic random-search policy optimization',task='upright balance; no swing-up or contact claim',
        physics_comparisons=64,max_one_step_error_vs_mujoco=maximum,
        evaluation_steps=512,evaluation_seconds=10.24,held_out_angles=np.asarray(angles).tolist(),
        initial_returns=before.tolist(),runs=results,
        sha256={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in [Path(__file__),Path(__file__).with_name('workload.py'),out/'tick.mlirbc']})
    (out/'learning.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='sha256'},indent=2),flush=True)
    if args.rtl:print(json.dumps(check_rtl(out/'rtl'),indent=2))


if __name__=='__main__':main()
