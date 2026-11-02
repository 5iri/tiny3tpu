#!/usr/bin/env python3
"""Exercise persistent renderer state and explicit unsupported-feature failure."""
import json,subprocess,sys
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).with_name('render')))
import export_scene
from build import flags,sources

RUNNER=r'''
#include <stdio.h>
#include <stdlib.h>
#include "renderer.h"
#include "port.h"
static uint16_t pixels[320*240];
_Noreturn void port_fail(const char *message){fprintf(stderr,"%s\n",message);exit(7);}
extern void port_glEnable(unsigned);
int main(int argc,char **argv){
    mujoco_renderer_init(pixels,320,240);
    if(argc==1){port_glEnable(0x0b60);return 2;}
    FILE *f=fopen(argv[1],"rb");if(!f)return 3;
    float pose[12];size_t heap=mujoco_renderer_heap();
    while(fread(pose,sizeof(float),12,f)==12){
        mujoco_renderer_draw(pose);
        if(mujoco_renderer_heap()!=heap)return 4;
        if(fwrite(pixels,2,320*240,stdout)!=320*240)return 5;
    }
    fclose(f);fprintf(stderr,"heap=%zu\n",heap);return 0;
}
'''

def check(out):
    out.mkdir(parents=True,exist_ok=True);export_scene.export(out)
    runner=out/'runner.c';runner.write_text(RUNNER)
    exe=out/'renderer-contract'
    command=['clang','-DRENDER_HEAP_BYTES=2097152',*flags(out),*map(str,sources(out)),str(runner),('-Wl,-dead_strip' if sys.platform=='darwin' else '-Wl,--gc-sections'),'-lm','-o',str(exe)]
    result=subprocess.run(command,capture_output=True,text=True)
    (out/'compile.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,(result.stdout+result.stderr)[-2000:]
    angles=[-.6,0.,.25,.65]*16
    poses=[]
    for q in angles:
        _,d,_=export_scene.scene_at(q)
        poses.append(np.concatenate((d.geom_xpos,d.geom_xmat),axis=1).ravel())
    np.asarray(poses,np.float32).tofile(out/'poses.bin')
    result=subprocess.run([str(exe),str(out/'poses.bin')],capture_output=True,check=True)
    images=np.frombuffer(result.stdout,np.uint16).reshape(64,240,320)
    for i in range(4,64):np.testing.assert_array_equal(images[i],images[i%4])
    assert all(np.any(images[0]!=images[i]) for i in (1,2,3))
    invalid=subprocess.run([str(exe)],capture_output=True)
    assert invalid.returncode==7 and b'unsupported enabled GL capability' in invalid.stderr
    original=export_scene.scene_at
    def invalid_scene():
        m,d,s=original();s.geoms[0].type=export_scene.mujoco.mjtGeom.mjGEOM_MESH
        return m,d,s
    export_scene.scene_at=invalid_scene
    try:
        try:export_scene.export(out/'rejected')
        except ValueError:pass
        else:raise AssertionError('Unsupported scene was accepted')
    finally:export_scene.scene_at=original
    report=dict(passed=True,persistent_frames=64,repeat_images_exact=True,arena_usage_constant=True,
        unsupported_fog_rejected=True,unsupported_mesh_rejected=True,arena=result.stderr.decode().strip())
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':check(Path(sys.argv[1]).resolve())
