"""Compare the port with the installed MuJoCo renderer and live MJX poses."""
from pathlib import Path
import json,subprocess,sys,re
import mujoco,numpy as np
from build import native,ROOT
from export_scene import scene_at


def fields(typ):
    text=(ROOT/'third_party/mujoco_renderer/include/mujoco/mjvisualize.h').read_text()
    text=re.search(r'typedef struct '+typ+r'_ \{(.*?)\} '+typ+';',text,re.S)[1]
    return re.findall(r'^\s*(?:int|float|mjtByte)\s+(\w+)(?:\[\d+\])?;',text,re.M)


def copy_struct(dst,src,typ):
    for name in fields(typ):
        value=getattr(src,name)
        if isinstance(value,np.ndarray):getattr(dst,name)[:]=value
        else:setattr(dst,name,value)


def reference(angle,width=320,height=240):
    m,d,s=scene_at(angle)
    m.vis.quality.numslices=16;m.vis.quality.numstacks=8;m.vis.quality.numquads=1;m.vis.quality.offsamples=0
    with mujoco.Renderer(m,height=height,width=width) as r:
        r.update_scene(d);r.scene.ngeom=s.ngeom;r.scene.nlight=s.nlight
        for i in range(s.ngeom):copy_struct(r.scene.geoms[i],s.geoms[i],'mjvGeom')
        for i in range(s.nlight):copy_struct(r.scene.lights[i],s.lights[i],'mjvLight')
        for i in range(2):copy_struct(r.scene.camera[i],s.camera[i],'mjvGLCamera')
        r.scene.flags[:]=s.flags
        return r.render().copy()


def rgb565(p):
    p=np.asarray(p,dtype=np.uint16)
    r,g,b=p>>11,(p>>5)&63,p&31
    return np.stack(((r<<3)|(r>>2),(g<<2)|(g>>4),(b<<3)|(b>>2)),axis=-1).astype(np.uint8)


def run(out,width=320,height=240):
    exe=native(out)
    stats=[]
    for i,angle in enumerate([-.6,0.,.25,.65]):
        m,d,s=scene_at(angle)
        poses=np.concatenate((d.geom_xpos,d.geom_xmat),axis=1).astype(np.float32)
        poses.tofile(out/'pose.bin')
        result=subprocess.run([str(exe),str(out/'pose.bin'),str(width),str(height)],capture_output=True,check=True)
        pixels=np.frombuffer(result.stdout,dtype=np.uint16).reshape(height,width)
        rgb=rgb565(pixels);ref=reference(angle,width,height)
        mask=pixels!=0;rmask=ref.max(2)>0
        iou=np.count_nonzero(mask&rmask)/np.count_nonzero(mask|rmask)
        mae=np.abs(rgb.astype(float)-ref)[mask&rmask].mean()
        stats.append(dict(angle=angle,silhouette_iou=iou,interior_rgb_mae=mae,heap=result.stderr.decode().strip()))
        (out/f'port-{i}.ppm').write_bytes(f'P6\n{width} {height}\n255\n'.encode()+rgb.tobytes())
        (out/f'official-{i}.ppm').write_bytes(f'P6\n{width} {height}\n255\n'.encode()+ref.tobytes())
        # TinyGL uses a different pixel-center convention and RGB565 precision.
        assert iou>.92,(angle,iou)
        assert mae<25,(angle,mae)
    report=dict(passed=True,render_resolution=[width,height],scope='Native upstream mjr_render + TinyGL against installed MuJoCo OpenGL renderer; approximate image comparison, not pixel identity',cases=stats)
    (out/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return report
if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('out',type=Path)
    parser.add_argument('--video-mode',choices=('vga','720p'),default='vga');args=parser.parse_args()
    run(args.out.resolve(),*((480,270) if args.video_mode=='720p' else (320,240)))
