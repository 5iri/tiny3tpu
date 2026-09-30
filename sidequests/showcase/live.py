#!/usr/bin/env python3
"""Display physical board results. No JAX import or host inference/physics."""
import argparse,base64,io,json,math,threading,time
from collections import deque
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
import serial
from protocol import transact
ROOT=Path(__file__).resolve().parents[2]
def banana_image(data,mesh,scale):
 camera=data[1:].reshape(-1,3)/scale
 projected=camera[:,:2]/camera[:,2,None]/math.tan(math.radians(30))
 pixels=np.column_stack(((projected[:,0]+1)*256,(1-projected[:,1])*256))
 im=Image.new('RGB',(512,512),(15,22,33));draw=ImageDraw.Draw(im)
 for face in sorted(mesh['faces'],key=lambda f:float(camera[f,2].mean()),reverse=True):
  normal=np.cross(camera[face[1]]-camera[face[0]],camera[face[2]]-camera[face[0]])
  light=.35+.65*abs(float(normal@np.array([.3,.6,.74])))/max(np.linalg.norm(normal),1e-9)
  color=tuple(int(c*light) for c in (245,215,65))
  draw.polygon([tuple(x) for x in pixels[face]],fill=color,outline=(110,100,40))
 b=io.BytesIO();im.save(b,format='PNG');return base64.b64encode(b.getvalue()).decode()
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',default='/dev/cu.usbserial-0001');p.add_argument('--http-port',type=int,default=8766);p.add_argument('--out',type=Path,default=ROOT/'build-showcase/live');a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 mesh=np.load(ROOT/'build-banana/render/mesh.npz');scale=json.loads((ROOT/'build-banana/render/report.json').read_text())['vertex_scale']*127
 state={'connected':False,'examples':{},'memory':json.loads((ROOT/'build-showcase/pretrained/memory-report.json').read_text())};lock=threading.Lock();page=Path(__file__).with_name('viewer.html').read_bytes()
 class Handler(BaseHTTPRequestHandler):
  def do_GET(self):
   if self.path=='/':b=page;mime='text/html'
   elif self.path.startswith('/state'):
    with lock:b=json.dumps(dict(state,age_seconds=time.time()-state.get('timestamp',time.time()))).encode()
    mime='application/json'
   else:self.send_error(404);return
   self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
  def log_message(self,*args):pass
 server=ThreadingHTTPServer(('127.0.0.1',a.http_port),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 samples={i:deque(maxlen=16) for i in range(4)};history=deque(maxlen=16);previous=None
 expected={0:np.load(ROOT/'build-showcase/quantized_mlp/expected-native.npy').ravel(),1:np.load(ROOT/'build-showcase/attention_block/expected-native.npy').ravel()};expected[2]=expected[1]
 with serial.Serial(a.port,921600,timeout=1,write_timeout=5) as uart,(out/'frames.jsonl').open('a',buffering=1) as log:
  uart.reset_input_buffer();sequence=0
  while True:
   mode=(sequence//20)%3 if sequence%20==0 else 3
   rec,data=transact(uart,sequence,mode)
   if rec['status']:raise RuntimeError(rec)
   if mode<3:np.testing.assert_array_equal(data.view(np.uint32),expected[mode].view(np.uint32))
   samples[mode].append(rec['compute_ms']);rec['mean_compute_ms']=sum(samples[mode])/len(samples[mode]);rec['outputs']=data.tolist();rec['verified']=True
   if mode==3:rec['png']=banana_image(data,mesh,scale)
   now=time.perf_counter()
   if previous is not None:history.append(now-previous)
   previous=now
   with lock:
    state['examples'][str(mode)]=rec;state.update(connected=True,timestamp=time.time(),sequence=sequence,fps=len(history)/sum(history) if history else 0)
    (out/'latest.json').write_text(json.dumps(state,indent=2)+'\n')
   log.write(json.dumps({k:v for k,v in rec.items() if k not in ('outputs','png')})+'\n');print('frame',sequence,'mode',mode,'ms',rec['compute_ms'],flush=True);sequence+=1
if __name__=='__main__':main()
