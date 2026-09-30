"""Compare the firmware physics with upstream JAX offline; not a live dependency."""
import sys,subprocess,json
from pathlib import Path
import numpy as np
sys.path.insert(0,sys.argv[1])
from model import Cloth
c=Cloth(6,3)
subprocess.run(['cc','-O2','-ffp-contract=off','-Ibuild-cloth','-Isidequests/cloth','sidequests/cloth/check.c','-o','build-cloth/check'],check=True)
rows=[]
for steps in (1,128,768,7680,11520):
 reference=np.asarray(c.advance(c.initial,steps)[0])
 actual=np.frombuffer(subprocess.check_output(['build-cloth/check',str(steps)]),np.float32).reshape(-1,3)
 assert np.isfinite(reference).all() and np.isfinite(actual).all()
 assert np.array_equal(actual[-2:],c.anchors)
 error=float(abs(actual-reference).max())
 assert error<(.0001 if steps<=7680 else .1),(steps,error)
 rows.append({'steps':steps,'seconds':steps*c.dt,'max_position_error_metres':error})
 print(rows[-1],flush=True)
Path('build-cloth/physics-check.json').write_text(json.dumps({'checks':rows,'long_run_limitation':'Upstream JAX becomes nonfinite in a 10-second test; live playback resets after the original 1.5-second interval.'},indent=2))
