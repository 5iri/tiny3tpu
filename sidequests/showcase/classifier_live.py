#!/usr/bin/env python3
"""Show trained classifier results from the physical board; no host inference."""
import argparse,base64,hashlib,io,json,threading,time
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
import serial
from protocol import transact
ROOT=Path(__file__).resolve().parents[2]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--port',default='/dev/cu.usbserial-0001');p.add_argument('--frames',type=int,default=0);a=p.parse_args();out=ROOT/'build-classifier';media=ROOT/'media/showcase/gifs';media.mkdir(exist_ok=True)
 samples=np.load(out/'samples.npz');expected=np.load(out/'expected.npy');training=json.loads((out/'training-report.json').read_text());state={};lock=threading.Lock();frames=[];records=[]
 font='/System/Library/Fonts/Supplemental/Arial.ttf';large=ImageFont.truetype(font,28);small=ImageFont.truetype(font,19)
 page=b'''<!doctype html><html><meta name="viewport" content="width=device-width"><title>KC705 trained MNIST classifier</title><body style="margin:0;background:#0f1621;color:white;font:18px sans-serif"><img id="frame" style="width:100%;max-width:760px"><p id="status"></p><script>const frameEl=document.getElementById('frame'),statusEl=document.getElementById('status');setInterval(async()=>{try{let s=await(await fetch('/state')).json();frameEl.src='data:image/png;base64,'+s.png;statusEl.textContent=Date.now()/1000-s.timestamp<3?'Live board / checksum and reference verified':'Last captured frame / board stream stale'}catch(e){statusEl.textContent='Stream unavailable'}},150)</script></body></html>'''
 class Handler(BaseHTTPRequestHandler):
  def do_GET(self):
   if self.path=='/':b=page;mime='text/html'
   elif self.path.startswith('/state'):
    with lock:b=json.dumps(state).encode()
    mime='application/json'
   else:self.send_error(404);return
   self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
  def log_message(self,*args):pass
 server=ThreadingHTTPServer(('127.0.0.1',8766),Handler);threading.Thread(target=server.serve_forever,daemon=True).start()
 with serial.Serial(a.port,921600,timeout=1,write_timeout=5) as uart:
  uart.reset_input_buffer();seq=0
  while not a.frames or seq<a.frames:
   index=seq%20;rec,data=transact(uart,seq,index);assert rec['status']==0 and rec['backend_calls']==1
   np.testing.assert_array_equal(data[:10].view(np.uint32),expected[index].view(np.uint32));assert data[10]==np.argmax(expected[index]);pred=int(data[10]);label=int(samples['labels'][index]);rec.update(sample=index,true_label=label,board_prediction=pred,all_logits_bit_exact=True)
   im=Image.new('RGB',(760,720),(15,22,33));d=ImageDraw.Draw(im);d.text((26,20),'TINY3TPU / PHYSICAL KC705 / 100 MHz',font=small,fill='#52d8c9');d.text((26,57),'Trained MNIST digit classifier / int8 TPU',font=large,fill='white')
   digit=Image.fromarray(samples['images'][index]).resize((280,280),Image.Resampling.NEAREST).convert('RGB');im.paste(digit,(26,132));d.text((26,441),f'Board prediction: {pred}',font=large,fill='#b2f073' if pred==label else '#ff9b7a');d.text((26,484),f'Test label: {label} / sample {index}',font=small,fill='white')
   low=float(data[:10].min());high=float(data[:10].max())
   for i,value in enumerate(data[:10]):
    y=128+i*37;d.text((348,y),str(i),font=small,fill='white');width=int((float(value)-low)/max(high-low,1e-9)*290);d.rectangle((379,y+3,379+width,y+27),fill='#52d8c9' if i==pred else '#31586d')
   d.text((348,520),'Relative logit bars / not probabilities',font=small,fill='white');d.text((26,566),f"Board compute: {rec['compute_ms']:.2f} ms / 1 TPU matrix product",font=large,fill='#b2f073');d.text((26,613),f"Held-out int8 accuracy: {training['int8_test_accuracy']*100:.2f}% / 10,000 images",font=small,fill='white');d.text((26,651),'First 20 test images / no cherry-picking / no host model execution',font=small,fill='white');d.text((26,683),f'Request {seq} / checksum + all 10 logits verified',font=small,fill='#52d8c9')
   buf=io.BytesIO();im.save(buf,format='PNG')
   with lock:state.update(**rec,png=base64.b64encode(buf.getvalue()).decode(),timestamp=time.time())
   if seq<20:frames.append(im);records.append(rec)
   if seq==19:
    frames[0].save(media/'classifier.gif',save_all=True,append_images=frames[1:],duration=800,loop=0)
    report={'passed':True,'source':'Physical KC705 trained classifier','bitstream_sha256':hashlib.sha256((out/'board/soc.bit').read_bytes()).hexdigest(),'training':training,'physical_samples':records,'playback_frame_ms':800,'playback_note':'Presentation paced at 0.8 seconds per image; displayed compute timings are measured board cycles.'};(media/'classifier-capture.json').write_text(json.dumps(report,indent=2));(out/'physical-check.json').write_text(json.dumps(report,indent=2));print('GIF SAVED / 20 physical images verified',flush=True)
   print(seq,index,pred,label,rec['compute_ms'],flush=True);seq+=1;time.sleep(.6)
 server.shutdown()
if __name__=='__main__':main()
