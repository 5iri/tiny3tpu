"""Prepare independent native-C expected UART geometry for three RTL frames."""
import subprocess,numpy as np,json
from pathlib import Path
subprocess.run(['cc','-O2','-ffp-contract=off','-Ibuild-cloth','-Isidequests/cloth','sidequests/cloth/check.c','-o','build-cloth/check'],check=True)
c=json.loads(Path('build-cloth/camera.json').read_text());lines=[]
for n in [2,4,6]:
 a=np.frombuffer(subprocess.check_output(['build-cloth/check',str(n)]),np.float32).reshape(-1,3)[:28]
 a=np.rint(a*8).astype(np.int8);lines.append('{'+','.join(map(str,a.ravel()))+'}')
Path('build-cloth/banana_vertices.h').write_text('#define BANANA_VERTICES 28U\nstatic const signed char frame_vertices[3][84]={'+','.join(lines)+'};\n')
Path('build-cloth/banana_fixture.h').write_text('static const signed char banana_weights[9]={'+','.join(map(str,np.array(c['weights']).ravel()))+'};\nstatic const int banana_bias[3]={'+','.join(map(str,c['bias']))+'};\n')
