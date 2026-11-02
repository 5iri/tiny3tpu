#!/usr/bin/env python3
"""Display only: cloth physics and TPU transforms execute on the KC705."""
import argparse,base64,io,json,math,struct,sys,threading,time
from collections import deque
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from sidequests.showcase.stream import LatestResults,read_exact,read_magic
from sidequests.showcase.udp_transport import add_transport_arguments,open_transport,LatencyWindow
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',default='/dev/cu.usbserial-0001');p.add_argument('--steps',type=int,default=2);p.add_argument('--frames',type=int,default=0)
 add_transport_arguments(p)
 p.add_argument('--compiled',action='store_true',help='Use the StableHLO-generated CPU+TPU firmware protocol')
 p.add_argument('--clock-hz',type=int,default=100000000,help='Must match the programmed image')
 a=p.parse_args()
 if not 1<=a.steps<=32:p.error('--steps must be between 1 and 32')
 if a.clock_hz<=0:p.error('--clock-hz must be positive')
 if a.frames<0:p.error('--frames must be nonnegative')
 if a.udp and not a.compiled:p.error('--udp requires --compiled (CLQ3 Ethernet firmware)')
 cycles_per_ms=a.clock_hz/1000.
 out=ROOT/('build-cloth/compiled-live' if a.compiled else 'build-cloth/live');out.mkdir(parents=True,exist_ok=True)
 faces=np.load(ROOT/'build-cloth/mesh.npz')['faces'];cam=json.loads((ROOT/'build-cloth/camera.json').read_text())
 state={'connected':False,'sequence':-1,'message':'Connecting to on-board cloth simulation'};lock=threading.Lock()
 class Handler(BaseHTTPRequestHandler):
  def do_GET(self):
   with lock:data=dict(state)
   data['age_seconds']=time.time()-data.get('timestamp',time.time());b=json.dumps(data).encode()
   self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
  def log_message(self,*args):pass
 server=ThreadingHTTPServer(('127.0.0.1',8765),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 def acquire(stream):
  intervals=deque(maxlen=16);previous=None;seq=0;last_steps=0;latencies=LatencyWindow()
  with open_transport(a.port,udp=a.udp,udp_bind_port=a.udp_bind_port,stop=stream.stopped) as uart:
   uart.reset_input_buffer()
   while not stream.stopped.is_set() and (not a.frames or seq<a.frames):
    start=time.perf_counter();deadline=time.monotonic()+60;reset=seq==0 or last_steps>=11520
    uart.write((b'CLQ3' if a.compiled else b'CLQ2')+struct.pack('<II',seq,a.steps|(256 if reset else 0)))
    def exact(n):return read_exact(uart,n,deadline=deadline,stop=stream.stopped)
    read_magic(uart,b'CLR3' if a.compiled else b'CLR2',deadline=deadline,stop=stream.stopped)
    got,status,cycles,count,checksum,physics_cycles,steps=struct.unpack('<7I',exact(28))
    physics_calls=struct.unpack('<I',exact(4))[0] if a.compiled else 0
    if got!=seq or status or count!=28:raise RuntimeError(f'Bad response {got=} {status=} {count=}')
    if steps!=(0 if reset else last_steps)+a.steps:raise RuntimeError('Incorrect simulation step count')
    last_steps=steps;raw=exact(count*12);coords=np.frombuffer(raw,dtype='<i4').reshape(count,3)
    if int(np.bitwise_xor.reduce(coords.ravel().view(np.uint32)))!=checksum:raise RuntimeError('Checksum mismatch')
    if a.udp:uart.assert_consumed()
    camera=coords.astype(np.float64)/cam['qscale']
    if not np.isfinite(camera).all() or (camera[:,2]<=0).any():raise RuntimeError('Invalid camera geometry')
    now=time.perf_counter();roundtrip=(now-start)*1000
    if previous is not None:intervals.append(now-previous)
    previous=now
    if seq==0:(out/'first_coords.bin').write_bytes(raw)
    latencies.observe(roundtrip,(cycles+physics_cycles)/cycles_per_ms)
    item={'transport':'udp' if a.udp else 'uart','latency':latencies.summary(),'outside_compute_ms':max(0.,roundtrip-(cycles+physics_cycles)/cycles_per_ms),'connected':True,'sequence':seq,'timestamp':time.time(),'acquisition_fps':len(intervals)/sum(intervals) if intervals else 1000/roundtrip,
     'fpga_compute_ms':cycles/cycles_per_ms,'physics_ms':physics_cycles/cycles_per_ms,'uart_and_host_wait_ms':max(0,roundtrip-(cycles+physics_cycles)/cycles_per_ms),'roundtrip_ms':roundtrip,
     'clock_hz':a.clock_hz,'sim_time':steps/7680,'dt':1/7680,'vertices':count,'verified':True,'verification':'checksum_geometry_and_step_count','simulation_steps':steps,
     'physics_backend_calls':physics_calls,
     'execution_backend':'stablehlo_cpu_tpu' if a.compiled else 'handwritten_cpu_tpu',
     'message':(('StableHLO physics on KC705 CPU + TPU / host pixels only' if physics_calls else
                 'StableHLO physics on KC705 CPU / physical TPU transforms / host pixels only')
                if a.compiled else 'On-board RISC-V cloth physics + physical TPU transforms / host pixels only')}
    if a.udp:
     item.pop('uart_and_host_wait_ms',None);item.update(uart.last_metrics)
    stream.publish(0,(item,camera));seq+=1
 intervals=deque(maxlen=16);previous=None;displayed=0
 try:
  with LatestResults(acquire,[0]) as stream,(out/'frames.jsonl').open('a',buffering=1) as log:
   for pending in stream:
    item,camera=pending[0];rs=time.perf_counter()
    projected=camera[:,:2]/camera[:,2,None]/math.tan(math.radians(30))
    pixels=np.column_stack(((projected[:,0]+1)*256,(1-projected[:,1])*256))
    image=Image.new('RGB',(512,512),(15,22,33));draw=ImageDraw.Draw(image)
    for t in sorted(faces,key=lambda t:float(camera[t,2].mean()),reverse=True):
     normal=np.cross(camera[t[1]]-camera[t[0]],camera[t[2]]-camera[t[0]]);length=np.linalg.norm(normal)
     light=.4+.6*abs(float(normal@np.array([.3,.6,.74])))/max(length,1e-9)
     color=tuple(int(min(255,x*light)) for x in (80,185,230))
     draw.polygon([tuple(x) for x in pixels[t]],fill=color,outline=(40,80,110))
    for vertex in (0,6):
     x,y=pixels[vertex];draw.ellipse((x-4,y-4,x+4,y+4),fill=(255,210,100))
    png=io.BytesIO();image.save(png,format='PNG');encoded=png.getvalue();render_ms=(time.perf_counter()-rs)*1000
    now=time.perf_counter()
    if previous is not None:intervals.append(now-previous)
    previous=now;displayed+=1
    item.update(host_render_ms=render_ms,fps=item['acquisition_fps'],display_updates_fps=len(intervals)/sum(intervals) if intervals else 0,displayed_frames=displayed,skipped_display_frames=item['sequence']+1-displayed)
    log.write(json.dumps(item)+'\n');(out/'latest.json').write_text(json.dumps(item,indent=2));(out/'latest.png').write_bytes(encoded)
    with lock:state.update(item,png=base64.b64encode(encoded).decode())
 except KeyboardInterrupt:pass
 finally:server.shutdown();server.server_close()
if __name__=='__main__':main()
