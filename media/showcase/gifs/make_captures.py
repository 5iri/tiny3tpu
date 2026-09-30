import json,time,urllib.request,base64,io
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
out=Path(__file__).resolve().parent;out.mkdir(parents=True,exist_ok=True)
font='/System/Library/Fonts/Supplemental/Arial.ttf'
f=ImageFont.truetype(font,24);small=ImageFont.truetype(font,17)
def card(title):
 im=Image.new('RGB',(760,720),(15,22,33));d=ImageDraw.Draw(im);d.text((26,20),'TINY3TPU / PHYSICAL KC705 / 100 MHz',font=small,fill='#52d8c9');d.text((26,57),title,font=f,fill='white');return im,d
banana=[];classifier=[];times=[];seen=None;start=time.monotonic()
while len(banana)<105:
 s=json.load(urllib.request.urlopen('http://127.0.0.1:8766/state'));b=s['examples'].get('3')
 if b and b['sequence']!=seen:
  seen=b['sequence'];im,d=card('Rotating banana / compiled on-board state')
  image=Image.open(io.BytesIO(base64.b64decode(b['png'])));im.paste(image,(124,102));d.text((26,634),f"Board compute {b['compute_ms']:.2f} ms / request {seen}",font=f,fill='#b2f073');d.text((26,677),'CPU angle + TPU camera transform / host pixels only',font=small,fill='white');banana.append(im);times.append(time.monotonic())
  if len(banana)%3==0:
   r=s['examples']['0'];im,d=card('Synthetic classifier-style MLP / live execution')
   d.text((26,103),'4 inputs / 5 output scores / 2 TPU matrix products',font=small,fill='white')
   for row in range(4):
    for col in range(5):
     v=r['outputs'][row*5+col];x=26+col*142;y=151+row*98
     d.rectangle((x,y,x+132,y+84),fill=(15,110,111) if v>=0 else (123,62,48));d.text((x+12,y+28),f'{v:.0f}',font=f,fill='white')
   d.text((26,575),f"Latest MLP request {r['sequence']} / {r['compute_ms']:.2f} ms",font=f,fill='#b2f073')
   d.text((26,621),'Same seeded fixture repeated; outputs are expected to stay fixed.',font=small,fill='white');d.text((26,653),'No trained-model accuracy or class-label claim.',font=small,fill='white')
   d.rectangle((26,692,26+int((len(banana)%30)/30*708),700),fill='#52d8c9');classifier.append(im)
 time.sleep(.025)
seconds=times[-1]-times[0];duration=round(seconds/len(banana)*1000/10)*10
banana[0].save(out/'banana.gif',save_all=True,append_images=banana[1:],duration=duration,loop=0)
classifier[0].save(out/'classifier-synthetic.gif',save_all=True,append_images=classifier[1:],duration=duration*3,loop=0)
(out/'banana-capture.json').write_text(json.dumps({'banana_frames':len(banana),'classifier_frames':len(classifier),'capture_seconds':seconds,'frame_duration_ms':duration,'source':'physical board live HTTP results; repeated fixed MLP fixture'},indent=2))
print(seconds,duration)
