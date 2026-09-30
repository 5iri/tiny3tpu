"""Export the upstream cloth constants; no simulation is used in the live host."""
import sys,json
from pathlib import Path
import numpy as np
sys.path.insert(0,sys.argv[1])
from model import Cloth
c=Cloth(6,3);m=c.model
out=Path('build-cloth');out.mkdir(exist_ok=True)
arrays={'initial_q':c.initial[0],'initial_v':c.initial[1],'inv_mass':m.particle_inv_mass,
        'triangles':m.tri_indices,'poses':m.tri_poses,'activations':m.tri_activations,
        'edges':m.edge_indices,'rest_angle':m.edge_rest_angle,'springs':m.spring_indices,
        'spring_length':m.spring_rest_length,'spring_k':m.spring_stiffness,'spring_d':m.spring_damping}
lines=[f'#define PARTICLES {m.particle_count}',f'#define VERTICES {c.count}',f'#define TRIANGLES {m.tri_count}',f'#define EDGES {m.edge_count}',f'#define SPRINGS {m.spring_count}',
       f'#define TRI_MU {m.tri_ke}f',f'#define TRI_LAMBDA {m.tri_ka}f',f'#define TRI_DAMP {m.tri_kd}f',f'#define EDGE_K {m.edge_ke}f',f'#define EDGE_D {m.edge_kd}f']
for name,a in arrays.items():
 a=np.asarray(a);integer=name in ['triangles','edges','springs'];t='int' if integer else 'float'
 values=','.join(str(int(x)) if integer else f'{float(x):.9e}f' for x in a.ravel())
 lines.append(f'static const {t} {name}[] = {{'+values+'};')
(out/'cloth_data.h').write_text('\n'.join(lines)+'\n')
np.savez(out/'mesh.npz',faces=c.faces)
(out/'metadata.json').write_text(json.dumps({'vertices':c.count,'faces':len(c.faces),'dt':c.dt,'physics':'upstream dflex springs, Neo-Hookean triangles, dihedral bending, semi-implicit Euler','mesh':'6x3 cells; same 2x1 metre dimensions','float':'software float32; acos approximation max absolute error about 7e-5 radians'},indent=2))
print(m.particle_count,m.tri_count,m.edge_count)
# Camera constants are compiled into firmware; no camera upload in the live loop.
import jax.numpy as jnp
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'banana'))
from jaxsim.renderutils import SoftRenderer
from render import camera_rotation
r=SoftRenderer(image_size=96,camera_mode='look_at');r.set_eye_from_angles(5.,15.,25.)
rotation=camera_rotation(r,jnp,np);weights=np.rint(rotation*127).astype(np.int8)
bias=np.rint(-np.asarray(r.eye)@rotation*(8*127)).astype(np.int32)
with (out/'cloth_data.h').open('a') as f:
 f.write('\nstatic const signed char camera_weights[9]={'+','.join(map(str,weights.ravel()))+'};\n')
 f.write('static const int camera_bias[3]={'+','.join(map(str,bias))+'};\n')
(out/'camera.json').write_text(json.dumps({'eye':np.asarray(r.eye).tolist(),'weights':weights.tolist(),'bias':bias.tolist(),'qscale':8*127}))
