import json,time,urllib.request,base64,io
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
out=Path(__file__).resolve().parent;f=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',24);sm=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',17)
frames=[];records=[];seen=-1;start=time.monotonic()
while len(frames)<64:
 try:s=json.load(urllib.request.urlopen('http://127.0.0.1:8765/state',timeout=2))
 except Exception:
  if len(frames)>1:break
  time.sleep(.5);continue
 if s.get('connected') and s['sequence']!=seen:
  seen=s['sequence'];im=Image.new('RGB',(760,720),(15,22,33));d=ImageDraw.Draw(im);d.text((26,20),'TINY3TPU / PHYSICAL KC705 / 100 MHz',font=sm,fill='#52d8c9');d.text((26,57),'Cloth / StableHLO CPU physics + TPU transform',font=f,fill='white');im.paste(Image.open(io.BytesIO(base64.b64decode(s['png']))),(124,102));d.text((26,632),f"Simulation {s['sim_time']:.4f} s / step {s['simulation_steps']}",font=f,fill='#b2f073');d.text((26,673),f"Time-compressed playback / {s['physics_ms']/32:.1f} ms per physics step",font=sm,fill='white');frames.append(im);records.append({k:v for k,v in s.items() if k!='png'});print(len(frames),s['sim_time'],flush=True)
 time.sleep(.1)
frames[0].save(out/'cloth.gif',save_all=True,append_images=frames[1:],duration=100,loop=0)
(out/'cloth-capture.json').write_text(json.dumps({'source':'physical compiled cloth board results','capture_seconds':time.monotonic()-start,'frames':len(frames),'playback_frame_ms':100,'time_compressed':True,'records':records},indent=2))
print('SAVED',len(frames),flush=True)
