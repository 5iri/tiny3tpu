#!/usr/bin/env python3
"""Prepare the upstream low-poly sphere for resident KC705 transforms."""
import argparse,json
from pathlib import Path
import numpy as np
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--jaxsim',type=Path,required=True)
p.add_argument('--out',type=Path,default=Path('build-physics/mesh'))
a=p.parse_args()
verts=[];faces=[]
for line in (a.jaxsim/'examples/sampledata/icosphere_80.obj').read_text().splitlines():
 fields=line.split()
 if fields and fields[0]=='v':verts.append([float(v) for v in fields[1:4]])
 if fields and fields[0]=='f':faces.append([int(v.split('/')[0])-1 for v in fields[1:4]])
vertices=np.asarray(verts,dtype=np.float32)*.18
scale=110/.18
inputs=np.rint(vertices*scale).astype(np.int8)
a.out.mkdir(parents=True,exist_ok=True)
np.savez(a.out/'mesh.npz',vertices=vertices,faces=np.asarray(faces,dtype=np.int32),inputs=inputs)
(a.out/'report.json').write_text(json.dumps({'vertex_scale':scale,'radius':.18,'vertices':len(vertices),'faces':len(faces)},indent=2))
(a.out/'banana_vertices.h').write_text(f'#define BANANA_VERTICES {len(vertices)}U\nstatic const signed char banana_vertices[] = {{'+','.join(str(int(v)) for v in inputs.ravel())+'};\n')
print(len(vertices),'sphere vertices,',len(faces),'faces')
