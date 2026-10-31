#!/usr/bin/env python3
"""Display physical board results. No JAX import or host inference/physics."""
import argparse,base64,io,json,math,threading,time
from collections import deque
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
from protocol import transact
from build_support import load_expected_modes
from stream import LatestResults
from uart_transport import open_transport,LatencyWindow
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
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--port',default='/dev/cu.usbserial-0001')
 p.add_argument('--http-port',type=int,default=8766)
 p.add_argument('--raw-uart','--raw-responses',dest='raw_uart',action='store_true',help='Disable lossless compact banana responses')
 p.add_argument('--out',type=Path,default=ROOT/'build-showcase/live')
 p.add_argument('--board',type=Path,default=ROOT/'build-showcase/board',help='Build directory for the programmed image')
 p.add_argument('--expected-backend-calls',type=int,nargs=4,metavar=('MLP','ATTENTION','CORDIC','BANANA'),help='Explicit counts for an older image without a build manifest')
 a=p.parse_args();out=a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 manifest_path=a.board/'build-manifest.json'
 if manifest_path.exists():
  _,manifest=load_expected_modes(a.board,{i:0 for i in range(4)})
  if manifest.get('io_transport','uart')!='uart':p.error('Selected build manifest does not match the requested UART transport')
  contracts={int(x['mode']):x for x in manifest['modes']};clock_hz=manifest['clock_hz']
 elif a.expected_backend_calls is not None:
  if min(a.expected_backend_calls)<0:p.error('--expected-backend-calls must be nonnegative')
  contracts={i:{'expected_backend_calls':calls,'words':(20,64,64,613)[i]} for i,calls in enumerate(a.expected_backend_calls)};clock_hz=100000000
 else:p.error('The programmed image needs --board with build-manifest.json, or --expected-backend-calls MLP ATTENTION CORDIC BANANA for an older image')
 if set(contracts)!=set(range(4)):p.error('Build manifest must describe modes 0 through 3')
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
 expected={i:np.load(a.board/contracts[i]['expected_file'] if 'expected_file' in contracts[i] else ROOT/'build-showcase'/('quantized_mlp' if i==0 else 'attention_block')/'expected-native.npy').ravel() for i in range(3)}
 server=ThreadingHTTPServer(('127.0.0.1',a.http_port),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 def acquire(stream):
  samples={i:deque(maxlen=16) for i in range(4)};history=deque(maxlen=16);previous=None;counts={i:0 for i in range(4)};latencies={i:LatencyWindow() for i in range(4)}
  with open_transport(a.port,stop=stream.stopped) as uart:
   # Compact coordinates reduce UART wire time.
   uart.reset_input_buffer();sequence=0;compact_enabled=not a.raw_uart
   while not stream.stopped.is_set():
    mode=(sequence//20)%3 if sequence%20==0 else 3
    rec,data=transact(uart,sequence,mode,stop=stream.stopped,compact=mode==3 and compact_enabled)
    if rec['compact_supported'] is False:compact_enabled=False
    contract=contracts[mode]
    if rec['status'] or rec['words']!=contract['words'] or rec['backend_calls']!=contract['expected_backend_calls']:raise RuntimeError(f'Board response does not match selected image: {rec}')
    if mode<3:np.testing.assert_array_equal(data.view(np.uint32),expected[mode].view(np.uint32))
    elif not np.isfinite(data).all() or (data[3::3]<=0).any():raise RuntimeError('Invalid banana camera geometry')
    rec['compute_ms']=rec['cycles']/(clock_hz/1000)
    latencies[mode].observe(rec['roundtrip_ms'],rec['compute_ms']);rec['latency']=latencies[mode].summary()
    rec['outside_compute_ms']=max(0.,rec['roundtrip_ms']-rec['compute_ms'])
    samples[mode].append(rec['compute_ms']);rec['mean_compute_ms']=sum(samples[mode])/len(samples[mode])
    now=time.perf_counter()
    if previous is not None:history.append(now-previous)
    previous=now;counts[mode]+=1
    rec.update(verified=True,verification='reference_and_checksum' if mode<3 else 'checksum_and_geometry',timestamp=time.time(),acquired_requests=sequence+1,mode_acquired_requests=counts[mode],acquisition_fps=len(history)/sum(history) if history else 0,clock_hz=clock_hz)
    stream.publish(mode,(rec,data));sequence+=1
 history=deque(maxlen=16);previous=None;rendered={i:0 for i in range(4)}
 try:
  with LatestResults(acquire,range(4)) as stream,(out/'frames.jsonl').open('a',buffering=1) as log:
   for pending in stream:
    for mode,(rec,data) in pending.items():
     start=time.perf_counter();rec['outputs']=data.tolist()
     if mode==3:rec['png']=banana_image(data,mesh,scale)
     rec['host_render_ms']=(time.perf_counter()-start)*1000;rendered[mode]+=1
     rec['displayed_frames']=rendered[mode];rec['skipped_display_frames']=rec['mode_acquired_requests']-rendered[mode]
     log.write(json.dumps({k:v for k,v in rec.items() if k not in ('outputs','png')})+'\n')
    now=time.perf_counter()
    if previous is not None:history.append(now-previous)
    previous=now;latest=max((entry[0] for entry in pending.values()),key=lambda item:item['sequence'])
    with lock:
     for mode,(rec,_) in pending.items():state['examples'][str(mode)]=rec
     state.update(connected=True,timestamp=latest['timestamp'],sequence=latest['sequence'],fps=latest['acquisition_fps'],acquisition_fps=latest['acquisition_fps'],display_updates_fps=len(history)/sum(history) if history else 0)
     snapshot=json.dumps(state,indent=2)+'\n'
    (out/'latest.json').write_text(snapshot)
 except KeyboardInterrupt:pass
 finally:server.shutdown();server.server_close()
if __name__=='__main__':main()
