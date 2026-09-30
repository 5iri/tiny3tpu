#!/usr/bin/env python3
"""SRAM-program a board and preserve UART bytes throughout programming/startup."""
import argparse, hashlib, json, os, select, subprocess, termios, time
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--bit',type=Path,required=True)
p.add_argument('--out',type=Path,required=True)
p.add_argument('--seconds',type=float,default=90)
p.add_argument('--baud',type=int,choices=[57600,115200],default=115200)
p.add_argument('--port',default='/dev/cu.usbserial-0001')
a=p.parse_args(); a.out.mkdir(parents=True,exist_ok=True)
fd=os.open(a.port,os.O_RDWR|os.O_NOCTTY|os.O_NONBLOCK)
c=termios.tcgetattr(fd);c[0:4]=[0,0,termios.CS8|termios.CREAD|termios.CLOCAL,0]
c[4:6]=[getattr(termios, "B"+str(a.baud))]*2;c[6][termios.VMIN]=0;c[6][termios.VTIME]=0
termios.tcsetattr(fd,termios.TCSANOW,c);termios.tcflush(fd,termios.TCIFLUSH)
start=time.monotonic();data=bytearray();events=[];program_done=None
with (a.out/'program.log').open('w') as log:
 proc=subprocess.Popen(['openFPGALoader','-b','kc705','--ftdi-serial','210203A3CFBC','--write-sram',str(a.bit)],stdout=log,stderr=subprocess.STDOUT)
 while time.monotonic()-start<a.seconds:
  if program_done is None and proc.poll() is not None:
   program_done=dict(seconds=time.monotonic()-start,offset=len(data),returncode=proc.returncode)
   print('Programming completed:',program_done,flush=True)
  if select.select([fd],[],[],0.25)[0]:
   chunk=os.read(fd,65536)
   if chunk:
    events.append(dict(seconds=time.monotonic()-start,offset=len(data),bytes=len(chunk)))
    data.extend(chunk)
    if program_done is not None: print(chunk.decode('ascii','backslashreplace'),end='',flush=True)
 rc=proc.wait()
os.close(fd)
(a.out/'uart.bin').write_bytes(data)
(a.out/'uart.txt').write_text(data.decode('ascii','backslashreplace'))
(a.out/'capture.json').write_text(json.dumps(dict(bit=str(a.bit),sha256=hashlib.sha256(a.bit.read_bytes()).hexdigest(),program_done=program_done,program_exit=rc,bytes=len(data),seconds=a.seconds,events=events),indent=2)+'\n')
print('\nCaptured',len(data),'bytes; includes any old-image bytes before reconfiguration.',flush=True)
raise SystemExit(rc)
