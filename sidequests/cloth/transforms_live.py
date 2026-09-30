#!/usr/bin/env python3
"""Temporary preview: JAX physics on host, verified TPU transforms on KC705."""
import argparse,base64,io,json,math,struct,threading,time,sys
from collections import deque
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import numpy as np
import serial
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[2]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--jaxsim',type=Path,required=True);p.add_argument('--port',default='/dev/cu.usbserial-0001');p.add_argument('--steps',type=int,default=2);p.add_argument('--frames',type=int,default=0);a=p.parse_args()
 out=ROOT/'build-cloth/transforms-live';out.mkdir(parents=True,exist_ok=True)
 faces=np.load(ROOT/'build-cloth/mesh.npz')['faces'];cam=json.loads((ROOT/'build-cloth/camera.json').read_text())
 sys.path.insert(0,str(a.jaxsim));from model import Cloth
 cloth=Cloth(6,3);physics_state=cloth.initial;physics_steps=0;epoch=time.perf_counter()
 state={'connected':False,'sequence':-1,'message':'Connecting to on-board cloth simulation'};lock=threading.Lock()
 class Handler(BaseHTTPRequestHandler):
  def do_GET(self):
   with lock:data=dict(state)
   data['age_seconds']=time.time()-data.get('timestamp',time.time());b=json.dumps(data).encode()
   self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
  def log_message(self,*args):pass
 server=ThreadingHTTPServer(('127.0.0.1',8765),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 intervals=deque(maxlen=16);previous=None;seq=0;last_steps=0
 with serial.Serial(a.port,921600,timeout=1,write_timeout=5) as uart,(out/'frames.jsonl').open('a',buffering=1) as log:
  uart.reset_input_buffer()
  def exact(n):
   b=bytearray();deadline=time.monotonic()+60
   while len(b)<n:
    b.extend(uart.read(n-len(b)))
    if time.monotonic()>deadline:raise RuntimeError('UART timed out')
   return bytes(b)
  while not a.frames or seq<a.frames:
   start=time.perf_counter();physics_start=start
   target=int((start-epoch)/cloth.dt)
   if target>=11520:
    epoch=start;target=0;physics_steps=0;physics_state=cloth.initial
   physics_state=cloth.advance(physics_state,max(0,target-physics_steps));physics_steps=target
   vertices=np.asarray(physics_state[0])[:cloth.count];physics_ms=(time.perf_counter()-physics_start)*1000
   quantized=np.rint(vertices*8)
   if not np.isfinite(quantized).all() or (abs(quantized)>127).any():raise RuntimeError('Physics outside int8 coordinate range')
   inputs=quantized.astype(np.int8);expected=inputs.astype(np.int32)@np.array(cam['weights'],np.int32)+np.array(cam['bias'],np.int32)
   request=b'CLQ1'+struct.pack('<I',seq)+np.array(cam['weights'],np.int8).tobytes()+np.array(cam['bias'],dtype='<i4').tobytes()+inputs.tobytes()
   wire_start=time.perf_counter();uart.write(request);uart.flush()
   sync=exact(4)
   while sync!=b'CLR1':sync=sync[1:]+exact(1)
   got,status,cycles,count,checksum=struct.unpack('<5I',exact(20));steps=physics_steps;physics_cycles=0
   if got!=seq or status or count!=28:raise RuntimeError(f'Bad response {got=} {status=} {count=}')
   last_steps=steps
   raw=exact(count*12);coords=np.frombuffer(raw,dtype='<i4').reshape(count,3)
   if int(np.bitwise_xor.reduce(coords.ravel().view(np.uint32)))!=checksum:raise RuntimeError('Checksum mismatch')
   if not np.array_equal(coords,expected):raise RuntimeError('Physical TPU coordinate mismatch')
   if seq==0:(out/'first_coords.bin').write_bytes(raw)
   camera=coords.astype(np.float64)/cam['qscale'];roundtrip=(time.perf_counter()-wire_start)*1000;rs=time.perf_counter()
   if not np.isfinite(camera).all() or (camera[:,2]<=0).any():raise RuntimeError('Invalid camera geometry')
   projected=camera[:,:2]/camera[:,2,None]/math.tan(math.radians(30))
   center=(projected.min(0)+projected.max(0))/2;scale=420/max(float(np.ptp(projected,axis=0).max()),.25)
   pixels=(projected-center)*[scale,-scale]+[256,256]
   image=Image.new('RGB',(512,512),(15,22,33));draw=ImageDraw.Draw(image)
   for t in sorted(faces,key=lambda t:float(camera[t,2].mean()),reverse=True):
    normal=np.cross(camera[t[1]]-camera[t[0]],camera[t[2]]-camera[t[0]]);length=np.linalg.norm(normal)
    light=.4+.6*abs(float(normal@np.array([.3,.6,.74])))/max(length,1e-9)
    color=tuple(int(min(255,x*light)) for x in (80,185,230))
    draw.polygon([tuple(x) for x in pixels[t]],fill=color,outline=(40,80,110))
   for vertex in (0,6):
    x,y=pixels[vertex];draw.ellipse((x-4,y-4,x+4,y+4),fill=(255,210,100))
   png=io.BytesIO();image.save(png,format='PNG');encoded=png.getvalue();render_ms=(time.perf_counter()-rs)*1000;now=time.perf_counter()
   if previous is not None:intervals.append(now-previous)
   previous=now
   item={'connected':True,'sequence':seq,'timestamp':time.time(),'fps':len(intervals)/sum(intervals) if intervals else 1/(now-start),
    'fpga_compute_ms':cycles/100000.,'physics_ms':physics_ms,'uart_and_host_wait_ms':max(0,roundtrip-(cycles+physics_cycles)/100000.),'host_render_ms':render_ms,
    'sim_time':steps/7680,'dt':1/7680,'vertices':count,'verified':True,'simulation_steps':steps,
    'message':'Host JAX cloth physics / all vertex transforms verified on physical KC705 TPU'}
   log.write(json.dumps(item)+'\n');(out/'latest.json').write_text(json.dumps(item,indent=2));(out/'latest.png').write_bytes(encoded)
   with lock:state.update(item,png=base64.b64encode(encoded).decode())
   print(f"frame={seq} fps={item['fps']:.2f} physics_ms={item['physics_ms']:.1f} sim_s={item['sim_time']:.4f} checksum_ok",flush=True);seq+=1
 server.shutdown()
if __name__=='__main__':main()
