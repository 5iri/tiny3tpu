#!/usr/bin/env python3
"""Export actual MJX learning ticks and build autonomous framebuffer firmware."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import jax
import mujoco
import numpy as np
from workload import make_tick, initial_tick_state, XML

ROOT=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from tools.jax_stablehlo import export_function
from tools.program import CompileOptions, KC705_DIRECT, compile_stablehlo
from test_stablehlo_compiler import Compiled
from sidequests.showcase.build_support import compile_firmware
sys.path.insert(0,str(Path(__file__).with_name("render")))
from build import riscv_objects
from export_scene import export as export_scene
from pose import make_pose


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out',type=Path,required=True)
    p.add_argument('--horizon',type=int,default=128)
    p.add_argument('--directions',type=int,default=4)
    p.add_argument('--seed',type=int,default=1)
    p.add_argument('--video-mode',choices=('vga','720p'),default='vga',help='720p uses a 480x270 MuJoCo image and 1280x720 scanout')
    p.add_argument('--verify-ticks',type=int,default=0,help='Bounded RTL fixture; zero builds the autonomous trainer')
    a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    hd=a.video_mode=='720p'
    width,height=(480,270) if hd else (320,240)
    display=(1280,720) if hd else (640,480)
    clock_hz=74250000 if hd else 25200000
    if a.verify_ticks<0 or a.verify_ticks>4096 or a.verify_ticks%8:p.error('--verify-ticks must be a multiple of 8, from 0 to 4096')
    state=initial_tick_state(a.seed,a.horizon,a.directions)
    np.save(out/'initial.npy',state);(out/'model.xml').write_text(XML)
    tick=make_tick();artifact=export_function(tick,state,output=out/'tick.mlirbc')
    options=CompileOptions(target=KC705_DIRECT,math_mode='freestanding',allow_approximation=True,gemm_policy='tpu')
    native=Compiled(artifact,options)
    expected=[]
    try:
        fn=jax.jit(tick);s=state.copy()
        # Same-state comparisons measure code generation, not chaotic drift.
        for i in range(max(16,a.verify_ticks)):
            want=np.asarray(fn(s));status,got=native.run(s);assert status==0
            np.testing.assert_allclose(got[0],want,rtol=3e-4,atol=3e-5)
            s=got[0];expected.append(s)
        assert native.library.backend_calls()==max(16,a.verify_ticks)
    finally:native.close()
    np.save(out/'native-states.npy',np.stack(expected))
    from dataclasses import replace
    report=compile_stablehlo(artifact,out/'mjx_tick.h',replace(options,symbol='mjx_tick'))
    (out/'compile-report.json').write_text(json.dumps(report,indent=2)+'\n')
    config=f'#define TINY3TPU_FB_WIDTH {width}U\n#define TINY3TPU_FB_HEIGHT {height}U\n#define DISPLAY_WIDTH {display[0]}U\n#define DISPLAY_HEIGHT {display[1]}U\n#define DISPLAY_CLOCK_HZ {clock_hz}U\n#define VERIFY_TICKS {a.verify_ticks}\n#define INITIAL_STATE {{'+','.join(float(v).hex()+'f' for v in state)+'}\n'
    if a.verify_ticks:
        config+=f'static const uint32_t expected_states[{a.verify_ticks}][20]={{\n'
        config+=',\n'.join('{'+','.join(str(int(v))+'U' for v in row.view(np.uint32))+'}' for row in expected[:a.verify_ticks])+'\n};\n'
    (out/'training_config.h').write_text(config)
    render_model,_,_=export_scene(out)
    pose_artifact=export_function(make_pose(),np.zeros(1,np.float32),output=out/'pose.mlirbc')
    pose_native=Compiled(pose_artifact,options)
    pose_error=0.
    try:
        for q in np.linspace(-np.pi,np.pi,65,dtype=np.float32):
            data=mujoco.MjData(render_model);data.qpos[0]=q;mujoco.mj_forward(render_model,data)
            expected_pose=np.concatenate((data.geom_xpos,data.geom_xmat),axis=1).ravel().astype(np.float32)
            status,result=pose_native.run(np.array([q],np.float32));assert status==0
            np.testing.assert_allclose(result[0],expected_pose,rtol=3e-5,atol=3e-5)
            pose_error=max(pose_error,float(np.abs(result[0]-expected_pose).max()))
        assert pose_native.library.backend_calls()==0
    finally:pose_native.close()
    pose_report=compile_stablehlo(pose_artifact,out/'mjx_pose.h',replace(options,symbol='mjx_pose'))
    pose_report.update(checked_poses=65,max_error_vs_native_mujoco=pose_error)
    (out/'pose-report.json').write_text(json.dumps(pose_report,indent=2)+'\n')
    objects=riscv_objects(out,heap_bytes=(640 if hd else 512)*1024)
    build=compile_firmware(Path(__file__).with_name('firmware.c'),[out,Path(__file__).with_name('render')],out,tpu_transport='direct',
        clock_hz=clock_hz,linker_script=Path(__file__).with_name('render')/('linker_720p.ld' if hd else 'linker.ld'),extra_objects=objects,libraries=['-lm','-lc'])
    build.update(workload='mjx-pendulum-random-search',framebuffer_abi='PFB1',framebuffer=[width,height],renderer="MuJoCo classic mjr_render + TinyGL",cpu_ram_bytes=build['memory']['ram_bytes'],
        pixel_format='RGB565',display=list(display),video_mode=a.video_mode,cores=2,array=[4,4],training=True,
        horizon=a.horizon,directions=a.directions,seed=a.seed,verify_ticks=a.verify_ticks,
        jax_version=jax.__version__,mujoco_version=mujoco.__version__,
        scope='Freestanding firmware; native tick checks passed; no physical execution claim')
    files=[Path(__file__),Path(__file__).with_name('workload.py'),ROOT/'include/tiny3tpu_framebuffer.h',
           ROOT/'sidequests/showcase/build_support.py',out/'mjx_tick.h',out/'tick.mlirbc',out/'training_config.h',
           out/'native-states.npy',out/'initial.npy',out/'model.xml']
    files += [f for folder in [Path(__file__).with_name('render'),ROOT/'third_party/mujoco_renderer',ROOT/'third_party/tinygl'] for f in folder.rglob('*') if f.is_file() and '__pycache__' not in f.parts]
    files += [out/'mjx_pose.h',out/'pose.mlirbc',out/'scene.h',out/'gl_dispatch.c']
    build['workload_sha256']={str(f):hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    (out/'build-manifest.json').write_text(json.dumps(build,indent=2)+'\n')
    print(json.dumps({'memory':build['memory'],'verify_ticks':a.verify_ticks,'workspace_bytes':report['workspace_bytes']},indent=2))


if __name__=='__main__':main()
