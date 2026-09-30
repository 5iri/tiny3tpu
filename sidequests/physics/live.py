#!/usr/bin/env python3
"""Live upstream double pendulum: JAX physics, verified KC705 sphere transforms."""
import argparse,base64,io,json,math,struct,sys,threading,time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--jaxsim',type=Path,required=True)
    p.add_argument('--mesh',type=Path,default=ROOT/'build-physics/mesh')
    p.add_argument('--out',type=Path,default=ROOT/'build-physics/live')
    p.add_argument('--port',default='/dev/cu.usbserial-0001')
    p.add_argument('--baud',type=int,default=921600)
    p.add_argument('--http-port',type=int,default=8765)
    p.add_argument('--size',type=int,default=96)
    p.add_argument('--frames',type=int,default=0)
    a=p.parse_args()
    import jax,jax.numpy as jnp,numpy as np,serial
    from PIL import Image,ImageDraw
    sys.path.insert(0,str(a.jaxsim.resolve()))
    sys.path.insert(0,str(ROOT/'sidequests/banana'))
    from jaxsim.renderutils import SoftRenderer
    from render import camera_rotation
    from model import Physics
    a.out.mkdir(parents=True,exist_ok=True)
    mesh=np.load(a.mesh/'mesh.npz');meta=json.loads((a.mesh/'report.json').read_text())
    vertices,faces,inputs=mesh['vertices'],mesh['faces'],mesh['inputs']
    scale=meta['vertex_scale'];qscale=scale*127
    physics=Physics();y=physics.initial;sim_steps=0
    renderer=SoftRenderer(image_size=a.size,anti_aliasing=False,camera_mode='look_at',
                          bg_color=[.025,.035,.05],gamma_val=.03)
    renderer.set_eye_from_angles(4.6,0.,0.)
    rotation=camera_rotation(renderer,jnp,np)
    weights=np.rint(rotation*127).astype(np.int8)
    face_indices=np.concatenate([faces,faces+len(vertices)])[None]
    world=np.concatenate([vertices,vertices])[None]
    colors=np.concatenate([np.tile([1.,.27,.18],(len(faces),1)),
                           np.tile([.18,.68,1.],(len(faces),1))])[None].astype(np.float32)
    # Upstream lighting returns (B,F,1,3); keep the sample axis explicit to
    # prevent face colours from broadcasting into an unintended F-by-F array.
    lit=renderer.lighting(jnp.asarray(world),jnp.asarray(face_indices),
                          jnp.asarray(colors[:,:,None,:]))[:,:,0,:]
    def render(camera):
        projected=renderer.perspective_distortion(camera,renderer.viewing_angle)
        return renderer.rasterize(projected,jnp.asarray(face_indices),lit)
    rasterize=jax.jit(render)
    rasterize(renderer.look_at(jnp.asarray(world),renderer.eye)).block_until_ready()
    # Project the support through the same camera convention used by the spheres.
    support=np.asarray(renderer.perspective_distortion(
        renderer.look_at(jnp.zeros((1,1,3)),renderer.eye),renderer.viewing_angle))[0,0]
    state={'connected':False,'message':'Waiting for UART','sequence':-1}
    lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith('/state'):
                with lock:snapshot=dict(state)
                snapshot['age_seconds']=time.time()-snapshot.get('timestamp',time.time())
                data=json.dumps(snapshot).encode();mime='application/json'
            else:
                data=b'''<!doctype html><title>KC705 Double Pendulum</title><body style="background:#101722;color:white;font:20px sans-serif"><h1>JAX double pendulum / KC705 transforms</h1><p id="s"></p><img id="i" width="512"><script>setInterval(async()=>{let d=await(await fetch('/state')).json();s.textContent=d.message+' / '+(d.fps||0).toFixed(1)+' FPS';if(d.png)i.src='data:image/png;base64,'+d.png},50)</script>''';mime='text/html'
            self.send_response(200);self.send_header('Content-Type',mime)
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)))
            self.end_headers();self.wfile.write(data)
        def log_message(self,*args):pass
    server=ThreadingHTTPServer(('127.0.0.1',a.http_port),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    print(f'Physics dashboard http://127.0.0.1:{a.http_port}',flush=True)
    intervals=deque(maxlen=16);trail=deque(maxlen=150)
    previous=None;sequence=0;start=time.perf_counter();executor=ThreadPoolExecutor(max_workers=1)
    log=(a.out/'frames.jsonl').open('a',buffering=1)
    try:
        with serial.Serial(a.port,a.baud,timeout=None,write_timeout=3) as uart:
            uart.reset_input_buffer()
            def exact(count):
                data=bytearray()
                while len(data)<count:data.extend(uart.read(count-len(data)))
                return bytes(data)
            def prepare(sequence):
                nonlocal y,sim_steps
                t=time.perf_counter();target=int((t-start)/physics.dt)
                y=physics.advance(y,max(0,target-sim_steps));sim_steps=target
                positions=np.asarray(physics.positions(y))
                energy=float(physics.energy(y))
                requests=[]
                for bob,pos in enumerate(positions):
                    bias=np.rint((pos-np.asarray(renderer.eye))@rotation*qscale).astype('<i4')
                    expected=inputs.astype(np.int32)@weights.astype(np.int32)+bias
                    wire_seq=sequence*2+bob
                    request=b'BNQ1'+struct.pack('<I',wire_seq)+weights.tobytes()+bias.tobytes()
                    requests.append((wire_seq,request,expected))
                return sequence,t,sim_steps*physics.dt,energy,requests
            def transact(sequence,t,sim_time,energy,requests):
                camera=[];cycles_total=0;wire_start=time.perf_counter()
                for wire_seq,request,expected in requests:
                    uart.write(request);uart.flush()
                    sync=exact(4)
                    while sync!=b'BNR1':sync=sync[1:]+exact(1)
                    got,status,cycles,count,checksum=struct.unpack('<IIIII',exact(20))
                    if got!=wire_seq or status or count!=len(inputs):
                        raise RuntimeError(f'Bad UART response seq={got}, status={status}, vertices={count}')
                    actual=np.frombuffer(exact(count*12),dtype='<i4').reshape(count,3)
                    if int(np.bitwise_xor.reduce(actual.ravel().view(np.uint32)))!=checksum:
                        raise RuntimeError('UART checksum mismatch')
                    if not np.array_equal(actual,expected):raise RuntimeError('KC705 coordinate mismatch')
                    camera.append(actual.astype(np.float32)/qscale);cycles_total+=cycles
                return t,sim_time,energy,np.concatenate(camera),cycles_total,(time.perf_counter()-wire_start)*1000
            pending=executor.submit(transact,*prepare(sequence))
            while not a.frames or sequence<a.frames:
                with lock:state.update(waiting=True,message='Waiting for UART')
                t,sim_time,energy,camera,cycles,roundtrip=pending.result()
                if not a.frames or sequence+1<a.frames:pending=executor.submit(transact,*prepare(sequence+1))
                render_start=time.perf_counter()
                rgba=np.asarray(rasterize(jnp.asarray(camera[None])))[0].transpose(1,2,0)
                if not np.isfinite(rgba).all():raise RuntimeError('Nonfinite rendered frame')
                rgb=np.rint(np.clip(rgba[:,:,:3],0,1)*255).astype(np.uint8)
                image=Image.fromarray(rgb).resize((512,512),Image.Resampling.BILINEAR)
                # Rod endpoints come from the verified board-transformed sphere centres.
                centres=np.stack([camera[:len(inputs)].mean(0),camera[len(inputs):].mean(0)])
                projected=np.asarray(renderer.perspective_distortion(jnp.asarray(centres[None]),renderer.viewing_angle))[0]
                def screen(point):return ((float(point[0])+1)*256,(1-float(point[1]))*256)
                points=[screen(support)]+[screen(v) for v in projected]
                trail.append(points[2]);draw=ImageDraw.Draw(image)
                if len(trail)>1:draw.line(list(trail),fill=(36,69,88),width=2)
                radius=.18/(math.tan(math.radians(renderer.viewing_angle))*float(centres[0,2]))*256
                for index in (0,1):
                    x0,y0=points[index];x1,y1=points[index+1]
                    length=math.hypot(x1-x0,y1-y0);dx=(x1-x0)/length;dy=(y1-y0)/length
                    inset0=5 if index==0 else radius;inset1=radius
                    draw.line((x0+dx*inset0,y0+dy*inset0,x1-dx*inset1,y1-dy*inset1),fill=(190,205,218),width=4)
                sx,sy=points[0];draw.line((sx-24,sy-7,sx+24,sy-7),fill=(115,133,152),width=5)
                draw.ellipse((sx-5,sy-5,sx+5,sy+5),fill=(229,237,244))
                png=io.BytesIO();image.save(png,format='PNG');encoded=png.getvalue()
                render_ms=(time.perf_counter()-render_start)*1000;completed=time.perf_counter()
                if previous is not None:intervals.append(completed-previous)
                previous=completed
                drift=abs(energy-physics.initial_energy)/max(abs(physics.initial_energy),1)*100
                item={'connected':True,'waiting':False,'sequence':sequence,'timestamp':time.time(),
                      'fps':len(intervals)/sum(intervals) if intervals else 1/(completed-t),
                      'frame_ms':(completed-t)*1000,'fpga_compute_ms':cycles/100000.,
                      'uart_and_host_wait_ms':max(0,roundtrip-cycles/100000.),'host_render_ms':render_ms,
                      'sim_time':sim_time,'energy_drift_percent':drift,'energy':energy,'dt':physics.dt,
                      'vertices':len(camera),'verified':True,'baud':a.baud,'azimuth':0.,
                      'message':'JAX double-pendulum physics / verified physical KC705 transforms'}
                log.write(json.dumps(item)+'\n');(a.out/'latest.json').write_text(json.dumps(item,indent=2))
                (a.out/'latest.png').write_bytes(encoded)
                with lock:state.update(item,png=base64.b64encode(encoded).decode())
                if sequence%60==0:print(f"frame={sequence} FPS={item['fps']:.1f} sim={sim_time:.2f}s energy_drift={drift:.5f}% verified",flush=True)
                sequence+=1
    except Exception as exc:
        with lock:state.update(connected=False,message=str(exc))
        print('PHYSICS STOPPED:',exc,flush=True)
        while True:time.sleep(1)
    finally:executor.shutdown(wait=False,cancel_futures=True);log.close()
    server.shutdown()
if __name__=='__main__':main()
