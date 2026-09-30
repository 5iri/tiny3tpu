"""Switch the existing cloth preview to verified physical-TPU transforms."""
from pathlib import Path
import json,os,signal,subprocess
ROOT=Path(__file__).resolve().parents[2]
for directory in ('build-cloth/live','build-cloth/transforms-live'):
 for name in ('live','window'):
  p=ROOT/directory/f'{name}-pid.json'
  if not p.exists():continue
  pid=json.loads(p.read_text())['pid'];r=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True)
  if 'sidequests/cloth/' in r.stdout:os.kill(pid,signal.SIGTERM)
out=ROOT/'build-cloth/transforms-live';out.mkdir(exist_ok=True)
with (out/'program.log').open('w') as log:
 subprocess.run(['openFPGALoader','-b','kc705','--ftdi-serial','210203A3CFBC','--write-sram',str(ROOT/'build-cloth/transforms-board/soc.bit')],stdout=log,stderr=subprocess.STDOUT,check=True)
for kind,script,args in [('live','transforms_live',['--jaxsim','/tmp/tiny3tpu-jaxsim-banana']),('window','transforms_window',['--title','KC705 — Cloth / TPU Transforms','--heading','KC705 / CLOTH TRANSFORMS','--scope','Host JAX physics · physical KC705 TPU transforms · every coordinate verified · no DDR'])]:
 with (out/f'{kind}.log').open('w') as log:
  p=subprocess.Popen(['/tmp/tiny3tpu-banana-venv/bin/python','-u',str(ROOT/f'sidequests/cloth/{script}.py'),*args],stdout=log,stderr=subprocess.STDOUT,start_new_session=True,cwd=ROOT)
 (out/f'{kind}-pid.json').write_text(json.dumps({'pid':p.pid}));print(kind,p.pid,flush=True)
