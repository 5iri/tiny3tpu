#!/usr/bin/env python3
"""Program, verify and display compiled cloth; no host physics process."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--board',type=Path,default=ROOT/'build-cloth/optimized-board')
    a=p.parse_args();board=a.board.resolve()
    manifest=json.loads((board/'application-manifest.json').read_text())
    for filename,want in manifest['sha256'].items():
        if hashlib.sha256(Path(filename).read_bytes()).hexdigest()!=want:
            raise RuntimeError('Rebuild required: manifest mismatch for '+filename)
    stopped=[]
    for directory in ('live','transforms-live','compiled-live'):
        for kind in ('live','window'):
            record=ROOT/'build-cloth'/directory/(kind+'-pid.json')
            if not record.exists():continue
            pid=json.loads(record.read_text())['pid']
            command=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True).stdout
            if 'sidequests/cloth/' in command:
                os.kill(pid,signal.SIGTERM);stopped.append(pid)
    for _ in range(30):
        if all(subprocess.run(['ps','-p',str(pid)],stdout=subprocess.DEVNULL).returncode for pid in stopped):break
        time.sleep(.1)
    else:raise RuntimeError('Prior cloth processes have not exited')
    for endpoint in ('/dev/cu.usbserial-0001','-iTCP:8765'):
        owners=subprocess.run(['lsof','-t',endpoint],capture_output=True,text=True).stdout.strip()
        if owners:raise RuntimeError('Another process owns '+endpoint+': '+owners)
    out=ROOT/'build-cloth/compiled-live';out.mkdir(parents=True,exist_ok=True)
    with (board/'program.log').open('w') as log:
        subprocess.run(['openFPGALoader','-b','kc705','--ftdi-serial','210203A3CFBC',
                        '--write-sram',str(board/'soc.bit')],check=True,stdout=log,stderr=subprocess.STDOUT)
    subprocess.run([sys.executable,str(ROOT/'sidequests/cloth/verify_compiled_board.py'),
                    '--board',str(board)],check=True)
    commands={
        'live':['live.py','--compiled','--steps','1','--clock-hz',str(manifest.get('clock_hz',100000000))],
        'window':['window.py','--title','KC705 — Compiled Cloth / CPU + TPU',
                  '--heading','KC705 / STABLEHLO CLOTH',
                  '--scope','Compiled physics on board CPU · packed TPU transforms · host pixels only · no host JAX']}
    if manifest.get('cpu')=='rocket':
        commands['window'][2]='KC705 — Rocket FPU + TPU / Cloth'
        commands['window'][4]='KC705 / ROCKET + STABLEHLO'
        commands['window'][-1]='Rocket FPU physics · packed TPU transforms · host pixels only · no host JAX'
    if manifest['physics_affine_partitions']:
        commands['window'][-1]='Compiled physics on board CPU + TPU · host pixels only · no host JAX'
    for kind,args in commands.items():
        with (out/(kind+'.log')).open('w') as log:
            process=subprocess.Popen([sys.executable,'-u',str(ROOT/'sidequests/cloth'/args[0]),*args[1:]],
                cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        (out/(kind+'-pid.json')).write_text(json.dumps({'pid':process.pid}))
        print(kind,process.pid,flush=True)
    (out/'active-board.json').write_text(json.dumps({'board':str(board),'manifest':manifest},indent=2)+'\n')
if __name__=='__main__':main()
