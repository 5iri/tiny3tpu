"""Specialize MuJoCo scene metadata; live poses remain runtime MJX outputs."""
from pathlib import Path
import sys,re
import mujoco
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from workload import XML
ROOT=Path(__file__).resolve().parents[3]

def scene_at(angle=0.):
    model=mujoco.MjModel.from_xml_string(XML)
    model.geom_rgba[0]=[.22,.6,.9,1]
    model.vis.headlight.ambient[:]=.25;model.vis.headlight.diffuse[:]=.8
    data=mujoco.MjData(model);data.qpos[0]=angle;mujoco.mj_forward(model,data)
    cam=mujoco.MjvCamera();cam.lookat[:]=[0,0,.4];cam.distance=2.4;cam.azimuth=100;cam.elevation=-15
    scene=mujoco.MjvScene(model,maxgeom=4)
    mujoco.mjv_updateScene(model,data,mujoco.MjvOption(),None,cam,mujoco.mjtCatBit.mjCAT_ALL,scene)
    scene.flags[:]=0;scene.flags[mujoco.mjtRndFlag.mjRND_CULL_FACE]=1
    # Static visual pedestal. No geometry or physics is substituted for the model.
    geom=scene.geoms[scene.ngeom]
    mujoco.mjv_initGeom(geom,mujoco.mjtGeom.mjGEOM_BOX,np.array([.25,.2,.025]),np.array([0,0,-.065]),np.eye(3).ravel(),np.array([.25,.3,.35,1],np.float32))
    scene.ngeom+=1
    return model,data,scene

def export(out):
    model,data,scene=scene_at()
    if model.ngeom!=1 or model.nq!=1 or any((model.ntex,model.nmesh,model.nskin,model.nflex)):
        raise ValueError('This renderer target specializes the one-hinge primitive MJX scene')
    allowed={mujoco.mjtGeom.mjGEOM_CAPSULE,mujoco.mjtGeom.mjGEOM_BOX,mujoco.mjtGeom.mjGEOM_SPHERE}
    for g in scene.geoms[:scene.ngeom]:
        if g.type not in allowed or g.rgba[3]!=1 or g.matid!=-1 or g.texid!=-1 or g.reflectance or g.label:
            raise ValueError('Unsupported renderer geometry, material, transparency or label')
    if scene.stereo or scene.enabletransform or scene.nlight>8:
        raise ValueError('Unsupported scene settings')
    text=(ROOT/'third_party/mujoco_renderer/include/mujoco/mjvisualize.h').read_text()
    def literal(v):
        if isinstance(v,np.ndarray):return '{'+','.join(literal(x) for x in v.ravel())+'}'
        if isinstance(v,(int,np.integer)):return str(int(v))
        return float(v).hex()+'f'
    def struct(typ,obj):
        fields=re.search(r'typedef struct '+typ+r'_ \{(.*?)\} '+typ+';',text,re.S)[1]
        names=re.findall(r'^\s*(?:int|float|mjtByte)\s+(\w+)(?:\[\d+\])?;',fields,re.M)
        return '{'+','.join('.'+n+'='+literal(getattr(obj,n)) for n in names)+'}'
    result='#include <mujoco/mujoco.h>\n#define SCENE_GEOMS '+str(scene.ngeom)+'\n'
    result+='static mjvGeom scene_geoms[SCENE_GEOMS] = {'+','.join(struct('mjvGeom',g) for g in scene.geoms[:scene.ngeom])+'};\n'
    result+='static int scene_order[SCENE_GEOMS];\nstatic mjvScene scene={.maxgeom=SCENE_GEOMS,.ngeom=SCENE_GEOMS,.geoms=scene_geoms,.geomorder=scene_order,.scale=1,.rotate={1,0,0,0},'
    result+='.nlight='+str(scene.nlight)+',.lights={'+','.join(struct('mjvLight',l) for l in scene.lights[:scene.nlight])+'},'
    result+='.camera={'+','.join(struct('mjvGLCamera',c) for c in scene.camera)+'},.flags='+literal(scene.flags)+'};\n'
    result+='static const mjModel render_model={.vis={.quality={.numslices=16,.numstacks=8,.numquads=1}}};\n'
    (out/'scene.h').write_text(result)
    return model,data,scene
if __name__=='__main__':export(Path(sys.argv[1]))
